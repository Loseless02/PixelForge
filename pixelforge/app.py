"""Application bootstrap."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from . import __app_name__, __version__
from .config import ORG_NAME, AppSettings
from .gui import icons, theme
from .gui.main_window import MainWindow


def _configure_platform() -> None:
    """Windows taskbar grouping needs an explicit AppUserModelID."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"{ORG_NAME}.{__app_name__}.{__version__}"
            )
        except Exception:
            pass
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


def build_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    _configure_platform()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    app.setWindowIcon(icons.app_icon())
    app.setFont(theme.ui_font())

    settings = AppSettings.load()
    window = MainWindow(settings)
    return app, window


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    files = [a for a in argv[1:] if not a.startswith("-")]

    app, window = build_app(argv)
    window.show()
    if files:
        window.add_paths(files)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
