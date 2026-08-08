"""Batch queue: the list of files waiting to be rendered."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Job, JobStatus
from .. import icons

_STATUS_TEXT = {
    JobStatus.PENDING: "Queued",
    JobStatus.RUNNING: "Working",
    JobStatus.DONE: "Done",
    JobStatus.FAILED: "Failed",
    JobStatus.CANCELLED: "Cancelled",
}


class JobRow(QWidget):
    """One queue entry: thumbnail, name, size line, progress."""

    def __init__(self, job: Job, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.job = job

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 9, 12, 9)
        root.setSpacing(11)

        self.thumb = QLabel()
        self.thumb.setFixedSize(46, 46)
        self.thumb.setScaledContents(False)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.thumb, 0)

        column = QVBoxLayout()
        column.setSpacing(3)
        column.setContentsMargins(0, 0, 0, 0)

        self.name = QLabel(job.name)
        self.name.setStyleSheet("font-weight: 600;")
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        self.detail = QLabel("")
        self.detail.setObjectName("Hint")

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.hide()

        column.addWidget(self.name)
        column.addWidget(self.detail)
        column.addWidget(self.progress)
        root.addLayout(column, 1)

        self.status = QLabel("")
        self.status.setObjectName("Badge")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setFixedHeight(20)
        root.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)

        self.refresh()

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumb.setPixmap(_rounded(pixmap, 46, 8))

    def refresh(self) -> None:
        job = self.job
        parts: list[str] = []
        if job.source_size:
            parts.append(f"{job.source_size[0]}x{job.source_size[1]}")
        if job.result_size:
            parts.append(f"to {job.result_size[0]}x{job.result_size[1]}")
        if job.elapsed:
            parts.append(f"{job.elapsed:.1f}s")
        detail = "  ·  ".join(parts) if parts else job.source.parent.name
        if job.status is JobStatus.FAILED and job.message:
            detail = job.message[:90]
        self.detail.setText(detail)
        self.detail.setToolTip(job.message or str(job.source))

        self.status.setText(_STATUS_TEXT.get(job.status, ""))
        self.status.setObjectName(
            {
                JobStatus.DONE: "BadgeOk",
                JobStatus.FAILED: "BadgeErr",
                JobStatus.CANCELLED: "BadgeWarn",
            }.get(job.status, "Badge")
        )
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

        running = job.status is JobStatus.RUNNING
        self.progress.setVisible(running)
        if running:
            self.progress.setValue(int(job.progress * 1000))

        self.setToolTip(str(job.source))


class QueuePanel(QWidget):
    """Owns the job list and keeps row widgets in sync with the model."""

    selection_changed = Signal(int)
    files_dropped = Signal(list)
    remove_requested = Signal(int)
    reveal_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.jobs: list[Job] = []
        self._rows: list[JobRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setUniformItemSizes(False)
        self.list.setSpacing(0)
        self.list.currentRowChanged.connect(self.selection_changed.emit)
        self.list.itemDoubleClicked.connect(
            lambda item: self.reveal_requested.emit(self.list.row(item))
        )
        root.addWidget(self.list, 1)

        self.empty = QLabel("No images queued.\nDrop files anywhere in the window.")
        self.empty.setObjectName("Hint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty, 1)
        self._sync_empty()

    # ----------------------------------------------------------- mutation
    def add_jobs(self, jobs: list[Job]) -> None:
        for job in jobs:
            self.jobs.append(job)
            row = JobRow(job)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, row.sizeHint().height() + 6))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self._rows.append(row)
        self._sync_empty()
        if self.list.currentRow() < 0 and self.jobs:
            self.list.setCurrentRow(0)

    def remove_current(self) -> int:
        index = self.list.currentRow()
        if index < 0:
            return -1
        self.list.takeItem(index)
        del self.jobs[index]
        del self._rows[index]
        self._sync_empty()
        return index

    def clear(self) -> None:
        self.list.clear()
        self.jobs.clear()
        self._rows.clear()
        self._sync_empty()

    def clear_finished(self) -> None:
        for index in range(len(self.jobs) - 1, -1, -1):
            if self.jobs[index].status in (JobStatus.DONE, JobStatus.CANCELLED):
                self.list.takeItem(index)
                del self.jobs[index]
                del self._rows[index]
        self._sync_empty()

    # ------------------------------------------------------------- access
    def current_index(self) -> int:
        return self.list.currentRow()

    def current_job(self) -> Job | None:
        index = self.list.currentRow()
        return self.jobs[index] if 0 <= index < len(self.jobs) else None

    def row(self, index: int) -> JobRow | None:
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def refresh(self, index: int | None = None) -> None:
        rows = self._rows if index is None else [self._rows[index]]
        for row in rows:
            row.refresh()

    def set_thumbnail(self, index: int, pixmap: QPixmap) -> None:
        row = self.row(index)
        if row is not None:
            row.set_thumbnail(pixmap)

    def _sync_empty(self) -> None:
        has_jobs = bool(self.jobs)
        self.list.setVisible(has_jobs)
        self.empty.setVisible(not has_jobs)

    # --------------------------------------------------------------- drag
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

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete and self.list.currentRow() >= 0:
            self.remove_requested.emit(self.list.currentRow())
            event.accept()
            return
        super().keyPressEvent(event)


def _rounded(pixmap: QPixmap, size: int, radius: int) -> QPixmap:
    """Centre-crop to a square and round the corners."""
    if pixmap.isNull():
        return pixmap
    scaled = pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - size) // 2)
    y = max(0, (scaled.height() - size) // 2)
    scaled = scaled.copy(x, y, size, size)

    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor(0, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, size, size, radius, radius)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return result


def placeholder_thumb(size: int = 46) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#1C1F29"))
    painter = QPainter(pixmap)
    painter.drawPixmap(
        (size - 20) // 2, (size - 20) // 2, icons.pixmap("image", "#646E85", 20)
    )
    painter.end()
    return _rounded(pixmap, size, 8)
