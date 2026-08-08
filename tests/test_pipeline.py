"""End-to-end pipeline behaviour, using the classic backend so tests stay fast."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pixelforge.core import adjust, imageio, pipeline
from pixelforge.core.models import (
    Adjustments,
    CropRect,
    EditSettings,
    FitMode,
    Job,
    JobStatus,
    Rotation,
    SizeMode,
)


def classic(**kwargs) -> EditSettings:
    settings = EditSettings(backend="classic", **kwargs)
    return settings


def test_render_hits_the_exact_target(sample_image: Path):
    settings = classic(size_mode=SizeMode.EXACT, target_width=640, target_height=360,
                       fit_mode=FitMode.COVER)
    result = pipeline.render(sample_image, settings)
    assert result.size == (640, 360)


@pytest.mark.parametrize("mode", list(FitMode))
def test_every_fit_mode_produces_a_sane_size(sample_image: Path, mode: FitMode):
    settings = classic(size_mode=SizeMode.EXACT, target_width=500, target_height=500,
                       fit_mode=mode)
    result = pipeline.render(sample_image, settings)
    if mode is FitMode.CONTAIN:
        assert max(result.size) == 500
    else:
        assert result.size == (500, 500)


def test_crop_applies_before_scaling(sample_image: Path):
    settings = classic(size_mode=SizeMode.SCALE, scale=2.0,
                       crop=CropRect(10, 10, 40, 20))
    result = pipeline.render(sample_image, settings)
    assert result.size == (80, 40)


def test_rotation_swaps_the_axes(sample_image: Path):
    settings = classic(size_mode=SizeMode.SCALE, scale=1.0, rotation=Rotation.CW_90)
    result = pipeline.render(sample_image, settings)
    assert result.size == (80, 120)


def test_alpha_survives_the_pipeline(alpha_image: Path):
    settings = classic(size_mode=SizeMode.SCALE, scale=2.0)
    result = pipeline.render(alpha_image, settings)
    assert result.mode == "RGBA"
    assert result.getpixel((0, 0))[3] == 0


def test_preview_is_smaller_but_same_aspect(sample_image: Path):
    settings = classic(size_mode=SizeMode.EXACT, target_width=4000,
                       target_height=3000, fit_mode=FitMode.COVER)
    loaded = imageio.load(sample_image)
    preview = pipeline.render_preview(loaded, settings, max_edge=400)
    assert max(preview.size) <= 400
    assert abs(preview.width / preview.height - 4 / 3) < 0.02


def test_plan_summary_mentions_both_sizes(sample_image: Path):
    settings = classic(size_mode=SizeMode.SCALE, scale=3.0)
    text = pipeline.plan_summary(120, 80, settings)
    assert "120x80" in text
    assert "360x240" in text


def test_run_job_writes_the_file(sample_image: Path, tmp_path: Path):
    settings = classic(size_mode=SizeMode.SCALE, scale=2.0)
    settings.export.format = "PNG"
    job = Job(source=sample_image, settings=settings)
    out_dir = tmp_path / "out"

    result = pipeline.run_job(job, out_dir)

    assert job.status is JobStatus.DONE
    assert result.output_path is not None and result.output_path.exists()
    assert result.output_path.parent == out_dir
    with Image.open(result.output_path) as written:
        assert written.size == (240, 160)


def test_run_job_suffix_policy_never_overwrites(sample_image: Path, tmp_path: Path):
    settings = classic(size_mode=SizeMode.SCALE, scale=1.0)
    settings.export.overwrite_policy = "suffix"
    out_dir = tmp_path / "out"

    first = pipeline.run_job(Job(source=sample_image, settings=settings), out_dir)
    second = pipeline.run_job(Job(source=sample_image, settings=settings), out_dir)

    assert first.output_path != second.output_path
    assert first.output_path.exists() and second.output_path.exists()


def test_run_job_skip_policy_leaves_the_original(sample_image: Path, tmp_path: Path):
    settings = classic(size_mode=SizeMode.SCALE, scale=1.0)
    settings.export.overwrite_policy = "skip"
    out_dir = tmp_path / "out"

    pipeline.run_job(Job(source=sample_image, settings=settings), out_dir)
    second = pipeline.run_job(Job(source=sample_image, settings=settings), out_dir)

    assert second.skipped is True


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "TIFF", "BMP"])
def test_export_formats_round_trip(sample_image: Path, tmp_path: Path, fmt: str):
    settings = classic(size_mode=SizeMode.SCALE, scale=1.0)
    settings.export.format = fmt
    job = Job(source=sample_image, settings=settings)

    result = pipeline.run_job(job, tmp_path / fmt.lower())

    assert result.output_path.exists()
    with Image.open(result.output_path) as written:
        assert written.size == (120, 80)


def test_jpeg_flattens_alpha_without_crashing(alpha_image: Path, tmp_path: Path):
    settings = classic(size_mode=SizeMode.SCALE, scale=1.0)
    settings.export.format = "JPEG"
    settings.export.background = "#ffffff"
    result = pipeline.run_job(Job(source=alpha_image, settings=settings), tmp_path)
    with Image.open(result.output_path) as written:
        assert written.mode == "RGB"
        assert written.getpixel((0, 0)) == (255, 255, 255)


def test_adjustments_identity_short_circuits(sample_image: Path):
    image = Image.open(sample_image).convert("RGB")
    assert adjust.apply(image, Adjustments()) is image


def test_adjustments_change_pixels(sample_image: Path):
    image = Image.open(sample_image).convert("RGB")
    brighter = adjust.apply(image, Adjustments(brightness=1.6))
    assert brighter.getpixel((0, 0)) != image.getpixel((0, 0))


def test_grayscale_produces_equal_channels(sample_image: Path):
    image = Image.open(sample_image).convert("RGB")
    mono = adjust.apply(image, Adjustments(grayscale=True))
    red, green, blue = mono.getpixel((30, 30))
    assert red == green == blue


def test_vignette_darkens_corners(sample_image: Path):
    image = Image.new("RGB", (100, 100), (200, 200, 200))
    result = adjust.apply(image, Adjustments(vignette=90.0))
    assert sum(result.getpixel((0, 0))) < sum(result.getpixel((50, 50)))
