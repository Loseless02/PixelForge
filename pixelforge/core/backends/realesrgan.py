"""Real-ESRGAN via the bundled ``realesrgan-ncnn-vulkan`` executable.

The binary is a self-contained ncnn/Vulkan build: no PyTorch, no CUDA, no
network access. It works on NVIDIA, AMD and Intel GPUs, and falls back to CPU
with ``-g -1``. Images go in and out as temporary PNG files.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image

from ...config import vendor_dir
from .base import Cancelled, ModelInfo, ProgressFn, UpscaleBackend, UpscaleError

_PERCENT = re.compile(rb"(\d+(?:\.\d+)?)%")

_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        "realesrgan-x4plus",
        "Real-ESRGAN x4plus",
        (4,),
        "Photos and general images. Best all-round quality, handles JPEG noise.",
    ),
    ModelInfo(
        "realesrgan-x4plus-anime",
        "Real-ESRGAN x4plus anime",
        (4,),
        "Illustrations, anime, flat colour art. Much sharper lines, wrong for photos.",
    ),
    ModelInfo(
        "realesr-animevideov3",
        "Real-ESRGAN anime video v3",
        (2, 3, 4),
        "Fast anime model with native x2/x3/x4. Small file, lowest VRAM.",
    ),
)


class RealesrganBackend(UpscaleBackend):
    key = "realesrgan"
    label = "Real-ESRGAN (AI)"
    description = "Neural super-resolution. Reconstructs detail. Runs fully offline."

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (vendor_dir() / "realesrgan")

    # ------------------------------------------------------------------ paths
    @property
    def executable(self) -> Path:
        name = "realesrgan-ncnn-vulkan"
        if sys.platform == "win32":
            name += ".exe"
        return self._root / name

    @property
    def model_dir(self) -> Path:
        return self._root / "models"

    def is_available(self) -> bool:
        return self.executable.is_file() and self.model_dir.is_dir()

    def models(self) -> tuple[ModelInfo, ...]:
        if not self.is_available():
            return ()
        present = {p.stem for p in self.model_dir.glob("*.param")}
        return tuple(
            m
            for m in _MODELS
            if m.key in present or any(f"{m.key}-x{f}" in present for f in m.factors)
        )

    @lru_cache(maxsize=1)  # noqa: B019 - backend instances are module singletons
    def probe_devices(self) -> tuple[str, ...]:
        """GPU names reported by the binary, in ``-g`` index order.

        ncnn only prints its device table once a Vulkan instance exists, so the
        cheapest probe is a real run on a 4x4 pixel image (~1s, cached).
        """
        if not self.is_available():
            return ()
        try:
            with tempfile.TemporaryDirectory(prefix="pixelforge-probe-") as tmp:
                probe_in = Path(tmp) / "probe.png"
                Image.new("RGB", (4, 4), (0, 0, 0)).save(probe_in)
                proc = subprocess.run(
                    [
                        str(self.executable),
                        "-i", str(probe_in),
                        "-o", str(Path(tmp) / "probe_out.png"),
                        "-n", "realesr-animevideov3",
                        "-s", "2",
                        "-m", str(self.model_dir),
                    ],
                    capture_output=True,
                    timeout=60,
                    creationflags=_no_window(),
                )
        except (OSError, subprocess.SubprocessError):
            return ()
        text = (proc.stderr or b"").decode("utf-8", "replace")
        seen: dict[int, str] = {}
        for index, name in re.findall(r"\[(\d+)\s+([^\]]+)\]\s+queueC", text):
            seen.setdefault(int(index), name.strip())
        return tuple(seen[k] for k in sorted(seen))

    # -------------------------------------------------------------- upscaling
    def upscale(
        self,
        image: Image.Image,
        factor: int,
        *,
        model: str = "realesrgan-x4plus",
        denoise_level: int = -1,
        tile_size: int = 0,
        gpu_id: int = 0,
        use_gpu: bool = True,
        tta: bool = False,
        progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
    ) -> Image.Image:
        if not self.is_available():
            raise UpscaleError(
                "Real-ESRGAN binary not found. Run scripts/fetch_models.py or "
                "switch the backend to Classic resample."
            )
        self._check(cancel)

        factor = self._coerce_factor(model, factor)
        has_alpha = image.mode == "RGBA"
        source = image if image.mode in ("RGB", "RGBA") else image.convert("RGB")

        with tempfile.TemporaryDirectory(prefix="pixelforge-") as tmp:
            tmp_dir = Path(tmp)
            in_path = tmp_dir / "in.png"
            out_path = tmp_dir / "out.png"
            source.save(in_path, format="PNG", compress_level=1)

            command = [
                str(self.executable),
                "-i", str(in_path),
                "-o", str(out_path),
                "-n", self._model_name(model, factor),
                "-s", str(factor),
                "-m", str(self.model_dir),
                "-f", "png",
                "-g", str(gpu_id if use_gpu else -1),
            ]
            if tile_size > 0:
                command += ["-t", str(tile_size)]
            if tta:
                command.append("-x")

            self._run(command, progress, cancel, factor, model)

            if not out_path.is_file():
                raise UpscaleError("Real-ESRGAN produced no output file.")
            with Image.open(out_path) as handle:
                handle.load()
                result = handle.copy()

        if has_alpha and result.mode != "RGBA":
            result = result.convert("RGBA")
        elif not has_alpha and result.mode == "RGBA":
            result = result.convert("RGB")
        return result

    # --------------------------------------------------------------- internals
    def _coerce_factor(self, model: str, factor: int) -> int:
        allowed = self.supported_factors(model)
        if factor in allowed:
            return factor
        # Ask for the smallest supported factor that still covers the request.
        larger = [f for f in allowed if f >= factor]
        return min(larger) if larger else max(allowed)

    def supported_factors(self, model: str) -> tuple[int, ...]:
        for info in _MODELS:
            if info.key == model:
                return info.factors
        return (4,)

    @staticmethod
    def _model_name(model: str, factor: int) -> str:
        # animevideov3 ships one file per factor; the binary appends "-x{n}".
        return model

    def _run(
        self,
        command: list[str],
        progress: ProgressFn | None,
        cancel: threading.Event | None,
        factor: int,
        model: str,
    ) -> None:
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=_no_window(),
            )
        except OSError as exc:
            raise UpscaleError(f"Cannot launch Real-ESRGAN: {exc}") from exc

        tail: list[str] = []
        assert proc.stderr is not None
        try:
            for chunk in _iter_chunks(proc.stderr):
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    proc.wait(timeout=5)
                    raise Cancelled("cancelled")
                text = chunk.decode("utf-8", "replace").strip()
                if text:
                    tail.append(text)
                    del tail[:-12]
                match = _PERCENT.findall(chunk)
                if match and progress:
                    progress(float(match[-1]) / 100.0, f"{model} x{factor}")
        finally:
            proc.stderr.close()

        code = proc.wait()
        if code != 0:
            detail = " | ".join(tail[-4:]) or f"exit code {code}"
            raise UpscaleError(f"Real-ESRGAN failed: {detail}")
        if progress:
            progress(1.0, f"{model} x{factor} done")


def _iter_chunks(stream, size: int = 256):
    """Yield stderr as it arrives.

    ``read1`` returns whatever is already buffered instead of blocking for a
    full ``size`` bytes, which matters because the binary emits progress
    percentages without trailing newlines.
    """
    reader = getattr(stream, "read1", stream.read)
    while True:
        chunk = reader(size)
        if not chunk:
            return
        yield chunk


def _no_window() -> int:
    """Suppress the console window that would otherwise flash on Windows."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
