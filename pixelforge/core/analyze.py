"""Guess what kind of image this is, and therefore which model suits it.

Real-ESRGAN's photo and anime weights fail in opposite directions: the photo
model leaves illustration line art mushy, and the anime model turns skin and
foliage into plastic. Picking between them is the single highest-impact choice
a user makes, and it is not obvious from a thumbnail — so measure it.

Everything here runs on a 256 px proxy and takes a few milliseconds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

PROXY_EDGE = 256

PHOTO_MODEL = "realesrgan-x4plus"
ANIME_MODEL = "realesrgan-x4plus-anime"


@dataclass(frozen=True)
class ImageProfile:
    """What the measurements say, and what to do about it."""

    kind: str            # photo | illustration | unknown
    model: str
    confidence: float    # 0..1
    reason: str
    flat_ratio: float
    colour_ratio: float
    edge_density: float
    saturation: float

    @property
    def label(self) -> str:
        return {
            "photo": "Looks like a photo",
            "illustration": "Looks like art or line work",
        }.get(self.kind, "Not sure what this is")


def _proxy(image: Image.Image) -> np.ndarray:
    small = image.convert("RGB")
    if max(small.size) > PROXY_EDGE:
        small = small.copy()
        small.thumbnail((PROXY_EDGE, PROXY_EDGE), Image.Resampling.BILINEAR)
    return np.asarray(small, dtype=np.float32)


def profile(image: Image.Image) -> ImageProfile:
    """Measure an image and recommend a model."""
    data = _proxy(image)
    if data.size == 0 or min(data.shape[:2]) < 8:
        return ImageProfile("unknown", PHOTO_MODEL, 0.0,
                            "Too small to judge — defaulting to the photo model.",
                            0.0, 0.0, 0.0, 0.0)

    luma = data @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

    # Flat areas: illustrations are full of them, photographs almost never are.
    gx = np.abs(np.diff(luma, axis=1))[:-1, :]
    gy = np.abs(np.diff(luma, axis=0))[:, :-1]
    gradient = gx + gy
    flat_ratio = float(np.mean(gradient < 1.5))

    # Distinct colours per pixel, quantised — flat art reuses very few.
    quantised = (data / 12.0).astype(np.int16)
    packed = (quantised[..., 0].astype(np.int32) << 16
              | quantised[..., 1].astype(np.int32) << 8
              | quantised[..., 2].astype(np.int32))
    colour_ratio = float(len(np.unique(packed)) / packed.size)

    # Hard edges: line art has a high share of very strong gradients.
    edge_density = float(np.mean(gradient > 34.0))

    top = data.max(axis=-1)
    bottom = data.min(axis=-1)
    saturation = float(np.mean((top - bottom) / np.maximum(top, 1.0)))

    # Each signal votes on "this is drawn rather than photographed".
    # Colour variety runs the other way, so its thresholds are reversed.
    votes = (
        _score(flat_ratio, 0.30, 0.62),
        _score(colour_ratio, 0.16, 0.03),
        _score(edge_density, 0.012, 0.055),
    )
    drawn = float(np.mean(votes))

    if drawn >= 0.62:
        kind, model = "illustration", ANIME_MODEL
        reason = (
            "Large flat colour areas and hard outlines. The anime model keeps "
            "lines crisp; the photo model would leave them soft."
        )
    elif drawn <= 0.38:
        kind, model = "photo", PHOTO_MODEL
        reason = (
            "Continuous tone and fine texture throughout. The photo model "
            "handles this and cleans up JPEG noise on the way."
        )
    else:
        kind, model = "unknown", PHOTO_MODEL
        reason = (
            "Mixed signals — could be a stylised photo or a painted image. "
            "The photo model is the safer default; try the anime model and "
            "compare if the result looks soft."
        )

    confidence = float(min(1.0, abs(drawn - 0.5) * 2.4))
    return ImageProfile(kind, model, confidence, reason, flat_ratio, colour_ratio,
                        edge_density, saturation)


def _score(value: float, low: float, high: float) -> float:
    """Map ``value`` onto 0..1 between two thresholds.

    ``high`` may be below ``low``, which flips the direction — that is how a
    signal that falls as the image gets more drawn still votes upward.
    """
    if high == low:
        return 0.5
    return float(min(1.0, max(0.0, (value - low) / (high - low))))


def recommend(image: Image.Image) -> str:
    """Just the model key."""
    return profile(image).model
