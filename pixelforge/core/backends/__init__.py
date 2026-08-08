"""Upscaling backends.

``classic`` is always available. ``realesrgan`` needs the bundled
``realesrgan-ncnn-vulkan`` binary plus a Vulkan-capable GPU; the registry
degrades to ``classic`` when it is missing.
"""

from __future__ import annotations

from .base import ProgressFn, UpscaleBackend, UpscaleError
from .classic import ClassicBackend
from .realesrgan import RealesrganBackend

_CLASSIC = ClassicBackend()
_REALESRGAN = RealesrganBackend()

BACKENDS: dict[str, UpscaleBackend] = {
    _CLASSIC.key: _CLASSIC,
    _REALESRGAN.key: _REALESRGAN,
}


def get_backend(key: str) -> UpscaleBackend:
    """Return the requested backend, falling back to ``classic``."""
    backend = BACKENDS.get(key, _CLASSIC)
    return backend if backend.is_available() else _CLASSIC


def available_backends() -> list[UpscaleBackend]:
    return [b for b in BACKENDS.values() if b.is_available()]


__all__ = [
    "BACKENDS",
    "ClassicBackend",
    "ProgressFn",
    "RealesrganBackend",
    "UpscaleBackend",
    "UpscaleError",
    "available_backends",
    "get_backend",
]
