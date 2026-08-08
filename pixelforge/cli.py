"""Headless batch interface: ``python -m pixelforge --cli ...``.

Useful for scripting and for CI, and it exercises exactly the same pipeline the
GUI uses.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import imageio, pipeline
from .core.backends import BACKENDS, available_backends
from .core.models import CropRect, EditSettings, FitMode, Job, Rotation, SizeMode
from .core.presets import LOOKS_BY_KEY, PRESETS_BY_KEY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pixelforge --cli",
        description="Offline AI image upscaler.",
    )
    parser.add_argument("inputs", nargs="*", type=Path,
                        help="Image files or folders.")
    parser.add_argument("-o", "--output", type=Path,
                        help="Output folder (default: alongside each source).")

    size = parser.add_argument_group("size")
    size.add_argument("-s", "--scale", type=float,
                      help="Multiply the source size, e.g. 2 or 3.5.")
    size.add_argument("--size", metavar="WxH",
                      help="Exact output size, e.g. 1920x1080.")
    size.add_argument("--preset", choices=sorted(PRESETS_BY_KEY),
                     help="Named resolution preset.")
    size.add_argument("--long-edge", type=int,
                      help="Scale so the longest side is this many pixels.")
    size.add_argument("--fit", choices=[m.value for m in FitMode], default="cover",
                      help="How to reconcile aspect ratio with an exact size.")
    size.add_argument("--crop", metavar="X,Y,W,H", help="Crop before scaling.")
    size.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0)

    ai = parser.add_argument_group("upscaler")
    ai.add_argument("-b", "--backend", choices=sorted(BACKENDS), default="realesrgan")
    ai.add_argument("-m", "--model", default="realesrgan-x4plus")
    ai.add_argument("--resample", default="lanczos")
    ai.add_argument("--cpu", action="store_true", help="Disable GPU acceleration.")
    ai.add_argument("--gpu-id", type=int, default=0)
    ai.add_argument("--tile", type=int, default=0,
                    help="Tile size; lower it if you run out of video memory.")

    look = parser.add_argument_group("look")
    look.add_argument("--look", choices=sorted(LOOKS_BY_KEY),
                      help="Apply a named adjustment preset.")
    look.add_argument("--sharpen", type=float, metavar="PERCENT",
                      help="Unsharp mask amount, 0-300.")
    look.add_argument("--denoise", type=float, metavar="AMOUNT",
                      help="Denoise strength, 0-100.")
    look.add_argument("--grayscale", action="store_true")

    out = parser.add_argument_group("output")
    out.add_argument("-f", "--format", default="PNG",
                     choices=[s.key for s in imageio.output_formats()])
    out.add_argument("-q", "--quality", type=int, default=92,
                     help="JPEG/WebP/AVIF quality, 40-100.")
    out.add_argument("--suffix", default="_upscaled")
    out.add_argument("--overwrite", action="store_true")
    out.add_argument("--strip-metadata", action="store_true")

    parser.add_argument("--list-devices", action="store_true",
                        help="Print detected GPUs and exit.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan for each file without rendering.")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def settings_from_args(args: argparse.Namespace) -> EditSettings:
    settings = EditSettings()
    settings.backend = args.backend
    settings.model = args.model
    settings.resample = args.resample
    settings.fit_mode = FitMode(args.fit)
    settings.rotation = Rotation(args.rotate)

    if args.preset:
        preset = PRESETS_BY_KEY[args.preset]
        settings.size_mode = SizeMode.EXACT
        settings.target_width, settings.target_height = preset.width, preset.height
    elif args.size:
        width, _, height = args.size.lower().partition("x")
        settings.size_mode = SizeMode.EXACT
        settings.target_width, settings.target_height = int(width), int(height)
    elif args.long_edge:
        settings.size_mode = SizeMode.LONG_EDGE
        settings.long_edge = args.long_edge
    else:
        settings.size_mode = SizeMode.SCALE
        settings.scale = args.scale if args.scale else 2.0

    if args.crop:
        x, y, width, height = (int(v) for v in args.crop.split(","))
        settings.crop = CropRect(x, y, width, height)

    if args.look:
        preset = LOOKS_BY_KEY[args.look]
        settings.adjustments = type(preset.adjustments)(**preset.adjustments.__dict__)
    if args.sharpen is not None:
        settings.adjustments.unsharp_amount = args.sharpen
    if args.denoise is not None:
        settings.adjustments.denoise = args.denoise
    if args.grayscale:
        settings.adjustments.grayscale = True

    settings.export.format = args.format
    settings.export.jpeg_quality = args.quality
    settings.export.webp_quality = args.quality
    settings.export.suffix = args.suffix
    settings.export.overwrite_policy = "overwrite" if args.overwrite else "suffix"
    settings.export.keep_metadata = not args.strip_metadata
    return settings


def collect_inputs(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found += sorted(p for p in path.rglob("*")
                            if p.is_file() and imageio.is_supported(p))
        elif path.is_file() and imageio.is_supported(path):
            found.append(path)
    return found


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_devices:
        backend = BACKENDS["realesrgan"]
        if not backend.is_available():
            print("Real-ESRGAN binary not found. Run scripts/fetch_models.py.")
            return 1
        devices = backend.probe_devices()
        if not devices:
            print("No Vulkan device found — CPU only.")
        for index, name in enumerate(devices):
            print(f"{index}: {name}")
        return 0

    if not args.inputs:
        build_parser().print_help()
        return 2

    files = collect_inputs(args.inputs)
    if not files:
        print("No supported images found.", file=sys.stderr)
        return 1

    settings = settings_from_args(args)
    backends = {b.key for b in available_backends()}
    if settings.backend not in backends:
        print(f"Backend '{settings.backend}' unavailable, falling back to classic.",
              file=sys.stderr)
        settings.backend = "classic"

    failures = 0
    for index, path in enumerate(files, start=1):
        job = Job(source=path, settings=settings.copy())
        try:
            with imageio.Image.open(path) as probe:
                width, height = probe.size
            plan = pipeline.plan_summary(width, height, job.settings)
        except Exception as exc:
            print(f"[{index}/{len(files)}] {path.name}: cannot read ({exc})",
                  file=sys.stderr)
            failures += 1
            continue

        print(f"[{index}/{len(files)}] {path.name}  ·  {plan}")
        if args.dry_run:
            continue

        def progress(fraction: float, note: str) -> None:
            if args.verbose:
                print(f"    {fraction * 100:5.1f}%  {note}", end="\r", flush=True)

        try:
            result = pipeline.run_job(
                job, args.output,
                tile_size=args.tile, gpu_id=args.gpu_id, use_gpu=not args.cpu,
                progress=progress,
            )
        except Exception as exc:
            print(f"    failed: {exc}", file=sys.stderr)
            failures += 1
            continue

        if args.verbose:
            print(" " * 40, end="\r")
        if result.skipped:
            print(f"    skipped, {result.output_path} exists")
        else:
            print(f"    wrote {result.output_path}  ({result.elapsed:.1f}s)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
