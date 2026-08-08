"""Shared fixtures. The core is headless, so no Qt is imported here."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """A small RGB PNG with hard edges, so resampling artefacts are visible."""
    image = Image.new("RGB", (120, 80), (30, 40, 70))
    draw = ImageDraw.Draw(image)
    draw.ellipse([20, 15, 70, 65], fill=(240, 190, 60))
    draw.rectangle([80, 20, 110, 60], fill=(60, 200, 140))
    path = tmp_path / "sample.png"
    image.save(path)
    return path


@pytest.fixture
def alpha_image(tmp_path: Path) -> Path:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([8, 8, 56, 56], fill=(255, 90, 120, 255))
    path = tmp_path / "alpha.png"
    image.save(path)
    return path
