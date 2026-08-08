"""Serialisation, presets and backend registry."""

from __future__ import annotations

from pixelforge.core import imageio
from pixelforge.core.backends import BACKENDS, available_backends, get_backend
from pixelforge.core.models import Adjustments, CropRect, EditSettings, FitMode, SizeMode
from pixelforge.core.presets import LOOK_PRESETS, PRESETS_BY_KEY, RESOLUTION_PRESETS


def test_settings_round_trip_through_dict():
    original = EditSettings(
        size_mode=SizeMode.EXACT,
        target_width=2560,
        target_height=1440,
        fit_mode=FitMode.PAD,
        crop=CropRect(4, 8, 100, 200),
        adjustments=Adjustments(contrast=1.3, grayscale=True),
    )
    original.export.format = "WEBP"

    restored = EditSettings.from_dict(original.to_dict())

    assert restored.size_mode is SizeMode.EXACT
    assert restored.fit_mode is FitMode.PAD
    assert restored.crop == CropRect(4, 8, 100, 200)
    assert restored.adjustments.contrast == 1.3
    assert restored.adjustments.grayscale is True
    assert restored.export.format == "WEBP"


def test_copy_is_deep():
    original = EditSettings()
    clone = original.copy()
    clone.adjustments.contrast = 2.0
    clone.export.format = "JPEG"
    assert original.adjustments.contrast == 1.0
    assert original.export.format == "PNG"


def test_crop_clamps_inside_the_image():
    crop = CropRect(-50, -50, 5000, 5000).clamped(100, 80)
    assert crop.x == 0 and crop.y == 0
    assert crop.width == 100 and crop.height == 80


def test_empty_crop_is_detected():
    assert CropRect().is_empty
    assert not CropRect(0, 0, 1, 1).is_empty


def test_classic_backend_is_always_available():
    keys = {backend.key for backend in available_backends()}
    assert "classic" in keys


def test_unknown_backend_falls_back_to_classic():
    assert get_backend("does-not-exist").key == "classic"


def test_classic_backend_upscales_by_the_factor():
    from PIL import Image

    backend = BACKENDS["classic"]
    result = backend.upscale(Image.new("RGB", (10, 20)), 3)
    assert result.size == (30, 60)


def test_resolution_presets_are_unique_and_sane():
    keys = [preset.key for preset in RESOLUTION_PRESETS]
    assert len(keys) == len(set(keys))
    assert PRESETS_BY_KEY["uhd"].width == 3840
    for preset in RESOLUTION_PRESETS:
        assert preset.width > 0 and preset.height > 0


def test_look_presets_include_a_neutral_entry():
    neutral = next(p for p in LOOK_PRESETS if p.key == "none")
    assert neutral.adjustments.is_identity()


def test_output_formats_report_availability():
    specs = imageio.output_formats()
    keys = {spec.key for spec in specs}
    assert {"PNG", "JPEG", "WEBP"} <= keys
    assert all(spec.extension.startswith(".") for spec in specs)


def test_is_supported_matches_read_extensions():
    assert imageio.is_supported("photo.PNG")
    assert imageio.is_supported("photo.jpeg")
    assert not imageio.is_supported("notes.txt")


def test_resolve_output_path_adds_the_suffix(tmp_path):
    from pathlib import Path

    source = Path("holiday.jpg")
    out = imageio.resolve_output_path(source, tmp_path, ".png", "_2x", "suffix")
    assert out.name == "holiday_2x.png"
    assert out.parent == tmp_path
