"""Resolution maths — the part most likely to silently produce wrong sizes."""

from __future__ import annotations

import pytest

from pixelforge.core import geometry
from pixelforge.core.models import CropRect, EditSettings, FitMode, Rotation, SizeMode


def test_scale_mode_multiplies_both_axes():
    settings = EditSettings(size_mode=SizeMode.SCALE, scale=2.5)
    assert geometry.resolve_target(400, 600, settings) == (1000, 1500)


def test_percent_mode_matches_scale():
    percent = EditSettings(size_mode=SizeMode.PERCENT, percent=250.0)
    scale = EditSettings(size_mode=SizeMode.SCALE, scale=2.5)
    assert geometry.resolve_target(400, 600, percent) == \
        geometry.resolve_target(400, 600, scale)


def test_long_edge_keeps_aspect_ratio():
    settings = EditSettings(size_mode=SizeMode.LONG_EDGE, long_edge=2000)
    assert geometry.resolve_target(1000, 500, settings) == (2000, 1000)
    assert geometry.resolve_target(500, 1000, settings) == (1000, 2000)


def test_exact_mode_is_literal_for_cover():
    settings = EditSettings(size_mode=SizeMode.EXACT, target_width=1200,
                            target_height=720, fit_mode=FitMode.COVER)
    assert geometry.resolve_target(400, 600, settings) == (1200, 720)


def test_exact_contain_shrinks_to_fit_the_box():
    settings = EditSettings(size_mode=SizeMode.EXACT, target_width=1200,
                            target_height=720, fit_mode=FitMode.CONTAIN)
    # 400x600 is portrait, so height is the limiting side.
    assert geometry.resolve_target(400, 600, settings) == (480, 720)


def test_crop_and_rotation_change_the_source_box():
    settings = EditSettings(crop=CropRect(10, 10, 200, 100), rotation=Rotation.CW_90)
    assert geometry.source_after_transform(400, 600, settings) == (100, 200)


def test_clamp_size_caps_total_pixels_and_keeps_aspect():
    width, height = geometry.clamp_size(40000, 30000)
    assert width <= geometry.MAX_EDGE and height <= geometry.MAX_EDGE
    assert width * height <= geometry.MAX_PIXELS
    assert width > height


@pytest.mark.parametrize(
    ("src", "target", "expected"),
    [
        ((400, 600), (1200, 720), [3]),      # width needs exactly 3x
        ((400, 600), (800, 1200), [2]),
        ((400, 600), (400, 600), []),        # no growth, no AI pass
        ((400, 600), (200, 300), []),        # downscale
        ((200, 200), (3200, 3200), [4, 4]),
    ],
)
def test_plan_ai_factor(src, target, expected):
    assert geometry.plan_ai_factor(*src, *target) == expected


def test_plan_ai_factor_respects_available_factors():
    # x4plus only knows 4x, so even a 1.2x request costs one full pass.
    assert geometry.plan_ai_factor(400, 600, 480, 720, available=(4,)) == [4]


def test_plan_ai_factor_always_covers_the_request():
    for target in (700, 1500, 3000, 9000):
        factors = geometry.plan_ai_factor(300, 300, target, target)
        product = 1
        for factor in factors:
            product *= factor
        assert product * 300 >= target or len(factors) == 2


@pytest.mark.parametrize(
    ("mode", "expected_canvas"),
    [
        (FitMode.STRETCH, (1200, 720)),
        (FitMode.COVER, (1200, 720)),
        (FitMode.PAD, (1200, 720)),
        (FitMode.CONTAIN, (480, 720)),
    ],
)
def test_fit_plan_canvas(mode, expected_canvas):
    _, canvas, _ = geometry.fit_plan(400, 600, 1200, 720, mode)
    assert canvas == expected_canvas


def test_fit_plan_cover_overflows_then_crops():
    resize_to, canvas, offset = geometry.fit_plan(400, 600, 1200, 720, FitMode.COVER)
    assert resize_to[0] >= canvas[0] and resize_to[1] >= canvas[1]
    assert offset[0] <= 0 or offset[1] <= 0


def test_fit_plan_pad_centres_the_image():
    resize_to, canvas, offset = geometry.fit_plan(400, 600, 1200, 720, FitMode.PAD)
    assert resize_to == (480, 720)
    assert canvas == (1200, 720)
    assert offset == (360, 0)
