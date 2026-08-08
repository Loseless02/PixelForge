"""Value objects describing an edit. Everything here is plain data.

The whole editing model is non-destructive: the GUI only ever mutates an
``EditSettings`` instance, and :mod:`pixelforge.core.pipeline` renders the
source file through it on demand.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any


class FitMode(str, Enum):
    """How the image is made to match a target width/height exactly."""

    STRETCH = "stretch"   # ignore aspect ratio
    CONTAIN = "contain"   # fit inside, result may be smaller than target
    COVER = "cover"       # fill target, crop the overflow
    PAD = "pad"           # fit inside, letterbox to exact target


class SizeMode(str, Enum):
    """How the target resolution is expressed."""

    SCALE = "scale"        # multiply source size by ``scale``
    EXACT = "exact"        # explicit width x height
    LONG_EDGE = "long_edge"  # longest side becomes ``long_edge`` px
    PERCENT = "percent"    # percentage of source size


class Rotation(int, Enum):
    NONE = 0
    CW_90 = 90
    HALF = 180
    CCW_90 = 270


@dataclass(frozen=True)
class CropRect:
    """Crop in source-pixel coordinates."""

    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def clamped(self, img_w: int, img_h: int) -> CropRect:
        x = max(0, min(self.x, img_w - 1))
        y = max(0, min(self.y, img_h - 1))
        w = max(1, min(self.width, img_w - x))
        h = max(1, min(self.height, img_h - y))
        return CropRect(x, y, w, h)


@dataclass
class Adjustments:
    """Tone / colour corrections. Neutral values are all zero or 1.0."""

    brightness: float = 1.0     # 0.0 .. 3.0
    contrast: float = 1.0       # 0.0 .. 3.0
    saturation: float = 1.0     # 0.0 .. 3.0
    sharpness: float = 1.0      # 0.0 .. 4.0
    gamma: float = 1.0          # 0.1 .. 3.0
    temperature: float = 0.0    # -100 (cool) .. +100 (warm)
    tint: float = 0.0           # -100 (green) .. +100 (magenta)
    vignette: float = 0.0       # 0 .. 100
    blur: float = 0.0           # gaussian radius in px
    denoise: float = 0.0        # 0 .. 100, edge-preserving
    unsharp_amount: float = 0.0  # 0 .. 300 (%)
    unsharp_radius: float = 2.0
    grayscale: bool = False
    sepia: bool = False
    invert: bool = False
    auto_contrast: bool = False
    equalize: bool = False

    def is_identity(self) -> bool:
        return (
            self.brightness == 1.0
            and self.contrast == 1.0
            and self.saturation == 1.0
            and self.sharpness == 1.0
            and self.gamma == 1.0
            and self.temperature == 0.0
            and self.tint == 0.0
            and self.vignette == 0.0
            and self.blur == 0.0
            and self.denoise == 0.0
            and self.unsharp_amount == 0.0
            and not self.grayscale
            and not self.sepia
            and not self.invert
            and not self.auto_contrast
            and not self.equalize
        )


@dataclass
class ExportSettings:
    """Everything about how the rendered result hits disk."""

    format: str = "PNG"
    jpeg_quality: int = 92
    webp_quality: int = 90
    webp_lossless: bool = False
    png_compression: int = 6      # 0..9
    keep_metadata: bool = True
    strip_gps: bool = False
    background: str = "#000000"   # used by PAD fit and by flattening alpha
    suffix: str = "_upscaled"
    overwrite_policy: str = "suffix"


@dataclass
class EditSettings:
    """Full description of one image edit."""

    # geometry
    size_mode: SizeMode = SizeMode.SCALE
    scale: float = 2.0
    target_width: int = 1920
    target_height: int = 1080
    long_edge: int = 2560
    percent: float = 200.0
    fit_mode: FitMode = FitMode.COVER
    lock_aspect: bool = True
    crop: CropRect = field(default_factory=CropRect)
    rotation: Rotation = Rotation.NONE
    flip_h: bool = False
    flip_v: bool = False

    # upscaling
    backend: str = "realesrgan"     # realesrgan | classic
    model: str = "realesrgan-x4plus"
    resample: str = "lanczos"       # classic resampler / final down-step
    denoise_level: int = -1         # animevideov3 only, -1 = n/a
    face_enhance: bool = False

    # look
    adjustments: Adjustments = field(default_factory=Adjustments)

    # output
    export: ExportSettings = field(default_factory=ExportSettings)

    def copy(self) -> EditSettings:
        return EditSettings.from_dict(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["size_mode"] = self.size_mode.value
        data["fit_mode"] = self.fit_mode.value
        data["rotation"] = int(self.rotation)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditSettings:
        data = dict(data)
        adjustments = Adjustments(**data.pop("adjustments", {}) or {})
        export = ExportSettings(**data.pop("export", {}) or {})
        crop = CropRect(**data.pop("crop", {}) or {})
        data["size_mode"] = SizeMode(data.get("size_mode", SizeMode.SCALE.value))
        data["fit_mode"] = FitMode(data.get("fit_mode", FitMode.COVER.value))
        data["rotation"] = Rotation(int(data.get("rotation", 0)))
        known = set(cls.__dataclass_fields__) - {"adjustments", "export", "crop"}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(adjustments=adjustments, export=export, crop=crop, **kwargs)

    def with_(self, **changes: Any) -> EditSettings:
        return replace(self, **changes)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """One queued file plus its per-file result state."""

    source: Path
    settings: EditSettings
    output: Path | None = None
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    message: str = ""
    source_size: tuple[int, int] | None = None
    result_size: tuple[int, int] | None = None
    elapsed: float = 0.0

    @property
    def name(self) -> str:
        return self.source.name
