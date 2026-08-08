"""Pure-Pillow resamplers. Always available, instant, invents no detail."""

from __future__ import annotations

import threading

from PIL import Image

from .base import ModelInfo, ProgressFn, UpscaleBackend

RESAMPLERS: dict[str, Image.Resampling] = {
    "lanczos": Image.Resampling.LANCZOS,
    "bicubic": Image.Resampling.BICUBIC,
    "bilinear": Image.Resampling.BILINEAR,
    "hamming": Image.Resampling.HAMMING,
    "box": Image.Resampling.BOX,
    "nearest": Image.Resampling.NEAREST,
}

RESAMPLER_LABELS: dict[str, str] = {
    "lanczos": "Lanczos — sharpest, default",
    "bicubic": "Bicubic — smooth",
    "bilinear": "Bilinear — fast",
    "hamming": "Hamming — soft downscale",
    "box": "Box — averaging",
    "nearest": "Nearest — hard pixels, pixel art",
}


def resample(
    image: Image.Image, size: tuple[int, int], method: str = "lanczos"
) -> Image.Image:
    """Resize to an exact size with the named resampler."""
    if image.size == tuple(size):
        return image
    return image.resize(size, RESAMPLERS.get(method, Image.Resampling.LANCZOS))


class ClassicBackend(UpscaleBackend):
    key = "classic"
    label = "Classic resample"
    description = "Instant. Stretches existing pixels, adds no new detail."

    def is_available(self) -> bool:
        return True

    def models(self) -> tuple[ModelInfo, ...]:
        return tuple(
            ModelInfo(key, RESAMPLER_LABELS[key], (2, 3, 4, 6, 8), RESAMPLER_LABELS[key])
            for key in RESAMPLERS
        )

    def supported_factors(self, model: str) -> tuple[int, ...]:
        return (2, 3, 4)

    def upscale(
        self,
        image: Image.Image,
        factor: int,
        *,
        model: str = "lanczos",
        denoise_level: int = -1,
        tile_size: int = 0,
        gpu_id: int = 0,
        use_gpu: bool = True,
        progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
    ) -> Image.Image:
        self._check(cancel)
        if progress:
            progress(0.0, f"Resampling x{factor}")
        target = (image.width * factor, image.height * factor)
        result = resample(image, target, model if model in RESAMPLERS else "lanczos")
        if progress:
            progress(1.0, "Resampled")
        return result
