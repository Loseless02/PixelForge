"""Preview canvas: zoom/pan, before-after split, and interactive cropping."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from ...core.models import CropRect

_HANDLE = 9.0
_EDGE = 7.0


class Handle(str, Enum):
    NONE = ""
    MOVE = "move"
    TL = "tl"
    TR = "tr"
    BL = "bl"
    BR = "br"
    T = "t"
    B = "b"
    L = "l"
    R = "r"


_CURSORS = {
    Handle.MOVE: Qt.CursorShape.SizeAllCursor,
    Handle.TL: Qt.CursorShape.SizeFDiagCursor,
    Handle.BR: Qt.CursorShape.SizeFDiagCursor,
    Handle.TR: Qt.CursorShape.SizeBDiagCursor,
    Handle.BL: Qt.CursorShape.SizeBDiagCursor,
    Handle.T: Qt.CursorShape.SizeVerCursor,
    Handle.B: Qt.CursorShape.SizeVerCursor,
    Handle.L: Qt.CursorShape.SizeHorCursor,
    Handle.R: Qt.CursorShape.SizeHorCursor,
}


@dataclass
class CanvasColors:
    canvas: str = "#0A0B0F"
    text: str = "#E9ECF5"
    dim: str = "#9AA3B8"
    faint: str = "#646E85"
    accent: str = "#6D5EF8"
    surface: str = "#15171F"
    border: str = "#333A4D"


class PreviewCanvas(QWidget):
    """Displays the render preview and hosts the crop tool.

    Two pixmaps are kept: ``before`` (the untouched source) and ``after`` (the
    rendered preview). They are drawn into the same on-screen rectangle so the
    split handle compares like for like.
    """

    crop_changed = Signal(object)      # CropRect
    files_dropped = Signal(list)       # list[str]
    zoom_changed = Signal(float)
    request_open = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(360, 260)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.colors = CanvasColors()
        self._before: QPixmap | None = None
        self._after: QPixmap | None = None
        self._source_size = QSize(0, 0)

        self._zoom = 1.0
        self._fit = True
        self._offset = QPointF(0.0, 0.0)
        self._panning = False
        self._pan_origin = QPoint()

        self._split = 0.5
        self._split_enabled = False
        self._dragging_split = False

        self._crop_mode = False
        self._crop = CropRect()
        self._crop_ratio: float | None = None
        self._active_handle = Handle.NONE
        self._drag_origin = QPointF()
        self._drag_rect = CropRect()

        self._checker = _checkerboard()
        self._placeholder = "Drop images here"
        self._placeholder_hint = "or press Ctrl+O to browse  ·  PNG JPG WEBP TIFF HEIC AVIF"

    # ------------------------------------------------------------- content
    def set_images(self, before: QPixmap | None, after: QPixmap | None,
                   source_size: QSize | None = None) -> None:
        first = self._after is None and after is not None
        self._before = before
        self._after = after
        if source_size is not None:
            self._source_size = source_size
        if first:
            self.fit_to_window()
        self.update()

    def clear(self) -> None:
        self._before = self._after = None
        self._source_size = QSize(0, 0)
        self._crop = CropRect()
        self.update()

    def has_image(self) -> bool:
        return self._after is not None

    def before_pixmap(self) -> QPixmap | None:
        return self._before

    def effective_zoom(self) -> float:
        return self._effective_zoom()

    def set_colors(self, colors: CanvasColors) -> None:
        self.colors = colors
        self.update()

    # ---------------------------------------------------------------- zoom
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float, anchor: QPointF | None = None) -> None:
        value = max(0.05, min(16.0, value))
        if abs(value - self._zoom) < 1e-6:
            return
        if anchor is not None and self._after is not None:
            before = self._widget_to_image(anchor)
            self._zoom = value
            self._fit = False
            after = self._widget_to_image(anchor)
            scale = self._display_scale()
            self._offset += QPointF((after.x() - before.x()) * scale,
                                    (after.y() - before.y()) * scale)
        else:
            self._zoom = value
            self._fit = False
        self.zoom_changed.emit(self._zoom)
        self.update()

    def fit_to_window(self) -> None:
        self._fit = True
        self._offset = QPointF(0.0, 0.0)
        self.zoom_changed.emit(self._effective_zoom())
        self.update()

    def zoom_to_actual(self) -> None:
        self._fit = False
        self._offset = QPointF(0.0, 0.0)
        self.set_zoom(1.0)

    def is_fit(self) -> bool:
        return self._fit

    # --------------------------------------------------------------- split
    def set_split_enabled(self, enabled: bool) -> None:
        self._split_enabled = enabled
        self.update()

    def split_enabled(self) -> bool:
        return self._split_enabled

    # ---------------------------------------------------------------- crop
    def set_crop_mode(self, enabled: bool) -> None:
        self._crop_mode = enabled
        if enabled and self._crop.is_empty and not self._source_size.isEmpty():
            self._crop = CropRect(0, 0, self._source_size.width(),
                                  self._source_size.height())
            self.crop_changed.emit(self._crop)
        self.setCursor(
            Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def crop_mode(self) -> bool:
        return self._crop_mode

    def set_crop(self, crop: CropRect) -> None:
        self._crop = crop
        self.update()

    def crop(self) -> CropRect:
        return self._crop

    def set_crop_ratio(self, ratio: float | None) -> None:
        self._crop_ratio = ratio
        if ratio and not self._crop.is_empty:
            self._crop = self._apply_ratio(self._crop, Handle.BR)
            self.crop_changed.emit(self._crop)
            self.update()

    def reset_crop(self) -> None:
        if self._source_size.isEmpty():
            self._crop = CropRect()
        else:
            self._crop = CropRect(0, 0, self._source_size.width(),
                                  self._source_size.height())
        self.crop_changed.emit(self._crop)
        self.update()

    # ------------------------------------------------------------ geometry
    def _base_pixmap(self) -> QPixmap | None:
        if self._crop_mode:
            return self._before or self._after
        return self._after or self._before

    def _content_size(self) -> QSize:
        pixmap = self._base_pixmap()
        if pixmap is None:
            return QSize(0, 0)
        return pixmap.size() / pixmap.devicePixelRatio()

    def _fit_scale(self) -> float:
        content = self._content_size()
        if content.isEmpty():
            return 1.0
        margin = 32
        available_w = max(1, self.width() - margin)
        available_h = max(1, self.height() - margin)
        return min(available_w / content.width(), available_h / content.height())

    def _effective_zoom(self) -> float:
        return self._fit_scale() if self._fit else self._zoom

    def _display_scale(self) -> float:
        return self._effective_zoom()

    def _image_rect(self) -> QRectF:
        content = self._content_size()
        if content.isEmpty():
            return QRectF()
        scale = self._display_scale()
        width = content.width() * scale
        height = content.height() * scale
        x = (self.width() - width) / 2 + self._offset.x()
        y = (self.height() - height) / 2 + self._offset.y()
        return QRectF(x, y, width, height)

    def _widget_to_image(self, point: QPointF) -> QPointF:
        rect = self._image_rect()
        if rect.isEmpty():
            return QPointF()
        scale = self._display_scale()
        return QPointF((point.x() - rect.x()) / scale, (point.y() - rect.y()) / scale)

    def _crop_rect_widget(self) -> QRectF:
        rect = self._image_rect()
        content = self._content_size()
        if rect.isEmpty() or content.isEmpty() or self._source_size.isEmpty():
            return QRectF()
        sx = rect.width() / self._source_size.width()
        sy = rect.height() / self._source_size.height()
        return QRectF(
            rect.x() + self._crop.x * sx,
            rect.y() + self._crop.y * sy,
            self._crop.width * sx,
            self._crop.height * sy,
        )

    def _widget_to_source(self, point: QPointF) -> QPointF:
        rect = self._image_rect()
        if rect.isEmpty() or self._source_size.isEmpty():
            return QPointF()
        sx = self._source_size.width() / rect.width()
        sy = self._source_size.height() / rect.height()
        return QPointF((point.x() - rect.x()) * sx, (point.y() - rect.y()) * sy)

    # -------------------------------------------------------------- events
    def wheelEvent(self, event) -> None:
        if not self.has_image():
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.0015 ** delta
        self.set_zoom(self._effective_zoom() * factor, QPointF(event.position()))
        event.accept()

    def mousePressEvent(self, event) -> None:
        if not self.has_image():
            if event.button() == Qt.MouseButton.LeftButton:
                self.request_open.emit()
            return
        position = QPointF(event.position())

        if event.button() == Qt.MouseButton.LeftButton and self._crop_mode:
            handle = self._hit_test(position)
            self._active_handle = handle if handle is not Handle.NONE else Handle.MOVE
            self._drag_origin = self._widget_to_source(position)
            self._drag_rect = self._crop
            if handle is Handle.NONE:
                point = self._drag_origin
                self._crop = CropRect(int(point.x()), int(point.y()), 1, 1)
                self._active_handle = Handle.BR
                self._drag_rect = self._crop
            event.accept()
            return

        if (event.button() == Qt.MouseButton.LeftButton and self._split_enabled
                and self._near_split(position)):
            self._dragging_split = True
            event.accept()
            return

        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._panning = True
            self._pan_origin = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        position = QPointF(event.position())

        if self._panning:
            current = event.globalPosition().toPoint()
            delta = current - self._pan_origin
            self._pan_origin = current
            self._fit = False
            if abs(self._zoom - self._effective_zoom()) > 1e-6:
                self._zoom = self._effective_zoom()
            self._offset += QPointF(delta.x(), delta.y())
            self.update()
            return

        if self._dragging_split:
            rect = self._image_rect()
            if rect.width() > 0:
                self._split = min(1.0, max(0.0, (position.x() - rect.x()) / rect.width()))
                self.update()
            return

        if self._crop_mode and self._active_handle is not Handle.NONE:
            self._resize_crop(position)
            return

        if self._crop_mode:
            handle = self._hit_test(position)
            self.setCursor(QCursor(_CURSORS.get(handle, Qt.CursorShape.CrossCursor)))
            return

        if self._split_enabled and self._near_split(position):
            self.setCursor(Qt.CursorShape.SplitHCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._dragging_split:
            self._dragging_split = False
        if self._active_handle is not Handle.NONE:
            self._active_handle = Handle.NONE
            self.crop_changed.emit(self._crop)
        if self._crop_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.has_image() and not self._crop_mode:
            self.fit_to_window()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    # ---------------------------------------------------------- crop logic
    def _hit_test(self, position: QPointF) -> Handle:
        rect = self._crop_rect_widget()
        if rect.isEmpty():
            return Handle.NONE
        near = _HANDLE
        left, right = rect.left(), rect.right()
        top, bottom = rect.top(), rect.bottom()
        x, y = position.x(), position.y()

        on_left = abs(x - left) <= near
        on_right = abs(x - right) <= near
        on_top = abs(y - top) <= near
        on_bottom = abs(y - bottom) <= near
        inside_x = left - near <= x <= right + near
        inside_y = top - near <= y <= bottom + near

        if on_left and on_top:
            return Handle.TL
        if on_right and on_top:
            return Handle.TR
        if on_left and on_bottom:
            return Handle.BL
        if on_right and on_bottom:
            return Handle.BR
        if on_left and inside_y:
            return Handle.L
        if on_right and inside_y:
            return Handle.R
        if on_top and inside_x:
            return Handle.T
        if on_bottom and inside_x:
            return Handle.B
        if rect.contains(position):
            return Handle.MOVE
        return Handle.NONE

    def _resize_crop(self, position: QPointF) -> None:
        point = self._widget_to_source(position)
        origin = self._drag_origin
        base = self._drag_rect
        max_w, max_h = self._source_size.width(), self._source_size.height()

        left, top = base.x, base.y
        right, bottom = base.x + base.width, base.y + base.height
        dx = int(point.x() - origin.x())
        dy = int(point.y() - origin.y())

        handle = self._active_handle
        if handle is Handle.MOVE:
            width, height = base.width, base.height
            left = max(0, min(base.x + dx, max_w - width))
            top = max(0, min(base.y + dy, max_h - height))
            self._crop = CropRect(left, top, width, height)
            self.update()
            return

        if handle in (Handle.TL, Handle.L, Handle.BL):
            left = max(0, min(int(point.x()), right - 8))
        if handle in (Handle.TR, Handle.R, Handle.BR):
            right = min(max_w, max(int(point.x()), left + 8))
        if handle in (Handle.TL, Handle.T, Handle.TR):
            top = max(0, min(int(point.y()), bottom - 8))
        if handle in (Handle.BL, Handle.B, Handle.BR):
            bottom = min(max_h, max(int(point.y()), top + 8))

        candidate = CropRect(left, top, right - left, bottom - top)
        if self._crop_ratio:
            candidate = self._apply_ratio(candidate, handle)
        self._crop = candidate.clamped(max_w, max_h)
        self.update()

    def _apply_ratio(self, rect: CropRect, handle: Handle) -> CropRect:
        """Force ``rect`` to the locked aspect ratio, anchored opposite the handle."""
        ratio = self._crop_ratio
        if not ratio:
            return rect
        max_w, max_h = self._source_size.width(), self._source_size.height()
        width, height = rect.width, rect.height
        if handle in (Handle.L, Handle.R):
            height = round(width / ratio)
        elif handle in (Handle.T, Handle.B) or width / max(1, height) > ratio:
            width = round(height * ratio)
        else:
            height = round(width / ratio)

        width = max(8, min(width, max_w))
        height = max(8, min(height, max_h))
        if width / height > ratio:
            width = round(height * ratio)
        else:
            height = round(width / ratio)

        anchor_right = handle in (Handle.TL, Handle.L, Handle.BL)
        anchor_bottom = handle in (Handle.TL, Handle.T, Handle.TR)
        x = rect.x + rect.width - width if anchor_right else rect.x
        y = rect.y + rect.height - height if anchor_bottom else rect.y
        x = max(0, min(x, max_w - width))
        y = max(0, min(y, max_h - height))
        return CropRect(x, y, width, height)

    def _near_split(self, position: QPointF) -> bool:
        rect = self._image_rect()
        if rect.isEmpty():
            return False
        return abs(position.x() - (rect.x() + rect.width() * self._split)) <= _EDGE

    # -------------------------------------------------------------- render
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(self.colors.canvas))

        base = self._base_pixmap()
        if base is None:
            self._paint_placeholder(painter)
            painter.end()
            return

        rect = self._image_rect()
        painter.save()
        painter.setClipRect(rect.toRect())
        painter.setBrushOrigin(rect.topLeft().toPoint())
        painter.fillRect(rect, QBrush(self._checker))
        painter.restore()

        if self._crop_mode:
            painter.drawPixmap(rect, base, QRectF(base.rect()))
            self._paint_crop(painter, rect)
        elif self._split_enabled and self._before is not None and self._after is not None:
            self._paint_split(painter, rect)
        else:
            painter.drawPixmap(rect, base, QRectF(base.rect()))

        self._paint_frame(painter, rect)
        painter.end()

    def _paint_split(self, painter: QPainter, rect: QRectF) -> None:
        divider_x = rect.x() + rect.width() * self._split

        painter.save()
        painter.setClipRect(QRectF(rect.x(), rect.y(), divider_x - rect.x(), rect.height()))
        painter.drawPixmap(rect, self._before, QRectF(self._before.rect()))
        painter.restore()

        painter.save()
        painter.setClipRect(
            QRectF(divider_x, rect.y(), rect.right() - divider_x, rect.height())
        )
        painter.drawPixmap(rect, self._after, QRectF(self._after.rect()))
        painter.restore()

        pen = QPen(QColor(255, 255, 255, 210), 1.6)
        painter.setPen(pen)
        painter.drawLine(QPointF(divider_x, rect.top()), QPointF(divider_x, rect.bottom()))

        knob = QRectF(divider_x - 15, rect.center().y() - 15, 30, 30)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1.4))
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawEllipse(knob)
        painter.setPen(QPen(QColor(255, 255, 255, 235), 1.6))
        cy = knob.center().y()
        painter.drawLine(QPointF(divider_x - 7, cy), QPointF(divider_x - 2, cy))
        painter.drawLine(QPointF(divider_x + 2, cy), QPointF(divider_x + 7, cy))
        painter.drawLine(QPointF(divider_x - 7, cy), QPointF(divider_x - 4, cy - 3))
        painter.drawLine(QPointF(divider_x - 7, cy), QPointF(divider_x - 4, cy + 3))
        painter.drawLine(QPointF(divider_x + 7, cy), QPointF(divider_x + 4, cy - 3))
        painter.drawLine(QPointF(divider_x + 7, cy), QPointF(divider_x + 4, cy + 3))

        self._paint_tag(painter, QPointF(rect.x() + 12, rect.y() + 12), "BEFORE")
        self._paint_tag(painter, QPointF(rect.right() - 66, rect.y() + 12), "AFTER")

    def _paint_tag(self, painter: QPainter, top_left: QPointF, text: str) -> None:
        font = QFont(painter.font())
        font.setPointSizeF(8.0)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(font)
        box = QRectF(top_left.x(), top_left.y(), 54, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(QColor(255, 255, 255, 225))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_crop(self, painter: QPainter, rect: QRectF) -> None:
        crop = self._crop_rect_widget()
        if crop.isEmpty():
            return

        shade = QColor(0, 0, 0, 150)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawRect(QRectF(rect.x(), rect.y(), rect.width(), crop.top() - rect.y()))
        painter.drawRect(QRectF(rect.x(), crop.bottom(), rect.width(),
                                rect.bottom() - crop.bottom()))
        painter.drawRect(QRectF(rect.x(), crop.top(), crop.left() - rect.x(),
                                crop.height()))
        painter.drawRect(QRectF(crop.right(), crop.top(), rect.right() - crop.right(),
                                crop.height()))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
        for i in (1, 2):
            x = crop.left() + crop.width() * i / 3
            y = crop.top() + crop.height() * i / 3
            painter.drawLine(QPointF(x, crop.top()), QPointF(x, crop.bottom()))
            painter.drawLine(QPointF(crop.left(), y), QPointF(crop.right(), y))

        painter.setPen(QPen(QColor(255, 255, 255, 235), 1.4))
        painter.drawRect(crop)

        accent = QColor(self.colors.accent)
        painter.setBrush(accent)
        painter.setPen(QPen(QColor(255, 255, 255, 235), 1.2))
        for point in (crop.topLeft(), crop.topRight(), crop.bottomLeft(),
                      crop.bottomRight()):
            painter.drawEllipse(point, 5.0, 5.0)
        for point in (QPointF(crop.center().x(), crop.top()),
                      QPointF(crop.center().x(), crop.bottom()),
                      QPointF(crop.left(), crop.center().y()),
                      QPointF(crop.right(), crop.center().y())):
            painter.drawEllipse(point, 3.6, 3.6)

        label = f"{self._crop.width} x {self._crop.height}"
        font = QFont(painter.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        painter.setFont(font)
        box = QRectF(crop.center().x() - 55, crop.bottom() + 8, 110, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(box, 7, 7)
        painter.setPen(QColor(255, 255, 255, 230))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_frame(self, painter: QPainter, rect: QRectF) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        painter.drawRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5))

    def _paint_placeholder(self, painter: QPainter) -> None:
        rect = QRectF(self.rect()).adjusted(28, 28, -28, -28)
        accent = QColor(self.colors.accent)

        glow = QLinearGradient(rect.topLeft(), rect.bottomRight())
        glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 26))
        glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 6))
        painter.setBrush(glow)
        pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 120), 1.6)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([7, 6])
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 16, 16)

        center = rect.center()
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 190), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(center.x() - 26, center.y() - 52, 52, 42), 6, 6)
        painter.drawLine(QPointF(center.x() - 20, center.y() - 20),
                         QPointF(center.x() - 6, center.y() - 34))
        painter.drawLine(QPointF(center.x() - 6, center.y() - 34),
                         QPointF(center.x() + 4, center.y() - 24))
        painter.drawLine(QPointF(center.x() + 4, center.y() - 24),
                         QPointF(center.x() + 12, center.y() - 31))
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 190))
        painter.drawEllipse(QPointF(center.x() - 10, center.y() - 42), 3.4, 3.4)

        font = QFont(painter.font())
        font.setPointSizeF(12.0)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(self.colors.text))
        painter.drawText(QRectF(rect.x(), center.y(), rect.width(), 26),
                         Qt.AlignmentFlag.AlignCenter, self._placeholder)

        font.setPointSizeF(9.0)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(self.colors.faint))
        painter.drawText(QRectF(rect.x(), center.y() + 26, rect.width(), 22),
                         Qt.AlignmentFlag.AlignCenter, self._placeholder_hint)


def _checkerboard(size: int = 12) -> QPixmap:
    """Transparency checkerboard tile."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(QColor("#191B22"))
    painter = QPainter(pixmap)
    painter.fillRect(QRect(0, 0, size, size), QColor("#20222B"))
    painter.fillRect(QRect(size, size, size, size), QColor("#20222B"))
    painter.end()
    return pixmap
