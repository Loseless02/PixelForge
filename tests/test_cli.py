"""CLI argument wiring.

The parser is built at call time, so a duplicate flag only blows up when
someone actually runs the CLI. These tests build it every run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pixelforge import cli
from pixelforge.config import default_output_dir
from pixelforge.core.models import FitMode, SizeMode


def test_parser_builds_without_conflicting_flags():
    assert cli.build_parser() is not None


def test_strength_and_encoder_quality_are_separate_flags():
    args = cli.build_parser().parse_args(
        ["x.png", "--quality", "maximum", "-q", "70"]
    )
    assert args.quality == "maximum"
    assert args.image_quality == 70


def test_quality_preset_populates_the_strength_fields():
    args = cli.build_parser().parse_args(["x.png", "--quality", "maximum"])
    settings = cli.settings_from_args(args)
    assert settings.oversample == 2.0
    assert settings.tta is True
    assert settings.max_chain == 3


def test_explicit_strength_flags_mark_the_preset_custom():
    args = cli.build_parser().parse_args(["x.png", "--tta", "--oversample", "1.5"])
    settings = cli.settings_from_args(args)
    assert settings.quality == "custom"
    assert settings.tta is True
    assert settings.oversample == 1.5


def test_detail_and_clarity_reach_the_adjustments():
    args = cli.build_parser().parse_args(
        ["x.png", "--detail", "40", "--clarity", "15"]
    )
    settings = cli.settings_from_args(args)
    assert settings.adjustments.detail == 40.0
    assert settings.adjustments.clarity == 15.0


def test_size_flag_parses_into_exact_mode():
    args = cli.build_parser().parse_args(["x.png", "--size", "1200x720"])
    settings = cli.settings_from_args(args)
    assert settings.size_mode is SizeMode.EXACT
    assert (settings.target_width, settings.target_height) == (1200, 720)
    assert settings.fit_mode is FitMode.COVER


def test_help_advertises_the_default_output_folder():
    text = cli.build_parser().format_help()
    assert str(default_output_dir()) in text


def test_dry_run_writes_nothing(sample_image: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    exit_code = cli.main(
        [str(sample_image), "-o", str(out_dir), "--dry-run", "-b", "classic"]
    )
    assert exit_code == 0
    assert not any(out_dir.iterdir())


def test_real_run_writes_into_the_chosen_folder(sample_image: Path, tmp_path: Path):
    out_dir = tmp_path / "nested" / "upscaled"
    exit_code = cli.main(
        [str(sample_image), "-o", str(out_dir), "-b", "classic", "-s", "2"]
    )
    assert exit_code == 0
    written = list(out_dir.glob("*.png"))
    assert len(written) == 1


def test_next_to_source_bypasses_the_output_folder(sample_image: Path, tmp_path: Path):
    out_dir = tmp_path / "should-stay-empty"
    exit_code = cli.main(
        [str(sample_image), "-o", str(out_dir), "--next-to-source",
         "-b", "classic", "-s", "2"]
    )
    assert exit_code == 0
    assert not out_dir.exists()
    assert (sample_image.parent / "sample_upscaled.png").exists()


@pytest.mark.parametrize("flag", ["--scale", "--long-edge", "--oversample"])
def test_numeric_flags_accept_values(flag):
    args = cli.build_parser().parse_args(["x.png", flag, "2"])
    assert getattr(args, flag.lstrip("-").replace("-", "_")) == pytest.approx(2)
