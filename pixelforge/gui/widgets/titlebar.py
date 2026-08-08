"""Custom title bar for the frameless main window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import icons


class WindowButton(QPushButton):
    def __init__(self, name: str, tooltip: str, close: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self.setObjectName("WinClose" if close else "WinButton")
        if close:
            self.setProperty("closeButton", True)
        self.setFixedSize(34, 28)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_glyph(self, name: str) -> None:
        self._name = name

    def apply_color(self, color: str) -> None:
        self.setIcon(icons.icon(self._name, color, 15))


class TitleBar(QWidget):
    """Drag-to-move strip holding the wordmark, a menu slot and window buttons."""

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(
        self, title: str, subtitle: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(10)

        self.logo = QLabel()
        self.logo.setPixmap(icons.app_icon().pixmap(20, 20))
        self.logo.setFixedSize(22, 22)
        self.logo.setScaledContents(True)

        self.title = QLabel(title)
        self.title.setObjectName("AppTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("AppSubtitle")

        layout.addWidget(self.logo)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addSpacing(8)

        self.slot = QHBoxLayout()
        self.slot.setSpacing(6)
        layout.addLayout(self.slot)
        layout.addStretch(1)

        self.trailing = QHBoxLayout()
        self.trailing.setSpacing(6)
        layout.addLayout(self.trailing)
        layout.addSpacing(6)

        self.btn_min = WindowButton("minimize", "Minimize")
        self.btn_max = WindowButton("maximize", "Maximize")
        self.btn_close = WindowButton("close", "Close", close=True)
        for button in (self.btn_min, self.btn_max, self.btn_close):
            layout.addWidget(button)

        self.btn_min.clicked.connect(self.minimize_requested.emit)
        self.btn_max.clicked.connect(self.maximize_requested.emit)
        self.btn_close.clicked.connect(self.close_requested.emit)

    def set_maximized(self, maximized: bool) -> None:
        self.btn_max.set_glyph("restore" if maximized else "maximize")
        self.btn_max.setToolTip("Restore" if maximized else "Maximize")
        self.setObjectName("TitleBarFlat" if maximized else "TitleBar")

    def apply_color(self, color: str, danger_text: str = "#FFFFFF") -> None:
        self.btn_min.apply_color(color)
        self.btn_max.apply_color(color)
        self.btn_close.apply_color(color)
        self.logo.setPixmap(icons.app_icon().pixmap(20, 20))

    # ---------------------------------------------------------------- drag
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window().windowHandle()
            if window is not None:
                window.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
