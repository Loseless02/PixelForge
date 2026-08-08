"""Transient bottom-centre notifications."""

from __future__ import annotations

import contextlib

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from .. import icons

_KIND_ICON = {"info": "info", "ok": "check", "warn": "warning", "err": "warning"}


class Toast(QWidget):
    """A single message that fades in, waits, then fades out and deletes itself."""

    def __init__(self, parent: QWidget, text: str, kind: str = "info",
                 accent: str = "#6D5EF8", timeout: int = 3200) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 16, 10)
        layout.setSpacing(9)

        color = {"ok": "#3DD68C", "warn": "#F5B14C", "err": "#F2555A"}.get(kind, accent)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(_KIND_ICON.get(kind, "info"), color, 16))
        glyph.setFixedSize(18, 18)
        glyph.setScaledContents(True)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setMaximumWidth(460)

        layout.addWidget(glyph, 0)
        layout.addWidget(label, 1)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

        QTimer.singleShot(timeout, self._dismiss)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 78
        self.move(max(12, x), max(12, y))

    def _dismiss(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()


class ToastHost:
    """Keeps at most one toast alive per parent widget."""

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._current: Toast | None = None
        self.accent = "#6D5EF8"

    def show(self, text: str, kind: str = "info", timeout: int = 3200) -> None:
        if self._current is not None:
            # It may already have been reaped by its own fade-out.
            with contextlib.suppress(RuntimeError):
                self._current.deleteLater()
        toast = Toast(self._parent, text, kind, self.accent, timeout)
        toast.destroyed.connect(lambda: self._forget(toast))
        self._current = toast

    def _forget(self, toast: Toast) -> None:
        if self._current is toast:
            self._current = None
