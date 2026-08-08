"""Vector icons.

Icons are inline SVG strings with a ``{c}`` colour placeholder, rendered to
``QIcon`` on demand and cached per (name, colour, size). A handful are also
written to PNG files because Qt stylesheets can only reference images by URL.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..config import cache_dir

_S = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" \
stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{p}</svg>'

_PATHS: dict[str, str] = {
    "add": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "trash": '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m-8 0 1 12a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-12"/>',
    "play": '<path d="M7 4.5v15l13-7.5z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "minimize": '<path d="M5 12h14"/>',
    "maximize": '<rect x="5.5" y="5.5" width="13" height="13" rx="2"/>',
    "restore": '<path d="M8 8V6.5A1.5 1.5 0 0 1 9.5 5h8A1.5 1.5 0 0 1 19 6.5v8a1.5 1.5 0 0 1-1.5 1.5H16"/><rect x="5" y="8" width="11" height="11" rx="1.5"/>',
    "crop": '<path d="M6.5 2v15.5H22M2 6.5h15.5V22"/>',
    "rotate_cw": '<path d="M21 12a9 9 0 1 1-3.1-6.8M21 4v5h-5"/>',
    "rotate_ccw": '<path d="M3 12a9 9 0 1 0 3.1-6.8M3 4v5h5"/>',
    "flip_h": '<path d="M12 3v18M8 7 3 12l5 5zM16 7l5 5-5 5z"/>',
    "flip_v": '<path d="M3 12h18M7 8l5-5 5 5zM7 16l5 5 5-5z"/>',
    "zoom_in": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5M11 8.5v5M8.5 11h5"/>',
    "zoom_out": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5M8.5 11h5"/>',
    "fit": '<path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15"/>',
    "compare": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
    "eye": '<path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z"/><circle cx="12" cy="12" r="2.6"/>',
    "sparkle": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h10M18 18h2"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>',
    "export": '<path d="M12 3v12M8 7l4-4 4 4M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M4.5 17.5 9 13l3.2 3.2L15.5 13l4 4.2"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .32 1.77l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.6 1.6 0 0 0-1.77-.32 1.6 1.6 0 0 0-1 1.47V21a2 2 0 1 1-4 0v-.11a1.6 1.6 0 0 0-1.05-1.46 1.6 1.6 0 0 0-1.77.32l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.6 1.6 0 0 0 4.8 15a1.6 1.6 0 0 0-1.47-1H3a2 2 0 1 1 0-4h.11a1.6 1.6 0 0 0 1.46-1.05 1.6 1.6 0 0 0-.32-1.77l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.6 1.6 0 0 0 9 4.8a1.6 1.6 0 0 0 1-1.47V3a2 2 0 1 1 4 0v.11a1.6 1.6 0 0 0 1 1.46 1.6 1.6 0 0 0 1.77-.32l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.6 1.6 0 0 0 19.2 9v.05a1.6 1.6 0 0 0 1.47 1H21a2 2 0 1 1 0 4h-.11a1.6 1.6 0 0 0-1.49 1z"/>',
    "check": '<path d="M4.5 12.5 9.5 17.5 19.5 6.5"/>',
    "caret_down": '<path d="M6 9.5l6 6 6-6"/>',
    "caret_up": '<path d="M6 14.5l6-6 6 6"/>',
    "caret_right": '<path d="M9.5 6l6 6-6 6"/>',
    "reset": '<path d="M3.5 12a8.5 8.5 0 1 1 2.6 6.1M3.5 19v-5h5"/>',
    "save": '<path d="M5 5.5A1.5 1.5 0 0 1 6.5 4h9L20 8.5v10a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 5 18.5z"/><path d="M8.5 4v5h7M8.5 20v-5.5h7V20"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8"/>',
    "moon": '<path d="M20.5 14.2A8.7 8.7 0 0 1 9.8 3.5a8.7 8.7 0 1 0 10.7 10.7z"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M10 2v4M14 2v4M10 18v4M14 18v4M2 10h4M2 14h4M18 10h4M18 14h4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "warning": '<path d="M10.3 4.3 2.5 18a1.6 1.6 0 0 0 1.4 2.4h16.2A1.6 1.6 0 0 0 21.5 18L13.7 4.3a1.6 1.6 0 0 0-2.8 0z"/><path d="M12 9.5v4M12 17h.01"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.2 1.9"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    "swap": '<path d="M7 4v14M7 18l-3-3M7 18l3-3M17 20V6M17 6l-3 3M17 6l3 3"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 1 1 8 0v3"/>',
    "unlock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 7.5-2"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
}


def svg_source(name: str, color: str) -> str:
    return _S.format(c=color, p=_PATHS.get(name, _PATHS["info"]))


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_source(name, color).encode("utf-8")))
    px = QPixmap(QSize(int(size * dpr), int(size * dpr)))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # The painter works in logical units because the pixmap carries a device
    # pixel ratio, so the target rect is `size`, not `size * dpr`.
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return px


@lru_cache(maxsize=512)
def icon(name: str, color: str, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))


def write_stylesheet_assets(palette) -> dict[str, str]:
    """Materialise the few icons the stylesheet needs as PNG files.

    Qt stylesheets take image URLs, not inline SVG, so these get written once
    per theme into the user cache directory.
    """
    out: dict[str, str] = {}
    wanted = {
        "check": (palette.accent_text, 11),
        "caret_down": (palette.text_dim, 10),
        "caret_up": (palette.text_dim, 10),
    }
    for key, (color, size) in wanted.items():
        path = cache_dir() / f"{key}_{size}_{color.lstrip('#')}.png"
        if not path.exists():
            pixmap(key, color, size, dpr=1.0).save(str(path), "PNG")
        out[key] = path.as_posix()
    return out


def app_icon() -> QIcon:
    """Window / taskbar icon, drawn from the wordmark glyph."""
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer = QSvgRenderer(QByteArray(_APP_MARK.encode("utf-8")))
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(px)
    return result


_APP_MARK = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#8B7BFF"/>
      <stop offset="100%" stop-color="#4B3BD6"/>
    </linearGradient>
  </defs>
  <rect x="3" y="3" width="58" height="58" rx="15" fill="url(#g)"/>
  <path d="M20 42V22h9.5a6.8 6.8 0 0 1 0 13.6H26V42z" fill="#FFFFFF" opacity="0.96"/>
  <path d="M36 27h9M36 33h12M36 39h7" stroke="#FFFFFF" stroke-width="3"
        stroke-linecap="round" opacity="0.75"/>
</svg>
"""
