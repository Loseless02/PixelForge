"""Application paths, persisted settings and runtime constants."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "PixelForge"
ORG_NAME = "PixelForge"


def _frozen() -> bool:
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    """Directory that holds the bundled ``vendor/`` tree."""
    if _frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def vendor_dir() -> Path:
    return project_root() / "vendor"


def user_data_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    path = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = user_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pictures_dir() -> Path:
    """The user's Pictures folder, honouring Windows folder redirection."""
    if sys.platform == "win32":
        try:
            import winreg

            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "My Pictures")
            path = Path(os.path.expandvars(value))
            if path.is_dir():
                return path
        except OSError:
            pass  # redirected folder unreadable; fall back to the home guess
    candidate = Path.home() / "Pictures"
    return candidate if candidate.is_dir() else Path.home()


def default_output_dir() -> Path:
    """Where upscaled files land unless the user picks somewhere else."""
    return pictures_dir() / "upscaled"


SETTINGS_FILE = user_data_dir() / "settings.json"


@dataclass
class AppSettings:
    """User preferences that survive across runs."""

    theme: str = "dark"
    accent: str = "#6D5EF8"
    last_input_dir: str = ""
    output_dir: str = ""            # empty = default_output_dir()
    save_next_to_source: bool = False
    default_model: str = "auto"
    default_format: str = "PNG"
    jpeg_quality: int = 92
    webp_quality: int = 90
    keep_metadata: bool = True
    tile_size: int = 0  # 0 = auto
    use_gpu: bool = True
    gpu_id: int = 0
    overwrite_policy: str = "suffix"  # suffix | overwrite | skip
    output_suffix: str = "_upscaled"
    recent_files: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> AppSettings:
        if SETTINGS_FILE.exists():
            try:
                raw: dict[str, Any] = json.loads(SETTINGS_FILE.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                return cls()
            known = set(cls.__dataclass_fields__)
            return cls(**{k: v for k, v in raw.items() if k in known})
        return cls()

    def save(self) -> None:
        payload = {k: getattr(self, k) for k in self.__dataclass_fields__}
        with contextlib.suppress(OSError):
            SETTINGS_FILE.write_text(json.dumps(payload, indent=2), "utf-8")

    def push_recent(self, path: str, limit: int = 12) -> None:
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        del self.recent_files[limit:]
