#!/usr/bin/env python3
"""Launch PixelForge from a source checkout without installing it."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pixelforge.app import main

if __name__ == "__main__":
    raise SystemExit(main())
