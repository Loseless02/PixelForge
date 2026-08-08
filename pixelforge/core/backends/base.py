"""Backend interface shared by the classic and AI upscalers."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

ProgressFn = Callable[[float, str], None]


class UpscaleError(RuntimeError):
    """Raised when a backend cannot produce a result."""


class Cancelled(RuntimeError):
    """Raised when the caller's cancel token was set mid-run."""


@dataclass(frozen=True)
class ModelInfo:
    key: str
    label: str
    factors: tuple[int, ...]
    description: str = ""
    denoise_levels: tuple[int, ...] = ()


class UpscaleBackend(ABC):
    key: str = ""
    label: str = ""
    description: str = ""

    @abstractmethod
    def is_available(self) -> bool:
        """True when this backend can actually run on this machine."""

    @abstractmethod
    def models(self) -> tuple[ModelInfo, ...]:
        """Models this backend exposes to the UI."""

    @abstractmethod
    def upscale(
        self,
        image: Image.Image,
        factor: int,
        *,
        model: str,
        denoise_level: int = -1,
        tile_size: int = 0,
        gpu_id: int = 0,
        use_gpu: bool = True,
        progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
    ) -> Image.Image:
        """Return ``image`` enlarged by ``factor``."""

    def supported_factors(self, model: str) -> tuple[int, ...]:
        for info in self.models():
            if info.key == model:
                return info.factors
        return (2, 3, 4)

    @staticmethod
    def _check(cancel: threading.Event | None) -> None:
        if cancel is not None and cancel.is_set():
            raise Cancelled("cancelled")
