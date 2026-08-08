"""Strength controls: oversampling, pass chaining, TTA and detail recovery."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageFilter

from pixelforge.core import adjust, geometry, pipeline
from pixelforge.core.models import Adjustments, EditSettings, SizeMode
from pixelforge.core.presets import QUALITY_BY_KEY, QUALITY_PRESETS


def sharpness(image: Image.Image) -> float:
    """Variance of the Laplacian — the usual sharpness proxy."""
    lum = np.asarray(image.convert("L"), dtype=np.float64)
    laplacian = (
        -4 * lum
        + np.roll(lum, 1, 0) + np.roll(lum, -1, 0)
        + np.roll(lum, 1, 1) + np.roll(lum, -1, 1)
    )
    return float(np.var(laplacian[2:-2, 2:-2]))


# ------------------------------------------------------------------ planning
def test_oversample_forces_a_bigger_chain():
    plain = geometry.plan_ai_factor(200, 200, 400, 400, max_chain=3)
    over = geometry.plan_ai_factor(200, 200, 400, 400, max_chain=3, oversample=2.0)
    assert np.prod(over) > np.prod(plain)


def test_oversample_below_one_is_ignored():
    assert geometry.plan_ai_factor(200, 200, 800, 800, oversample=0.1) == \
        geometry.plan_ai_factor(200, 200, 800, 800)


def test_max_chain_caps_the_number_of_passes():
    factors = geometry.plan_ai_factor(100, 100, 6400, 6400, max_chain=1)
    assert len(factors) == 1


def test_plan_pixels_reports_the_peak():
    assert geometry.plan_pixels(100, 200, [2, 4]) == (100 * 8) * (200 * 8)


def test_plan_factors_backs_off_when_oversampling_blows_the_memory_guard():
    settings = EditSettings(size_mode=SizeMode.SCALE, scale=4.0, oversample=3.0,
                            max_chain=3, model="realesr-animevideov3")
    factors = pipeline.plan_factors(4000, 3000, 16000, 12000, settings)
    assert geometry.plan_pixels(4000, 3000, factors) <= geometry.MAX_PIXELS


def test_classic_backend_plans_no_ai_passes():
    settings = EditSettings(backend="classic", oversample=2.0)
    assert pipeline.plan_factors(100, 100, 800, 800, settings) == []


# ------------------------------------------------------------------- presets
def test_quality_presets_escalate():
    fast, balanced, maximum = QUALITY_PRESETS
    assert fast.max_chain < balanced.max_chain < maximum.max_chain
    assert maximum.oversample > balanced.oversample
    assert maximum.tta and not balanced.tta


def test_quality_presets_are_addressable_by_key():
    assert set(QUALITY_BY_KEY) == {"fast", "balanced", "maximum"}


def test_tta_shows_up_in_the_plan_summary():
    settings = EditSettings(tta=True, size_mode=SizeMode.SCALE, scale=4.0)
    assert "TTA" in pipeline.plan_summary(200, 200, settings)


# -------------------------------------------------------------------- detail
def test_detail_is_part_of_the_identity_check():
    assert Adjustments().is_identity()
    assert not Adjustments(detail=10.0).is_identity()
    assert not Adjustments(clarity=10.0).is_identity()


def test_detail_increases_sharpness(sample_image):
    soft = Image.open(sample_image).convert("RGB").filter(
        ImageFilter.GaussianBlur(1.4)
    )
    sharpened = adjust.apply(soft, Adjustments(detail=70.0))
    assert sharpness(sharpened) > sharpness(soft) * 1.5


def test_detail_scales_with_strength(sample_image):
    soft = Image.open(sample_image).convert("RGB").filter(
        ImageFilter.GaussianBlur(1.4)
    )
    low = adjust.apply(soft, Adjustments(detail=20.0))
    high = adjust.apply(soft, Adjustments(detail=90.0))
    assert sharpness(high) > sharpness(low)


def test_clarity_raises_local_contrast_without_clipping():
    # Midtone blocks: clarity works on the band the mask lets through.
    array = np.full((160, 160, 3), 110, dtype=np.uint8)
    array[:, 80:] = 165
    array[80:, :] = 130
    image = Image.fromarray(array).filter(ImageFilter.GaussianBlur(4))

    result = adjust.apply(image, Adjustments(clarity=90.0))
    data = np.asarray(result, dtype=np.float64)
    assert data.std() > np.asarray(image, dtype=np.float64).std()
    assert data.max() <= 255 and data.min() >= 0


def test_clarity_leaves_flat_extremes_alone():
    white = Image.new("RGB", (64, 64), (255, 255, 255))
    result = adjust.apply(white, Adjustments(clarity=100.0))
    assert np.asarray(result).min() >= 250


@pytest.mark.parametrize("field", ["detail", "clarity"])
def test_strength_fields_survive_serialisation(field):
    settings = EditSettings()
    setattr(settings.adjustments, field, 42.0)
    settings.oversample = 2.0
    settings.tta = True
    settings.max_chain = 3
    settings.quality = "maximum"

    restored = EditSettings.from_dict(settings.to_dict())

    assert getattr(restored.adjustments, field) == 42.0
    assert restored.oversample == 2.0
    assert restored.tta is True
    assert restored.max_chain == 3
    assert restored.quality == "maximum"
