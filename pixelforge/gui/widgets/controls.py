"""Small composable controls used across the settings panels."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import icons


class Card(QFrame):
    """Rounded surface with an optional title row."""

    def __init__(self, title: str = "", parent: QWidget | None = None,
                 flat: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("CardFlat" if flat else "Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 14)
        self._layout.setSpacing(10)
        self.header: QHBoxLayout | None = None
        if title:
            self.header = QHBoxLayout()
            self.header.setSpacing(8)
            label = QLabel(title.upper())
            label.setObjectName("SectionTitle")
            # Wrapping keeps a long heading from setting the panel's minimum width.
            label.setWordWrap(True)
            self.header.addWidget(label, 1)
            self._layout.addLayout(self.header)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.HLine)
    return line


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


def badge(text: str, kind: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName({"ok": "BadgeOk", "warn": "BadgeWarn",
                         "err": "BadgeErr"}.get(kind, "Badge"))
    label.setProperty("class", "badge")
    return label


class IconButton(QToolButton):
    def __init__(self, name: str, tooltip: str = "", size: int = 18,
                 checkable: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._size = size
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.setIconSize(QSize(size, size))
        self.setFixedSize(size + 14, size + 14)

    def apply_color(self, color: str) -> None:
        self.setIcon(icons.icon(self._name, color, self._size))


class SegmentedControl(QWidget):
    """iOS-style segmented picker backed by a QButtonGroup."""

    changed = Signal(int)

    def __init__(self, options: Iterable[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SegmentBox")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for index, text in enumerate(options):
            button = QPushButton(text)
            button.setObjectName("SegItem")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            # Ignored so a long label cannot force the whole panel wider; the
            # stretch factor still keeps the segments equal.
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(38)
            layout.addWidget(button, 1)
            self.group.addButton(button, index)
        self.group.idClicked.connect(self.changed.emit)
        if self.group.buttons():
            self.group.buttons()[0].setChecked(True)

    def current(self) -> int:
        return self.group.checkedId()

    def set_current(self, index: int) -> None:
        button = self.group.button(index)
        if button:
            button.setChecked(True)


class ToggleSwitch(QWidget):
    """Animated on/off switch."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._offset = 1.0 if checked else 0.0
        self._track_off = QColor("#333A4D")
        self._track_on = QColor("#6D5EF8")
        self._knob = QColor("#FFFFFF")
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def set_colors(self, track_off: str, track_on: str, knob: str) -> None:
        self._track_off = QColor(track_off)
        self._track_on = QColor(track_on)
        self._knob = QColor(knob)
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        if value == self._checked:
            return
        self._checked = value
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if value else 0.0)
        self._anim.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = self.height() / 2
        track = QColor(self._track_off)
        target = QColor(self._track_on)
        blend = QColor(
            int(track.red() + (target.red() - track.red()) * self._offset),
            int(track.green() + (target.green() - track.green()) * self._offset),
            int(track.blue() + (target.blue() - track.blue()) * self._offset),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(blend)
        painter.drawRoundedRect(self.rect(), radius, radius)

        knob_d = self.height() - 6
        x = 3 + self._offset * (self.width() - knob_d - 6)
        painter.setBrush(self._knob)
        painter.drawEllipse(int(x), 3, knob_d, knob_d)
        painter.end()


class LabeledToggle(QWidget):
    toggled = Signal(bool)

    def __init__(self, text: str, checked: bool = False, tooltip: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.switch = ToggleSwitch(checked)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.switch, 0)
        self.switch.toggled.connect(self.toggled.emit)
        if tooltip:
            self.setToolTip(tooltip)

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setChecked(self, value: bool) -> None:
        self.switch.setChecked(value)


class SliderRow(QWidget):
    """Label + slider + numeric box + reset, kept in sync.

    The slider works in integers; ``scale`` maps them onto the float value the
    core expects (e.g. scale=100 gives 0.01 steps).
    """

    valueChanged = Signal(float)

    def __init__(
        self,
        text: str,
        minimum: float,
        maximum: float,
        default: float,
        *,
        scale: int = 100,
        decimals: int = 2,
        suffix: str = "",
        tooltip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scale = scale
        self._default = default
        self._guard = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.label = QLabel(text)
        self.label.setObjectName("Hint")
        self.label.setWordWrap(True)
        self.reset_button = QToolButton()
        self.reset_button.setObjectName("ResetTiny")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.setToolTip("Reset")
        self.reset_button.setFixedSize(18, 18)
        self.reset_button.setIconSize(QSize(12, 12))
        self.reset_button.clicked.connect(lambda: self.set_value(self._default))

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(max(1.0 / scale, (maximum - minimum) / 100.0))
        self.spin.setValue(default)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(72)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)

        head.addWidget(self.label, 1)
        head.addWidget(self.reset_button, 0)
        head.addWidget(self.spin, 0)
        root.addLayout(head)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(minimum * scale), int(maximum * scale))
        self.slider.setValue(int(default * scale))
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self.slider)

        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        if tooltip:
            self.setToolTip(tooltip)

    def apply_color(self, color: str) -> None:
        self.reset_button.setIcon(icons.icon("reset", color, 12))

    def _from_slider(self, raw: int) -> None:
        if self._guard:
            return
        self._guard = True
        value = raw / self._scale
        self.spin.setValue(value)
        self._guard = False
        self.valueChanged.emit(value)

    def _from_spin(self, value: float) -> None:
        if self._guard:
            return
        self._guard = True
        self.slider.setValue(round(value * self._scale))
        self._guard = False
        self.valueChanged.emit(value)

    def value(self) -> float:
        return self.spin.value()

    def set_value(self, value: float) -> None:
        self._guard = True
        self.spin.setValue(value)
        self.slider.setValue(round(value * self._scale))
        self._guard = False
        self.valueChanged.emit(value)

    def set_default(self, value: float) -> None:
        self._default = value


class Spinner(QWidget):
    """Indeterminate activity ring, shown while a render is queued."""

    def __init__(self, size: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._color = QColor("#6D5EF8")
        self.setFixedSize(size, size)
        self._anim = QPropertyAnimation(self, b"angle", self)
        self._anim.setDuration(900)
        self._anim.setStartValue(0)
        self._anim.setEndValue(360)
        self._anim.setLoopCount(-1)
        self.hide()

    def get_angle(self) -> int:
        return self._angle

    def set_angle(self, value: int) -> None:
        self._angle = value
        self.update()

    angle = Property(int, get_angle, set_angle)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)

    def start(self) -> None:
        self.show()
        self._anim.start()

    def stop(self) -> None:
        self._anim.stop()
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawArc(rect, -self._angle * 16, 110 * 16)
        painter.end()


def expanding() -> QSizePolicy:
    return QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
