"""Main window: layout, wiring and application state."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizeGrip,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..config import AppSettings
from ..core import imageio, pipeline
from ..core.models import EditSettings, Job, JobStatus
from . import icons, theme
from .widgets.canvas import CanvasColors, PreviewCanvas
from .widgets.controls import IconButton, Spinner, badge
from .widgets.queue_panel import QueuePanel, placeholder_thumb
from .widgets.settings_panel import SettingsPanel
from .widgets.titlebar import TitleBar
from .widgets.toast import ToastHost
from .workers import BatchWorker, LoadTask, PreviewTask, ProbeWorker

_RESIZE_MARGIN = 6


class MainWindow(QWidget):
    """Frameless shell holding the queue, the canvas and the inspector."""

    def __init__(self, app_settings: AppSettings) -> None:
        super().__init__()
        self.app_settings = app_settings
        self.settings = EditSettings()
        self.settings.model = app_settings.default_model
        self.settings.export.format = app_settings.default_format
        self.settings.export.suffix = app_settings.output_suffix
        self.settings.export.jpeg_quality = app_settings.jpeg_quality
        self.settings.export.webp_quality = app_settings.webp_quality
        self.settings.export.keep_metadata = app_settings.keep_metadata
        self.settings.export.overwrite_policy = app_settings.overwrite_policy

        self.palette_tokens = theme.palette_for(app_settings.theme, app_settings.accent)
        self._loaded: imageio.LoadedImage | None = None
        self._loaded_index = -1
        self._load_token = 0
        self._preview_token = 0
        self._worker: BatchWorker | None = None
        self._pool = QThreadPool.globalInstance()

        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.resize(1480, 920)
        self.setMinimumSize(1120, 680)

        self._build_ui()
        self._build_shortcuts()
        self.apply_theme()

        self.toasts = ToastHost(self)
        self.toasts.accent = self.palette_tokens.accent

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(140)
        self._preview_timer.timeout.connect(self._render_preview)

        self._probe = ProbeWorker(self)
        self._probe.finished_probe.connect(self._on_devices)
        self._probe.start()

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def shutdown(self) -> None:
        """Stop every background thread. Qt aborts if one outlives the process."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        if self._probe.isRunning():
            self._probe.wait(8000)
        self._pool.clear()
        self._pool.waitForDone(5000)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.root = QWidget(self)
        self.root.setObjectName("Root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.root)

        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar(__app_name__, f"v{__version__}   ·   offline")
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_maximized)
        self.title_bar.close_requested.connect(self.close)
        self._build_title_actions()
        root_layout.addWidget(self.title_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.splitter, 1)

        self.splitter.addWidget(self._build_left())
        self.splitter.addWidget(self._build_center())
        self.splitter.addWidget(self._build_right())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([300, 680, 460])

        root_layout.addWidget(self._build_status_bar())

    def _build_title_actions(self) -> None:
        self.btn_open = QPushButton("  Open")
        self.btn_open.setObjectName("Ghost")
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.clicked.connect(self.open_files)

        self.btn_folder = QPushButton("  Folder")
        self.btn_folder.setObjectName("Ghost")
        self.btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_folder.clicked.connect(self.open_folder)

        self.title_bar.slot.addWidget(self.btn_open)
        self.title_bar.slot.addWidget(self.btn_folder)

        self.btn_theme = IconButton("moon", "Toggle light / dark theme")
        self.btn_theme.clicked.connect(self._toggle_theme)
        self.btn_accent = IconButton("sparkle", "Accent colour")
        self.btn_accent.clicked.connect(self._show_accent_menu)
        self.title_bar.trailing.addWidget(self.btn_accent)
        self.title_bar.trailing.addWidget(self.btn_theme)

    def _build_left(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(250)
        panel.setMaximumWidth(460)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 6, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("QUEUE")
        title.setObjectName("SectionTitle")
        self.queue_count = badge("0")
        header.addWidget(title)
        header.addWidget(self.queue_count)
        header.addStretch(1)

        self.btn_add = IconButton("add", "Add images (Ctrl+O)")
        self.btn_add.clicked.connect(self.open_files)
        self.btn_add_folder = IconButton("folder", "Add a folder (Ctrl+Shift+O)")
        self.btn_add_folder.clicked.connect(self.open_folder)
        self.btn_remove = IconButton("trash", "Remove selected (Del)")
        self.btn_remove.clicked.connect(self.remove_current)
        for button in (self.btn_add, self.btn_add_folder, self.btn_remove):
            header.addWidget(button)
        layout.addLayout(header)

        self.queue = QueuePanel()
        self.queue.selection_changed.connect(self._on_queue_selection)
        self.queue.files_dropped.connect(self.add_paths)
        self.queue.remove_requested.connect(lambda _: self.remove_current())
        self.queue.reveal_requested.connect(self._reveal_output)
        layout.addWidget(self.queue, 1)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.btn_clear_done = QPushButton("Clear finished")
        self.btn_clear_done.setObjectName("Ghost")
        self.btn_clear_done.clicked.connect(self._clear_finished)
        self.btn_clear_all = QPushButton("Clear all")
        self.btn_clear_all.setObjectName("Ghost")
        self.btn_clear_all.clicked.connect(self._clear_all)
        footer.addWidget(self.btn_clear_done)
        footer.addWidget(self.btn_clear_all)
        footer.addStretch(1)
        layout.addLayout(footer)
        return panel

    def _build_center(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(8)

        bar = QWidget()
        bar.setObjectName("CardFlat")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 6, 8, 6)
        bar_layout.setSpacing(6)

        self.btn_zoom_out = IconButton("zoom_out", "Zoom out (Ctrl+-)")
        self.btn_zoom_in = IconButton("zoom_in", "Zoom in (Ctrl++)")
        self.btn_fit = IconButton("fit", "Fit to window (Ctrl+0)")
        self.btn_actual = QPushButton("100%")
        self.btn_actual.setObjectName("Ghost")
        self.btn_actual.setToolTip("Zoom to 100% (Ctrl+1)")
        self.zoom_label = QLabel("Fit")
        self.zoom_label.setObjectName("Mono")
        self.zoom_label.setMinimumWidth(52)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_zoom_out.clicked.connect(lambda: self._zoom_by(1 / 1.25))
        self.btn_zoom_in.clicked.connect(lambda: self._zoom_by(1.25))
        self.btn_fit.clicked.connect(lambda: self.canvas.fit_to_window())
        self.btn_actual.clicked.connect(lambda: self.canvas.zoom_to_actual())

        self.btn_split = IconButton("compare", "Before / after split (B)", checkable=True)
        self.btn_split.toggled.connect(self._toggle_split)
        self.btn_crop = IconButton("crop", "Crop tool (C)", checkable=True)
        self.btn_crop.toggled.connect(self._toggle_crop)

        for widget in (self.btn_zoom_out, self.zoom_label, self.btn_zoom_in,
                       self.btn_fit, self.btn_actual):
            bar_layout.addWidget(widget)
        bar_layout.addStretch(1)
        self.canvas_info = QLabel("")
        self.canvas_info.setObjectName("Mono")
        bar_layout.addWidget(self.canvas_info)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self.btn_crop)
        bar_layout.addWidget(self.btn_split)
        layout.addWidget(bar)

        self.canvas = PreviewCanvas()
        self.canvas.files_dropped.connect(self.add_paths)
        self.canvas.crop_changed.connect(self._on_crop_changed)
        self.canvas.zoom_changed.connect(self._on_zoom_changed)
        self.canvas.request_open.connect(self.open_files)
        layout.addWidget(self.canvas, 1)
        return panel

    def _build_right(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(452)
        panel.setMaximumWidth(620)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 12, 12, 12)
        layout.setSpacing(10)

        self.inspector = SettingsPanel(self.settings)
        self.inspector.changed.connect(self._on_settings_changed)
        self.inspector.crop_mode_requested.connect(self._toggle_crop)
        self.inspector.crop_ratio_changed.connect(self.canvas_set_crop_ratio)
        self.inspector.crop_reset_requested.connect(self._reset_crop)
        self.inspector.apply_to_all_requested.connect(self._apply_settings_to_all)
        layout.addWidget(self.inspector, 1)

        actions = QWidget()
        actions.setObjectName("CardFlat")
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(12, 12, 12, 12)
        actions_layout.setSpacing(8)

        self.btn_run = QPushButton("  Upscale selected")
        self.btn_run.setObjectName("Primary")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.clicked.connect(self.run_current)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_run_all = QPushButton("Run whole queue")
        self.btn_run_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_all.clicked.connect(self.run_all)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("Danger")
        self.btn_cancel.clicked.connect(self.cancel_run)
        self.btn_cancel.setEnabled(False)
        row.addWidget(self.btn_run_all, 1)
        row.addWidget(self.btn_cancel, 0)

        actions_layout.addWidget(self.btn_run)
        actions_layout.addLayout(row)
        layout.addWidget(actions)
        return panel

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(38)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(10)

        self.spinner = Spinner(15)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("Hint")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFixedWidth(200)
        self.progress.hide()

        self.backend_badge = badge("checking GPU…")

        layout.addWidget(self.spinner)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.backend_badge)

        self.grip = QSizeGrip(bar)
        self.grip.setFixedSize(16, 16)
        layout.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignBottom)
        return bar

    def _build_shortcuts(self) -> None:
        def add(sequence: str, slot) -> None:
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(slot)
            self.addAction(action)

        add("Ctrl+O", self.open_files)
        add("Ctrl+Shift+O", self.open_folder)
        add("Ctrl+Return", self.run_current)
        add("Ctrl+Shift+Return", self.run_all)
        add("Escape", self._escape)
        add("Delete", self.remove_current)
        add("Ctrl+0", lambda: self.canvas.fit_to_window())
        add("Ctrl+1", lambda: self.canvas.zoom_to_actual())
        add("Ctrl++", lambda: self._zoom_by(1.25))
        add("Ctrl+=", lambda: self._zoom_by(1.25))
        add("Ctrl+-", lambda: self._zoom_by(1 / 1.25))
        add("C", lambda: self.btn_crop.setChecked(not self.btn_crop.isChecked()))
        add("B", lambda: self.btn_split.setChecked(not self.btn_split.isChecked()))
        add("F11", self._toggle_maximized)
        add("Ctrl+Shift+T", self._toggle_theme)

    # --------------------------------------------------------------- theme
    def apply_theme(self) -> None:
        palette = self.palette_tokens
        assets = icons.write_stylesheet_assets(palette)
        self.setStyleSheet(theme.build_stylesheet(palette, assets))

        self.title_bar.apply_color(palette.text_dim)
        self.btn_open.setIcon(icons.icon("add", palette.text_dim, 15))
        self.btn_folder.setIcon(icons.icon("folder", palette.text_dim, 15))
        self.btn_run.setIcon(icons.icon("sparkle", palette.accent_text, 16))
        self.btn_theme._name = "sun" if palette.name == "dark" else "moon"
        for button in (self.btn_theme, self.btn_accent, self.btn_add, self.btn_add_folder,
                       self.btn_remove, self.btn_zoom_in, self.btn_zoom_out, self.btn_fit,
                       self.btn_split, self.btn_crop):
            button.apply_color(palette.text_dim)
        self.inspector.apply_color(palette)
        self.spinner.set_color(palette.accent)

        self.canvas.set_colors(
            CanvasColors(
                canvas=palette.canvas,
                text=palette.text,
                dim=palette.text_dim,
                faint=palette.text_faint,
                accent=palette.accent,
                surface=palette.surface,
                border=palette.border_strong,
            )
        )
        if hasattr(self, "toasts"):
            self.toasts.accent = palette.accent

    def _toggle_theme(self) -> None:
        name = "light" if self.palette_tokens.name == "dark" else "dark"
        self.app_settings.theme = name
        self.palette_tokens = theme.palette_for(name, self.app_settings.accent)
        self.apply_theme()
        self.app_settings.save()

    def _show_accent_menu(self) -> None:
        menu = QMenu(self)
        for label, color in theme.ACCENT_SWATCHES:
            action = menu.addAction(label)
            action.setIcon(QIcon(_swatch(color)))
            action.triggered.connect(lambda _=False, c=color: self._set_accent(c))
        menu.exec(self.btn_accent.mapToGlobal(QPoint(0, self.btn_accent.height() + 4)))

    def _set_accent(self, color: str) -> None:
        self.app_settings.accent = color
        self.palette_tokens = theme.palette_for(self.app_settings.theme, color)
        self.apply_theme()
        self.app_settings.save()

    # ---------------------------------------------------------- file input
    def open_files(self) -> None:
        start = self.app_settings.last_input_dir or str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add images", start, imageio.file_filter()
        )
        if paths:
            self.app_settings.last_input_dir = str(Path(paths[0]).parent)
            self.add_paths(paths)

    def open_folder(self) -> None:
        start = self.app_settings.last_input_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Add every image in a folder",
                                                  start)
        if not folder:
            return
        self.app_settings.last_input_dir = folder
        paths = sorted(
            str(p) for p in Path(folder).iterdir()
            if p.is_file() and imageio.is_supported(p)
        )
        if not paths:
            self.toasts.show("No supported images in that folder.", "warn")
            return
        self.add_paths(paths)

    def add_paths(self, paths: list[str]) -> None:
        """Accept files and folders, skipping anything unreadable."""
        collected: list[Path] = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                collected += sorted(
                    p for p in path.rglob("*") if p.is_file() and imageio.is_supported(p)
                )
            elif path.is_file() and imageio.is_supported(path):
                collected.append(path)

        existing = {job.source for job in self.queue.jobs}
        fresh = [p for p in collected if p not in existing]
        rejected = len(paths) - len(collected) if len(paths) >= len(collected) else 0

        if not fresh:
            message = "Those files are already queued." if collected else \
                "No supported image files found."
            self.toasts.show(message, "warn")
            return

        first_index = len(self.queue.jobs)
        jobs = [Job(source=path, settings=self.settings.copy()) for path in fresh]
        self.queue.add_jobs(jobs)
        for offset in range(len(jobs)):
            self.queue.set_thumbnail(first_index + offset, placeholder_thumb())
            self._request_thumbnail(first_index + offset)

        self.queue_count.setText(str(len(self.queue.jobs)))
        self.app_settings.push_recent(str(fresh[0]))
        if self.queue.current_index() < 0:
            self.queue.list.setCurrentRow(0)
        elif first_index == 0:
            self._on_queue_selection(0)

        note = f"Added {len(fresh)} image{'s' if len(fresh) != 1 else ''}."
        if rejected:
            note += f" Skipped {rejected} unsupported."
        self.toasts.show(note, "ok")

    def remove_current(self) -> None:
        if self.queue.current_index() < 0:
            return
        self.queue.remove_current()
        self.queue_count.setText(str(len(self.queue.jobs)))
        if not self.queue.jobs:
            self._loaded = None
            self._loaded_index = -1
            self.canvas.clear()
            self.canvas_info.clear()
            self.status_label.setText("Ready")

    def _reveal_output(self, index: int) -> None:
        if not 0 <= index < len(self.queue.jobs):
            return
        job = self.queue.jobs[index]
        target = job.output if job.output and job.output.exists() else job.source
        open_in_explorer(target)

    def _clear_finished(self) -> None:
        self.queue.clear_finished()
        self.queue_count.setText(str(len(self.queue.jobs)))
        if not self.queue.jobs:
            self.canvas.clear()

    def _clear_all(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.toasts.show("Stop the current run first.", "warn")
            return
        self.queue.clear()
        self.queue_count.setText("0")
        self._loaded = None
        self._loaded_index = -1
        self.canvas.clear()
        self.canvas_info.clear()

    # -------------------------------------------------------------- loading
    def _request_thumbnail(self, index: int) -> None:
        job = self.queue.jobs[index]
        task = LoadTask(index, job.source, thumb_edge=92)
        task.signals.finished.connect(self._on_thumbnail_ready)
        self._pool.start(task)

    def _on_thumbnail_ready(self, index: int, loaded, thumb, error: str) -> None:
        if error or thumb is None or index >= len(self.queue.jobs):
            return
        job = self.queue.jobs[index]
        job.source_size = loaded.size
        self.queue.set_thumbnail(index, QPixmap.fromImage(thumb))
        self.queue.refresh(index)

    def _on_queue_selection(self, index: int) -> None:
        if index < 0 or index >= len(self.queue.jobs):
            return
        job = self.queue.jobs[index]
        self._loaded_index = index
        self.inspector.load(job.settings)
        self.settings = job.settings

        self._load_token += 1
        token = self._load_token
        self.status_label.setText(f"Loading {job.name}…")
        self.spinner.start()

        task = LoadTask(token, job.source)
        task.signals.finished.connect(self._on_image_loaded)
        self._pool.start(task)

    def _on_image_loaded(self, token: int, loaded, thumb, error: str) -> None:
        if token != self._load_token:
            return
        self.spinner.stop()
        if error or loaded is None:
            self.status_label.setText(f"Could not open the file: {error}")
            self.toasts.show(f"Could not open the file: {error}", "err")
            return

        self._loaded = loaded
        width, height = loaded.size
        self.inspector.set_source_size(width, height)
        self.canvas.set_images(None, None, QSize(width, height))
        if self.settings.crop.is_empty:
            self.canvas.set_crop(self.settings.crop)
        else:
            self.canvas.set_crop(self.settings.crop)
        self.canvas_info.setText(f"{loaded.path.name}   ·   {width} x {height}")
        self.status_label.setText(f"{loaded.path.name} loaded")
        self._schedule_preview(immediate=True)

    # -------------------------------------------------------------- preview
    def _schedule_preview(self, immediate: bool = False) -> None:
        if self._loaded is None:
            return
        self._preview_timer.start(0 if immediate else 140)

    def _render_preview(self) -> None:
        if self._loaded is None:
            return
        self._preview_token += 1
        task = PreviewTask(self._preview_token, self._loaded, self.settings.copy())
        task.signals.finished.connect(self._on_preview_ready)
        self._pool.start(task)
        self._update_plan_text()

    def _on_preview_ready(self, token: int, before, after, error: str) -> None:
        if token != self._preview_token:
            return
        if error or after is None:
            self.status_label.setText(f"Preview failed: {error}")
            return
        self.canvas.set_images(
            QPixmap.fromImage(before), QPixmap.fromImage(after),
            QSize(*self._loaded.size) if self._loaded else None,
        )

    def _update_plan_text(self) -> None:
        if self._loaded is None:
            return
        width, height = self._loaded.size
        text = pipeline.plan_summary(width, height, self.settings)
        self.inspector.set_plan_text(text)
        self.status_label.setText(text)

    def _on_settings_changed(self) -> None:
        self._schedule_preview()

    def _apply_settings_to_all(self) -> None:
        if not self.queue.jobs:
            return
        current = self.queue.current_index()
        for index, job in enumerate(self.queue.jobs):
            if index != current:
                job.settings = self.settings.copy()
                job.settings.crop = job.settings.crop.__class__()  # crop is per-image
        self.toasts.show(f"Applied to {len(self.queue.jobs)} files.", "ok")

    # ----------------------------------------------------------------- crop
    def _toggle_crop(self, enabled: bool) -> None:
        if self.btn_crop.isChecked() != enabled:
            self.btn_crop.blockSignals(True)
            self.btn_crop.setChecked(enabled)
            self.btn_crop.blockSignals(False)
        self.inspector.crop_button_set_checked(enabled)
        if enabled and self.btn_split.isChecked():
            self.btn_split.setChecked(False)
        self.canvas.set_crop_mode(enabled)
        self.status_label.setText(
            "Crop: drag inside the image, Enter or C to finish."
            if enabled else "Ready"
        )

    def canvas_set_crop_ratio(self, ratio) -> None:
        self.canvas.set_crop_ratio(ratio)

    def _reset_crop(self) -> None:
        self.canvas.reset_crop()

    def _on_crop_changed(self, crop) -> None:
        self.inspector.set_crop(crop)

    # ----------------------------------------------------------------- zoom
    def _zoom_by(self, factor: float) -> None:
        self.canvas.set_zoom(self.canvas.effective_zoom() * factor)

    def _on_zoom_changed(self, value: float) -> None:
        self.zoom_label.setText("Fit" if self.canvas.is_fit() else f"{value * 100:.0f}%")

    def _toggle_split(self, enabled: bool) -> None:
        if enabled and self.btn_crop.isChecked():
            self.btn_crop.setChecked(False)
        self.canvas.set_split_enabled(enabled)

    def _escape(self) -> None:
        if self.btn_crop.isChecked():
            self.btn_crop.setChecked(False)
        elif self._worker is not None and self._worker.isRunning():
            self.cancel_run()

    # ------------------------------------------------------------ rendering
    def run_current(self) -> None:
        index = self.queue.current_index()
        if index < 0:
            self.toasts.show("Nothing selected.", "warn")
            return
        self._start_run([index])

    def run_all(self) -> None:
        indices = [
            i for i, job in enumerate(self.queue.jobs)
            if job.status in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        if not indices:
            self.toasts.show("Every queued file is already done.", "warn")
            return
        self._start_run(indices)

    def _start_run(self, indices: list[int]) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.toasts.show("A run is already in progress.", "warn")
            return
        if not self.queue.jobs:
            self.toasts.show("Add some images first.", "warn")
            return

        use_gpu, gpu_id, tile = self.inspector.gpu_settings()
        out_dir = self.inspector.output_dir
        self.app_settings.gpu_id = gpu_id
        self.app_settings.use_gpu = use_gpu

        self._worker = BatchWorker(
            self.queue.jobs, indices, out_dir,
            tile_size=tile, gpu_id=gpu_id, use_gpu=use_gpu, parent=self,
        )
        self._worker.job_started.connect(self._on_job_started)
        self._worker.job_progress.connect(self._on_job_progress)
        self._worker.job_finished.connect(self._on_job_finished)
        self._worker.preview_ready.connect(self._on_result_preview)
        self._worker.all_finished.connect(self._on_run_finished)

        self._set_running(True)
        self.progress.setValue(0)
        self.progress.show()
        self._worker.start()

    def cancel_run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.status_label.setText("Cancelling…")

    def _set_running(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
        self.btn_run_all.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.inspector.setEnabled(not running)
        if running:
            self.spinner.start()
        else:
            self.spinner.stop()

    def _on_job_started(self, index: int) -> None:
        self.queue.refresh(index)
        self.status_label.setText(f"Upscaling {self.queue.jobs[index].name}…")

    def _on_job_progress(self, index: int, fraction: float, note: str) -> None:
        row = self.queue.row(index)
        if row is not None:
            row.progress.setValue(int(fraction * 1000))
        self.progress.setValue(int(fraction * 1000))
        if note:
            self.status_label.setText(f"{self.queue.jobs[index].name} — {note}")

    def _on_job_finished(self, index: int, ok: bool, message: str) -> None:
        self.queue.refresh(index)
        if not ok and message and message != "Cancelled":
            self.toasts.show(f"{self.queue.jobs[index].name}: {message}", "err", 6000)

    def _on_result_preview(self, index: int, image) -> None:
        if index != self.queue.current_index():
            return
        pixmap = QPixmap.fromImage(image)
        self.canvas.set_images(self.canvas.before_pixmap(), pixmap)

    def _on_run_finished(self, succeeded: int, failed: int) -> None:
        self._set_running(False)
        self.progress.hide()
        self.queue.refresh()
        if failed and succeeded:
            self.toasts.show(f"{succeeded} done, {failed} failed.", "warn", 5000)
        elif failed:
            self.toasts.show(f"{failed} file(s) failed.", "err", 5000)
        elif succeeded:
            job = next((j for j in reversed(self.queue.jobs) if j.output), None)
            self.toasts.show(f"{succeeded} file(s) written.", "ok")
            if job is not None and job.output is not None:
                self.status_label.setText(f"Saved to {job.output.parent}")
                self._last_output_dir = job.output.parent
        else:
            self.status_label.setText("Run cancelled")
        self.app_settings.save()

    def _on_devices(self, devices: tuple) -> None:
        self.inspector.set_devices(devices, self.app_settings.gpu_id)
        if devices:
            self.backend_badge.setText(f"GPU · {devices[0].replace('(R)', '')[:28]}")
            self.backend_badge.setObjectName("BadgeOk")
        else:
            self.backend_badge.setText("CPU only")
            self.backend_badge.setObjectName("BadgeWarn")
        self.backend_badge.style().unpolish(self.backend_badge)
        self.backend_badge.style().polish(self.backend_badge)

    # -------------------------------------------------------- window chrome
    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            maximized = self.isMaximized()
            self.title_bar.set_maximized(maximized)
            self.root.setObjectName("RootMaximized" if maximized else "Root")
            self.grip.setVisible(not maximized)
            self.root.style().unpolish(self.root)
            self.root.style().polish(self.root)
        super().changeEvent(event)

    def _edges_at(self, position: QPoint) -> Qt.Edge | None:
        if self.isMaximized():
            return None
        rect = self.rect()
        edges = Qt.Edge(0)
        if position.x() <= _RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        if position.x() >= rect.width() - _RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if position.y() <= _RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        if position.y() >= rect.height() - _RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges or None

    def mouseMoveEvent(self, event) -> None:
        edges = self._edges_at(event.position().toPoint())
        cursors = {
            Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(edges, Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            answer = QMessageBox.question(
                self, "Stop the run?",
                "Images are still being processed. Close anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer is not QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.cancel()
            self._worker.wait(4000)
        self.shutdown()
        self.app_settings.save()
        super().closeEvent(event)


def _swatch(color: str, size: int = 14) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    from PySide6.QtGui import QColor, QPainter

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return pixmap


def open_in_explorer(path: Path) -> None:
    """Reveal a file in the system file manager."""
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=False)
    except OSError:
        pass
