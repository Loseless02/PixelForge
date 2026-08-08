"""Colour tokens and the application stylesheet.

One dataclass holds every colour; the stylesheet is a format string over it.
Switching theme or accent means rebuilding the sheet and re-polishing widgets,
so no widget hard-codes a colour.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str            # window background
    surface: str       # cards / panels
    surface_alt: str   # inputs, hover rows
    surface_high: str  # raised elements
    border: str
    border_strong: str
    text: str
    text_dim: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_press: str
    accent_text: str
    success: str
    warning: str
    danger: str
    canvas: str
    shadow: str


DARK = Palette(
    name="dark",
    bg="#0E0F14",
    surface="#15171F",
    surface_alt="#1C1F29",
    surface_high="#242836",
    border="#252A38",
    border_strong="#333A4D",
    text="#E9ECF5",
    text_dim="#9AA3B8",
    text_faint="#646E85",
    accent="#6D5EF8",
    accent_hover="#7F72FA",
    accent_press="#5B4CE0",
    accent_text="#FFFFFF",
    success="#3DD68C",
    warning="#F5B14C",
    danger="#F2555A",
    canvas="#0A0B0F",
    shadow="rgba(0, 0, 0, 140)",
)

LIGHT = Palette(
    name="light",
    bg="#F4F5F9",
    surface="#FFFFFF",
    surface_alt="#F0F1F6",
    surface_high="#E7E9F1",
    border="#E1E3EC",
    border_strong="#C9CDDB",
    text="#161923",
    text_dim="#5A6178",
    text_faint="#8B92A6",
    accent="#5B4CE0",
    accent_hover="#6D5EF8",
    accent_press="#4A3CC4",
    accent_text="#FFFFFF",
    success="#12A268",
    warning="#C77A11",
    danger="#D63B41",
    canvas="#DFE2EA",
    shadow="rgba(20, 24, 40, 40)",
)

PALETTES = {"dark": DARK, "light": LIGHT}


def palette_for(theme: str, accent: str | None = None) -> Palette:
    base = PALETTES.get(theme, DARK)
    if not accent or accent.lower() == base.accent.lower():
        return base
    color = QColor(accent)
    if not color.isValid():
        return base
    return Palette(
        **{
            **base.__dict__,
            "accent": color.name(),
            "accent_hover": color.lighter(115).name(),
            "accent_press": color.darker(115).name(),
            "accent_text": "#FFFFFF" if color.lightnessF() < 0.62 else "#101219",
        }
    )


ACCENT_SWATCHES: tuple[tuple[str, str], ...] = (
    ("Iris", "#6D5EF8"),
    ("Cyan", "#22B8CF"),
    ("Emerald", "#22C55E"),
    ("Amber", "#F59E0B"),
    ("Rose", "#F43F5E"),
    ("Violet", "#A855F7"),
    ("Slate", "#64748B"),
)


def ui_font() -> QFont:
    """Prefer a modern UI face, fall back gracefully."""
    families = QFontDatabase.families()
    for candidate in ("Inter", "Segoe UI Variable Text", "Segoe UI", "SF Pro Text",
                      "Ubuntu", "Noto Sans"):
        if candidate in families:
            font = QFont(candidate)
            break
    else:
        font = QFont()
    font.setPointSizeF(9.5)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def mono_font() -> QFont:
    families = QFontDatabase.families()
    for candidate in ("JetBrains Mono", "Cascadia Mono", "Consolas", "SF Mono",
                      "DejaVu Sans Mono"):
        if candidate in families:
            return QFont(candidate)
    return QFont("monospace")


STYLESHEET = """
* {{
    outline: 0;
}}

QWidget {{
    color: {text};
    background: transparent;
    font-size: 13px;
}}

#Root {{
    background: {bg};
    border: 1px solid {border_strong};
    border-radius: 12px;
}}

#RootMaximized {{
    background: {bg};
    border: 0;
    border-radius: 0;
}}

/* ------------------------------------------------------------ title bar */
#TitleBar {{
    background: {surface};
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
    border-bottom: 1px solid {border};
}}

#TitleBarFlat {{
    background: {surface};
    border-radius: 0;
    border-bottom: 1px solid {border};
}}

#AppTitle {{
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}

#AppSubtitle {{
    color: {text_faint};
    font-size: 11px;
}}

#WinButton {{
    background: transparent;
    border: 0;
    border-radius: 6px;
    padding: 0;
}}
#WinButton:hover {{ background: {surface_high}; }}
#WinButton:pressed {{ background: {border_strong}; }}
#WinClose:hover {{ background: {danger}; }}

/* ---------------------------------------------------------------- cards */
#Card {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 10px;
}}

#CardFlat {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 8px;
}}

#SectionTitle {{
    color: {text_dim};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.9px;
}}

#Hint {{
    color: {text_faint};
    font-size: 11px;
}}

#Mono {{
    color: {text_dim};
    font-size: 11px;
}}

#Divider {{
    background: {border};
    max-height: 1px;
    min-height: 1px;
    border: 0;
}}

