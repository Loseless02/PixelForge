"""Named resolution and look presets exposed in the UI."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Adjustments


@dataclass(frozen=True)
class ResolutionPreset:
    key: str
    label: str
    width: int
    height: int
    note: str = ""

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1_000_000


RESOLUTION_PRESETS: tuple[ResolutionPreset, ...] = (
    ResolutionPreset("hd", "HD", 1280, 720, "720p"),
    ResolutionPreset("fhd", "Full HD", 1920, 1080, "1080p"),
    ResolutionPreset("qhd", "2K / QHD", 2560, 1440, "1440p"),
    ResolutionPreset("uhd", "4K / UHD", 3840, 2160, "2160p"),
    ResolutionPreset("dci4k", "DCI 4K", 4096, 2160, "cinema"),
    ResolutionPreset("uhd5k", "5K", 5120, 2880, ""),
    ResolutionPreset("uhd8k", "8K", 7680, 4320, "4320p"),
    ResolutionPreset("a4_300", "A4 @ 300 dpi", 2480, 3508, "print"),
    ResolutionPreset("a3_300", "A3 @ 300 dpi", 3508, 4961, "print"),
    ResolutionPreset("ig_square", "Instagram square", 1080, 1080, "1:1"),
    ResolutionPreset("ig_portrait", "Instagram portrait", 1080, 1350, "4:5"),
    ResolutionPreset("story", "Story / Reel", 1080, 1920, "9:16"),
    ResolutionPreset("yt_thumb", "YouTube thumbnail", 1280, 720, "16:9"),
    ResolutionPreset("wallpaper", "Desktop wallpaper", 2560, 1600, "16:10"),
)

PRESETS_BY_KEY = {p.key: p for p in RESOLUTION_PRESETS}


ASPECT_RATIOS: tuple[tuple[str, float | None], ...] = (
    ("Free", None),
    ("Original", 0.0),  # 0.0 is a sentinel resolved against the source image
    ("1:1", 1.0),
    ("4:3", 4 / 3),
    ("3:2", 3 / 2),
    ("16:9", 16 / 9),
    ("16:10", 16 / 10),
    ("21:9", 21 / 9),
    ("9:16", 9 / 16),
    ("4:5", 4 / 5),
    ("2:3", 2 / 3),
    ("3:4", 3 / 4),
)


@dataclass(frozen=True)
class QualityPreset:
    """How hard the upscaler is allowed to work."""

    key: str
    label: str
    oversample: float
    tta: bool
    max_chain: int
    description: str


QUALITY_PRESETS: tuple[QualityPreset, ...] = (
    QualityPreset(
        "fast", "Fast", 1.0, False, 1,
        "One AI pass, then resample. Quickest, lowest video memory.",
    ),
    QualityPreset(
        "balanced", "Balanced", 1.0, False, 2,
        "Smallest AI chain that covers the target. Good default.",
    ),
    QualityPreset(
        "maximum", "Maximum", 2.0, True, 3,
        "Renders 2x above the target and downsamples, with test-time "
        "augmentation. Roughly 10-30x slower, visibly cleaner edges.",
    ),
)

QUALITY_BY_KEY = {p.key: p for p in QUALITY_PRESETS}


@dataclass(frozen=True)
class LookPreset:
    key: str
    label: str
    adjustments: Adjustments


LOOK_PRESETS: tuple[LookPreset, ...] = (
    LookPreset("none", "Original", Adjustments()),
    LookPreset(
        "punch",
        "Punch",
        Adjustments(contrast=1.18, saturation=1.22, unsharp_amount=60.0),
    ),
    LookPreset(
        "soft",
        "Soft",
        Adjustments(contrast=0.92, saturation=0.95, blur=0.6, brightness=1.04),
    ),
    LookPreset(
        "warm",
        "Warm",
        Adjustments(temperature=28.0, saturation=1.08, brightness=1.03),
    ),
    LookPreset("cool", "Cool", Adjustments(temperature=-26.0, contrast=1.06)),
    LookPreset("mono", "Mono", Adjustments(grayscale=True, contrast=1.12)),
    LookPreset("sepia", "Sepia", Adjustments(sepia=True, contrast=1.05)),
    LookPreset(
        "cinema",
        "Cinematic",
        Adjustments(
            contrast=1.14, saturation=0.9, temperature=-10.0, vignette=28.0
        ),
    ),
    LookPreset(
        "restore",
        "Restore",
        Adjustments(auto_contrast=True, denoise=25.0, unsharp_amount=80.0, detail=30.0),
    ),
    LookPreset(
        "crisp",
        "Crisp",
        Adjustments(detail=55.0, clarity=25.0, contrast=1.05),
    ),
    LookPreset(
        "hdr", "HDR pop", Adjustments(equalize=True, saturation=1.15, contrast=1.05)
    ),
)

LOOKS_BY_KEY = {p.key: p for p in LOOK_PRESETS}
