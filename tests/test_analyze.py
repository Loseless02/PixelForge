"""Model auto-selection."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from pixelforge.core import analyze, pipeline
from pixelforge.core.models import EditSettings


def photo_like(width: int = 320, height: int = 240) -> Image.Image:
    """Continuous tone with texture at several scales — no flat regions."""
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    base = np.stack([
        120 + 60 * np.sin(xx / 47.0) + 30 * np.cos(yy / 31.0),
        110 + 50 * np.sin((xx + yy) / 60.0),
        130 + 55 * np.cos(yy / 40.0),
    ], axis=-1)
    base += rng.normal(0, 14, base.shape)
    for cell, amp in ((16, 30.0), (6, 18.0)):
        small = rng.random((height // cell + 2, width // cell + 2, 3)).astype(np.float32)
        band = np.asarray(
            Image.fromarray((small * 255).astype(np.uint8)).resize(
                (width, height), Image.Resampling.BICUBIC
            ), dtype=np.float32,
        )
        base += (band - 127.5) / 127.5 * amp
    image = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")
    return image.filter(ImageFilter.GaussianBlur(0.4))


def illustration_like(width: int = 320, height: int = 240) -> Image.Image:
    """Flat fills and hard outlines, the way cel-shaded art looks."""
    image = Image.new("RGB", (width, height), (238, 232, 214))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, height * 0.62, width, height], fill=(96, 168, 108))
    draw.ellipse([40, 40, 150, 150], fill=(232, 84, 96), outline=(24, 24, 32), width=4)
    draw.rectangle([180, 60, 280, 170], fill=(72, 122, 216), outline=(24, 24, 32),
                   width=4)
    draw.polygon([(60, 200), (120, 150), (180, 200)], fill=(250, 208, 72),
                 outline=(24, 24, 32))
    return image


def test_photo_is_routed_to_the_photo_model():
    result = analyze.profile(photo_like())
    assert result.kind == "photo"
    assert result.model == analyze.PHOTO_MODEL


def test_illustration_is_routed_to_the_anime_model():
    result = analyze.profile(illustration_like())
    assert result.kind == "illustration"
    assert result.model == analyze.ANIME_MODEL


def test_illustration_has_more_flat_area_than_a_photo():
    assert analyze.profile(illustration_like()).flat_ratio > \
        analyze.profile(photo_like()).flat_ratio


def test_photo_uses_far_more_distinct_colours():
    assert analyze.profile(photo_like()).colour_ratio > \
        analyze.profile(illustration_like()).colour_ratio


def test_confidence_is_a_fraction():
    for image in (photo_like(), illustration_like()):
        assert 0.0 <= analyze.profile(image).confidence <= 1.0


def test_tiny_images_degrade_gracefully():
    result = analyze.profile(Image.new("RGB", (4, 4), (10, 20, 30)))
    assert result.kind == "unknown"
    assert result.model == analyze.PHOTO_MODEL


def test_profile_always_names_a_real_model():
    from pixelforge.core.backends import BACKENDS

    keys = {info.key for info in BACKENDS["realesrgan"].models()}
    if not keys:
        pytest.skip("Real-ESRGAN runtime not installed")
    for image in (photo_like(), illustration_like()):
        assert analyze.profile(image).model in keys


def test_every_profile_carries_a_reason():
    assert len(analyze.profile(photo_like()).reason) > 20


# ------------------------------------------------------------------ pipeline
def test_resolve_model_replaces_auto():
    settings = EditSettings(model=pipeline.AUTO_MODEL)
    resolved = pipeline.resolve_model(illustration_like(), settings)
    assert resolved.model == analyze.ANIME_MODEL
    assert settings.model == pipeline.AUTO_MODEL  # original untouched


def test_resolve_model_leaves_an_explicit_choice_alone():
    settings = EditSettings(model="realesrgan-x4plus-anime")
    assert pipeline.resolve_model(photo_like(), settings) is settings


def test_resolve_model_skips_the_classic_backend():
    settings = EditSettings(model=pipeline.AUTO_MODEL, backend="classic")
    assert pipeline.resolve_model(illustration_like(), settings) is settings


def test_auto_model_renders_without_the_ai_backend(sample_image, tmp_path):
    settings = EditSettings(backend="classic", model=pipeline.AUTO_MODEL)
    settings.scale = 2.0
    result = pipeline.render(sample_image, settings)
    assert result.size == (240, 160)
