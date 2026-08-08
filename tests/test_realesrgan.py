"""Real-ESRGAN backend. Skipped when the runtime has not been fetched."""

from __future__ import annotations

import pytest
from PIL import Image

from pixelforge.core import pipeline
from pixelforge.core.backends import BACKENDS
from pixelforge.core.models import EditSettings, FitMode, SizeMode

backend = BACKENDS["realesrgan"]

pytestmark = pytest.mark.skipif(
    not backend.is_available(),
    reason="Real-ESRGAN runtime not installed — run scripts/fetch_models.py",
)


def test_models_are_discovered():
    keys = {info.key for info in backend.models()}
    assert "realesrgan-x4plus" in keys


def test_supported_factors_are_declared():
    assert backend.supported_factors("realesrgan-x4plus") == (4,)
    assert backend.supported_factors("realesr-animevideov3") == (2, 3, 4)


@pytest.mark.slow
def test_upscale_multiplies_the_size():
    source = Image.new("RGB", (32, 24), (40, 90, 160))
    result = backend.upscale(source, 2, model="realesr-animevideov3")
    assert result.size == (64, 48)


@pytest.mark.slow
def test_render_reaches_an_arbitrary_target(sample_image):
    settings = EditSettings(
        size_mode=SizeMode.EXACT,
        target_width=300,
        target_height=180,
        fit_mode=FitMode.COVER,
        backend="realesrgan",
        model="realesr-animevideov3",
    )
    result = pipeline.render(sample_image, settings)
    assert result.size == (300, 180)


@pytest.mark.slow
def test_alpha_is_preserved_by_the_ai_pass(alpha_image):
    settings = EditSettings(
        size_mode=SizeMode.SCALE,
        scale=2.0,
        backend="realesrgan",
        model="realesr-animevideov3",
    )
    result = pipeline.render(alpha_image, settings)
    assert result.mode == "RGBA"
    assert result.size == (128, 128)
