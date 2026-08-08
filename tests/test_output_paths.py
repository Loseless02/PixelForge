"""Where results land on disk."""

from __future__ import annotations

from pathlib import Path

from pixelforge import config
from pixelforge.core import imageio, pipeline
from pixelforge.core.models import EditSettings, Job, SizeMode


def test_default_output_dir_is_under_pictures():
    target = config.default_output_dir()
    assert target.name == "upscaled"
    assert target.parent == config.pictures_dir()


def test_pictures_dir_exists_or_falls_back_home():
    pictures = config.pictures_dir()
    assert pictures.is_dir()


def test_output_dir_is_created_on_demand(sample_image: Path, tmp_path: Path):
    out_dir = tmp_path / "Pictures" / "upscaled"
    assert not out_dir.exists()

    settings = EditSettings(backend="classic", size_mode=SizeMode.SCALE, scale=1.0)
    result = pipeline.run_job(Job(source=sample_image, settings=settings), out_dir)

    assert out_dir.is_dir()
    assert result.output_path.parent == out_dir


def test_none_output_dir_writes_beside_the_source(sample_image: Path):
    settings = EditSettings(backend="classic", size_mode=SizeMode.SCALE, scale=1.0)
    result = pipeline.run_job(Job(source=sample_image, settings=settings), None)
    assert result.output_path.parent == sample_image.parent


def test_resolve_output_path_creates_missing_parents(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c"
    out = imageio.resolve_output_path(Path("x.png"), nested, ".png", "_up", "suffix")
    assert nested.is_dir()
    assert out.name == "x_up.png"


def test_app_settings_round_trip_output_fields(tmp_path: Path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", settings_file)

    settings = config.AppSettings()
    settings.output_dir = str(tmp_path / "elsewhere")
    settings.save_next_to_source = True
    settings.save()

    restored = config.AppSettings.load()
    assert restored.output_dir == str(tmp_path / "elsewhere")
    assert restored.save_next_to_source is True