/* -------------------------------------------------------------- buttons */
QPushButton {{
    background: {surface_alt};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {surface_high}; border-color: {accent}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{
    color: {text_faint}; border-color: {border}; background: {surface};
}}

QPushButton#Primary {{
    background: {accent};
    color: {accent_text};
    border: 1px solid {accent};
    font-weight: 600;
    padding: 9px 18px;
}}
QPushButton#Primary:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton#Primary:pressed {{ background: {accent_press}; }}
QPushButton#Primary:disabled {{
    background: {surface_high}; color: {text_faint}; border-color: {border};
}}

QPushButton#Danger:hover {{ border-color: {danger}; color: {danger}; }}

QPushButton#Ghost {{
    background: transparent;
    border: 1px solid transparent;
    color: {text_dim};
    padding: 6px 10px;
}}
QPushButton#Ghost:hover {{ background: {surface_alt}; color: {text}; }}

QPushButton#Chip {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 13px;
    padding: 5px 9px;
    color: {text_dim};
    font-size: 12px;
}}
QPushButton#Chip:hover {{ border-color: {accent}; color: {text}; }}
QPushButton#Chip:checked {{
    background: {accent}; color: {accent_text}; border-color: {accent}; font-weight: 600;
}}

QPushButton#SegItem {{
    background: transparent;
    border: 0;
    border-radius: 6px;
    padding: 6px 12px;
    color: {text_dim};
    font-weight: 500;
}}
QPushButton#SegItem:hover {{ color: {text}; }}
QPushButton#SegItem:checked {{
    background: {surface_high}; color: {text}; font-weight: 600;
}}

#SegmentBox {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 8px;
}}

QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px;
}}
QToolButton:hover {{ background: {surface_high}; }}
QToolButton:checked {{ background: {accent}; }}

/* --------------------------------------------------------------- inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {surface_alt};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {accent};
    selection-color: {accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {text_faint}; background: {surface};
}}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 16px;
    border: 0;
    background: transparent;
    margin-right: 3px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({caret_up}); width: 9px; height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({caret_down}); width: 9px; height: 9px;
}}

QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox::down-arrow {{ image: url({caret_down}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {surface_high};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {accent};
    selection-color: {accent_text};
    outline: 0;
}}

/* -------------------------------------------------------------- sliders */
QSlider::groove:horizontal {{
    height: 4px;
    background: {surface_high};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {text};
    border: 3px solid {accent};
    width: 8px;
    height: 8px;
    margin: -6px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ border-color: {accent_hover}; }}
QSlider::handle:horizontal:disabled {{
    background: {text_faint}; border-color: {border_strong};
}}

/* ------------------------------------------------------------ checkable */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {border_strong};
    border-radius: 5px;
    background: {surface_alt};
}}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent}; border-color: {accent};
    image: url({check});
}}

QRadioButton::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {border_strong};
    border-radius: 8px;
    background: {surface_alt};
}}
QRadioButton::indicator:checked {{
    border: 5px solid {accent};
    background: {surface};
}}

/* ------------------------------------------------------------ tab strip */
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{
    background: transparent;
    color: {text_dim};
    padding: 8px 3px;
    margin-right: 14px;
    border: 0;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}}
QTabBar::tab:hover {{ color: {text}; }}
QTabBar::tab:selected {{
    color: {text};
    border-bottom: 2px solid {accent};
    font-weight: 600;
}}

/* ----------------------------------------------------------------- list */
QListWidget {{
    background: transparent;
    border: 0;
    outline: 0;
}}
QListWidget::item {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 9px;
    margin: 0 0 6px 0;
    padding: 0;
}}
QListWidget::item:hover {{ border-color: {border_strong}; }}
QListWidget::item:selected {{
    background: {surface_high};
    border-color: {accent};
}}

/* --------------------------------------------------------------- scroll */
QScrollArea {{ background: transparent; border: 0; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {border_strong}; border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {text_faint}; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {border_strong}; border-radius: 4px; min-width: 32px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ------------------------------------------------------------- progress */
QProgressBar {{
    background: {surface_high};
    border: 0;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 4px;
}}

/* --------------------------------------------------------------- misc */
QToolTip {{
    background: {surface_high};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 7px;
    padding: 6px 9px;
}}

QMenu {{
    background: {surface_high};
    border: 1px solid {border_strong};
    border-radius: 9px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent}; color: {accent_text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

#StatusBar {{
    background: {surface};
    border-top: 1px solid {border};
    border-bottom-left-radius: 11px;
    border-bottom-right-radius: 11px;
}}
#StatusBarFlat {{
    background: {surface};
    border-top: 1px solid {border};
    border-radius: 0;
}}

#Badge {{
    background: {surface_high};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 2px 9px;
    color: {text_dim};
    font-size: 11px;
    font-weight: 600;
}}
#BadgeOk {{ color: {success}; border-color: {success}; }}
#BadgeWarn {{ color: {warning}; border-color: {warning}; }}
#BadgeErr {{ color: {danger}; border-color: {danger}; }}

#Toast {{
    background: {surface_high};
    border: 1px solid {border_strong};
    border-radius: 10px;
}}
"""


def build_stylesheet(palette: Palette, assets: dict[str, str]) -> str:
    return STYLESHEET.format(**palette.__dict__, **assets)
