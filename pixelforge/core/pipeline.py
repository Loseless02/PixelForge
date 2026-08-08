"""The render pipeline: source file plus EditSettings in, image or file out.

Fixed stage order:

    load -> crop -> rotate/flip -> AI upscale chain -> fit to target
         -> adjustments -> export

Cropping first means the target resolution always describes the *visible*
result. Adjustments run last so tone changes are not amplified or smeared by
the super-resolution pass.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps

from . import adjust, analyze, geometry, imageio
from .backends import get_backend
from .backends.base import Cancelled, UpscaleError
from .backends.classic import resample
from .models import EditSettings, FitMode, Job, JobStatus, SizeMode

ProgressFn = Callable[[float, str], None]

PREVIEW_MAX_EDGE = 1400
AI_PREVIEW_MAX_EDGE = 1100
AI_PREVIEW_SOURCE_CAP = 520


class RenderResult:
    __slots__ = ("elapsed", "image", "output_path", "plan", "skipped", "source")

    def __init__(
        self,
        image: Image.Image | None,
        output_path: Path | None,
        elapsed: float,
        plan: str,
        skipped: bool = False,
        source: Image.Image | None = None,
    ) -> None:
        self.image = image
        # The cropped/rotated original, so callers can build a fair comparison.
        self.source = source
        self.output_path = output_path
        self.elapsed = elapsed
        self.plan = plan
        self.skipped = skipped


# --------------------------------------------------------------------- stages
AUTO_MODEL = "auto"


def resolve_model(image: Image.Image, settings: EditSettings) -> EditSettings:
    """Replace the ``auto`` model with whatever suits this particular image.

    Returns ``settings`` untouched when nothing needs resolving, so the common
    path costs nothing.
    """
    if settings.model != AUTO_MODEL or settings.backend == "classic":
        return settings
    resolved = settings.copy()
    resolved.model = analyze.recommend(image)
    return resolved


def effective_fit(settings: EditSettings) -> FitMode:
    """Fit mode for the resample step, given what ``resolve_target`` already did.

    Only EXACT mode leaves work for the fit step. SCALE, PERCENT and LONG_EDGE
    already return an aspect-correct box, and so does EXACT+CONTAIN — running
    contain a second time would shave a pixel off through rounding.
    """
    if settings.size_mode is not SizeMode.EXACT:
        return FitMode.STRETCH
    if settings.fit_mode is FitMode.CONTAIN:
        return FitMode.STRETCH
    return settings.fit_mode


def apply_geometry_stage(image: Image.Image, settings: EditSettings) -> Image.Image:
    """Crop, rotate and flip — everything that happens before scaling."""
    if not settings.crop.is_empty:
        crop = settings.crop.clamped(image.width, image.height)
        image = image.crop((crop.x, crop.y, crop.x + crop.width, crop.y + crop.height))
    if settings.rotation:
        image = image.rotate(-int(settings.rotation), expand=True)
    if settings.flip_h:
        image = ImageOps.mirror(image)
    if settings.flip_v:
        image = ImageOps.flip(image)
    return image


def fit_to_target(
    image: Image.Image,
    target_w: int,
    target_h: int,
    mode: FitMode,
    method: str,
    background: str,
) -> Image.Image:
    """Resample and compose so the result matches the target box exactly."""
    resize_to, canvas, offset = geometry.fit_plan(
        image.width, image.height, target_w, target_h, mode
    )
    image = resample(image, resize_to, method)
    if canvas == resize_to and offset == (0, 0):
        return image

    if mode is FitMode.COVER:
        left = max(0, -offset[0])
        top = max(0, -offset[1])
        return image.crop((left, top, left + canvas[0], top + canvas[1]))

    base_mode = "RGBA" if image.mode == "RGBA" else "RGB"
    base = Image.new(base_mode, canvas, background if base_mode == "RGB" else (0, 0, 0, 0))
    if base_mode == "RGBA":
        base.paste(image, offset)
    else:
        base.paste(image, offset)
    return base


def plan_factors(
    src_w: int, src_h: int, target_w: int, target_h: int, settings: EditSettings
) -> list[int]:
    """AI passes this job will run, honouring the quality settings."""
    backend = get_backend(settings.backend)
    if backend.key == "classic":
        return []
    factors = geometry.plan_ai_factor(
        src_w,
        src_h,
        target_w,
        target_h,
        available=backend.supported_factors(settings.model),
        max_chain=max(1, settings.max_chain),
        oversample=settings.oversample,
    )
    # Supersampling is only worth an extra pass while it stays inside the
    # memory guard; otherwise fall back to the plain covering chain.
    while factors and geometry.plan_pixels(src_w, src_h, factors) > geometry.MAX_PIXELS:
        factors = factors[:-1]
        if not factors:
            factors = geometry.plan_ai_factor(
                src_w, src_h, target_w, target_h,
                available=backend.supported_factors(settings.model),
                max_chain=1,
            )
            break
    return factors


def upscale_stage(
    image: Image.Image,
    settings: EditSettings,
    target_w: int,
    target_h: int,
    *,
    tile_size: int = 0,
    gpu_id: int = 0,
    use_gpu: bool = True,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Image.Image:
    """Run the AI factor chain, if any is needed."""
    backend = get_backend(settings.backend)
    if backend.key == "classic":
        return image

    factors = plan_factors(image.width, image.height, target_w, target_h, settings)
    if not factors:
        return image

    total = len(factors)
    for index, factor in enumerate(factors):
        def step(fraction: float, note: str, _i: int = index) -> None:
            if progress:
                progress((_i + fraction) / total, note)

        image = backend.upscale(
            image,
            factor,
            model=settings.model,
            denoise_level=settings.denoise_level,
            tile_size=tile_size,
            gpu_id=gpu_id,
            use_gpu=use_gpu,
            tta=settings.tta,
            progress=step,
            cancel=cancel,
        )
    return image


# --------------------------------------------------------------------- render
def render(
    source: Path | str | imageio.LoadedImage,
    settings: EditSettings,
    *,
    tile_size: int = 0,
    gpu_id: int = 0,
    use_gpu: bool = True,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Image.Image:
    """Render the full-resolution result in memory."""
    loaded = source if isinstance(source, imageio.LoadedImage) else imageio.load(source)
    settings = resolve_model(loaded.image, settings)
    image = apply_geometry_stage(loaded.image, settings)

    target_w, target_h = geometry.resolve_target(image.width, image.height, settings)

    if progress:
        progress(0.02, "Preparing")

    def upscale_progress(fraction: float, note: str) -> None:
        if progress:
            progress(0.05 + fraction * 0.80, note)

    image = upscale_stage(
        image,
        settings,
        target_w,
        target_h,
        tile_size=tile_size,
        gpu_id=gpu_id,
        use_gpu=use_gpu,
        progress=upscale_progress,
        cancel=cancel,
    )

    if cancel is not None and cancel.is_set():
        raise Cancelled("cancelled")

    if progress:
        progress(0.88, "Fitting")
    image = fit_to_target(
        image,
        target_w,
        target_h,
        effective_fit(settings),
        settings.resample,
        settings.export.background,
    )

    if progress:
        progress(0.94, "Adjusting")
    image = adjust.apply(image, settings.adjustments)

    if progress:
        progress(1.0, "Done")
    return image


def preview_size(
    loaded: imageio.LoadedImage, settings: EditSettings, max_edge: int
) -> tuple[int, int, Image.Image]:
    """Preview box for these settings, plus the cropped/rotated source."""
    image = apply_geometry_stage(loaded.image, settings)
    target_w, target_h = geometry.resolve_target(image.width, image.height, settings)
    scale = min(1.0, max_edge / max(target_w, target_h))
    return max(1, round(target_w * scale)), max(1, round(target_h * scale)), image


def render_preview(
    loaded: imageio.LoadedImage,
    settings: EditSettings,
    max_edge: int = PREVIEW_MAX_EDGE,
) -> Image.Image:
    """Fast, AI-free approximation for the live preview pane.

    Adjustments are exact; the upscale is simulated with Lanczos so the pane
    stays interactive while sliders move. :func:`render_ai_preview` replaces it
    once the settings stop changing.
    """
    preview_w, preview_h, image = preview_size(loaded, settings, max_edge)

    # Downscale the source first when it dwarfs the preview box — much faster
    # and visually identical at preview resolution.
    guard = max(preview_w, preview_h) * 2
    if max(image.size) > guard:
        image = ImageOps.contain(image, (guard, guard), Image.Resampling.LANCZOS)

    image = fit_to_target(
        image, preview_w, preview_h, effective_fit(settings), settings.resample,
        settings.export.background,
    )
    return adjust.apply(image, settings.adjustments)


def render_ai_preview(
    loaded: imageio.LoadedImage,
    settings: EditSettings,
    max_edge: int = AI_PREVIEW_MAX_EDGE,
    *,
    source_cap: int = AI_PREVIEW_SOURCE_CAP,
    tile_size: int = 0,
    gpu_id: int = 0,
    use_gpu: bool = True,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Image.Image:
    """Preview that actually runs the model, so the split view means something.

    The source is capped to ``source_cap`` pixels on its long edge first. The
    model sees a representative amount of detail per pixel, one pass takes a
    second or two instead of a minute, and the result is resampled into the
    same box the fast preview uses so the two can swap seamlessly.
    """
    settings = resolve_model(loaded.image, settings)
    preview_w, preview_h, image = preview_size(loaded, settings, max_edge)

    if max(image.size) > source_cap:
        image = ImageOps.contain(
            image, (source_cap, source_cap), Image.Resampling.LANCZOS
        )

    image = upscale_stage(
        image,
        settings,
        preview_w,
        preview_h,
        tile_size=tile_size,
        gpu_id=gpu_id,
        use_gpu=use_gpu,
        progress=progress,
        cancel=cancel,
    )
    if cancel is not None and cancel.is_set():
        raise Cancelled("cancelled")

    image = fit_to_target(
        image, preview_w, preview_h, effective_fit(settings), settings.resample,
        settings.export.background,
    )
    return adjust.apply(image, settings.adjustments)


def plan_summary(width: int, height: int, settings: EditSettings) -> str:
    """One-line description of what running this job would do."""
    src_w, src_h = geometry.source_after_transform(width, height, settings)
    target_w, target_h = geometry.resolve_target(src_w, src_h, settings)
    factors = plan_factors(src_w, src_h, target_w, target_h, settings)
    if not factors:
        return f"{src_w}x{src_h} to {target_w}x{target_h} · resample only"
    product = math.prod(factors)
    chain = "+".join(f"x{f}" for f in factors)
    extras = " · TTA" if settings.tta else ""
    return (
        f"{src_w}x{src_h} to {target_w}x{target_h} · AI {chain} "
        f"({src_w * product}x{src_h * product}) then resample{extras}"
    )


# ------------------------------------------------------------------ job runner
def run_job(
    job: Job,
    out_dir: Path | None,
    *,
    tile_size: int = 0,
    gpu_id: int = 0,
    use_gpu: bool = True,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> RenderResult:
    """Render one queued file and write it to disk."""
    started = time.perf_counter()
    settings = job.settings
    export = settings.export

    spec = next(
        (s for s in imageio.output_formats() if s.key == export.format.upper()), None
    )
    extension = spec.extension if spec else ".png"
    out_path = imageio.resolve_output_path(
        job.source, out_dir, extension, export.suffix, export.overwrite_policy
    )

    if export.overwrite_policy == "skip" and out_path.exists():
        job.status = JobStatus.DONE
        job.output = out_path
        job.message = "Skipped — output already exists"
        return RenderResult(None, out_path, 0.0, "skipped", skipped=True)

    loaded = imageio.load(job.source)
    job.source_size = loaded.size

    try:
        image = render(
            loaded,
            settings,
            tile_size=tile_size,
            gpu_id=gpu_id,
            use_gpu=use_gpu,
            progress=progress,
            cancel=cancel,
        )
    except Cancelled:
        job.status = JobStatus.CANCELLED
        job.message = "Cancelled"
        raise
    except (UpscaleError, OSError, ValueError) as exc:
        job.status = JobStatus.FAILED
        job.message = str(exc)
        raise

    imageio.save(
        image,
        out_path,
        export.format,
        jpeg_quality=export.jpeg_quality,
        webp_quality=export.webp_quality,
        webp_lossless=export.webp_lossless,
        png_compression=export.png_compression,
        exif=loaded.exif,
        icc_profile=loaded.icc_profile,
        keep_metadata=export.keep_metadata,
        strip_gps=export.strip_gps,
        background=export.background,
    )

    elapsed = time.perf_counter() - started
    job.status = JobStatus.DONE
    job.output = out_path
    job.result_size = image.size
    job.elapsed = elapsed
    job.message = f"{image.width}x{image.height} in {elapsed:.1f}s"
    return RenderResult(
        image, out_path, elapsed, plan_summary(*loaded.size, settings),
        source=apply_geometry_stage(loaded.image, settings),
    )
