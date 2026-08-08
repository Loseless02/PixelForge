"""Background threads.

Qt widgets are not thread-safe, so workers only ever emit plain data or
``QImage`` (which is safe to build off the GUI thread). Conversion to
``QPixmap`` happens in the receiving slot.
"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThread, Signal
from PySide6.QtGui import QImage, QPixmap

from ..core import imageio, pipeline
from ..core.backends.base import Cancelled
from ..core.models import EditSettings, Job, JobStatus


def pil_to_qimage(image: Image.Image) -> QImage:
    """Copy a Pillow image into a standalone QImage."""
    if image.mode == "RGBA":
        data = image.tobytes("raw", "RGBA")
        fmt = QImage.Format.Format_RGBA8888
        stride = image.width * 4
    else:
        rgb = image if image.mode == "RGB" else image.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        fmt = QImage.Format.Format_RGB888
        stride = rgb.width * 3
    # copy() detaches from the temporary bytes object.
    return QImage(data, image.width, image.height, stride, fmt).copy()


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    return QPixmap.fromImage(pil_to_qimage(image))


# --------------------------------------------------------------- image load
class LoadSignals(QObject):
    finished = Signal(int, object, object, str)   # token, LoadedImage, QImage thumb, error


class LoadTask(QRunnable):
    """Reads one file off the GUI thread and prepares a thumbnail."""

    def __init__(self, token: int, path: Path, thumb_edge: int = 96) -> None:
        super().__init__()
        self.signals = LoadSignals()
        self.token = token
        self.path = path
        self.thumb_edge = thumb_edge
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            loaded = imageio.load(self.path)
            thumb = loaded.image.copy()
            thumb.thumbnail((self.thumb_edge, self.thumb_edge), Image.Resampling.LANCZOS)
            self.signals.finished.emit(self.token, loaded, pil_to_qimage(thumb), "")
        except Exception as exc:
            self.signals.finished.emit(self.token, None, None, str(exc))


# ------------------------------------------------------------------ preview
class PreviewSignals(QObject):
    finished = Signal(int, object, object, str)   # token, before QImage, after QImage, err


class PreviewTask(QRunnable):
    """Renders the fast, AI-free preview for the canvas.

    Each request carries a token; the window ignores results whose token is no
    longer the newest, which is how rapid slider drags stay responsive.
    """

    def __init__(self, token: int, loaded: imageio.LoadedImage, settings: EditSettings,
                 max_edge: int = pipeline.PREVIEW_MAX_EDGE) -> None:
        super().__init__()
        self.signals = PreviewSignals()
        self.token = token
        self.loaded = loaded
        self.settings = settings
        self.max_edge = max_edge
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            after = pipeline.render_preview(self.loaded, self.settings, self.max_edge)
            before = pipeline.apply_geometry_stage(self.loaded.image, self.settings)
            before = before.resize(after.size, Image.Resampling.LANCZOS)
            self.signals.finished.emit(
                self.token, pil_to_qimage(before), pil_to_qimage(after), ""
            )
        except Exception as exc:
            self.signals.finished.emit(self.token, None, None, str(exc))


# -------------------------------------------------------------- batch runner
class BatchWorker(QThread):
    """Runs queued jobs one after another on a single background thread."""

    job_started = Signal(int)
    job_progress = Signal(int, float, str)
    job_finished = Signal(int, bool, str)         # index, ok, message
    preview_ready = Signal(int, object)           # index, QImage of the result
    all_finished = Signal(int, int)               # succeeded, failed

    def __init__(
        self,
        jobs: list[Job],
        indices: list[int],
        out_dir: Path | None,
        *,
        tile_size: int = 0,
        gpu_id: int = 0,
        use_gpu: bool = True,
        preview_edge: int = 1600,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.jobs = jobs
        self.indices = indices
        self.out_dir = out_dir
        self.tile_size = tile_size
        self.gpu_id = gpu_id
        self.use_gpu = use_gpu
        self.preview_edge = preview_edge
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        succeeded = failed = 0
        for index in self.indices:
            if self.cancel_event.is_set():
                break
            job = self.jobs[index]
            job.status = JobStatus.RUNNING
            job.progress = 0.0
            job.message = ""
            self.job_started.emit(index)

            def progress(fraction: float, note: str, _i: int = index) -> None:
                self.jobs[_i].progress = fraction
                self.job_progress.emit(_i, fraction, note)

            try:
                result = pipeline.run_job(
                    job,
                    self.out_dir,
                    tile_size=self.tile_size,
                    gpu_id=self.gpu_id,
                    use_gpu=self.use_gpu,
                    progress=progress,
                    cancel=self.cancel_event,
                )
            except Cancelled:
                job.status = JobStatus.CANCELLED
                job.message = "Cancelled"
                self.job_finished.emit(index, False, "Cancelled")
                break
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.message = str(exc) or exc.__class__.__name__
                traceback.print_exc()
                failed += 1
                self.job_finished.emit(index, False, job.message)
                continue

            succeeded += 1
            if result.image is not None:
                thumb = result.image
                if max(thumb.size) > self.preview_edge:
                    thumb = thumb.copy()
                    thumb.thumbnail((self.preview_edge, self.preview_edge),
                                    Image.Resampling.LANCZOS)
                self.preview_ready.emit(index, pil_to_qimage(thumb))
            self.job_finished.emit(index, True, job.message)

        self.all_finished.emit(succeeded, failed)


class ProbeWorker(QThread):
    """One-shot GPU enumeration so startup never blocks on Vulkan init."""

    finished_probe = Signal(tuple)

    def run(self) -> None:
        from ..core.backends import BACKENDS

        backend = BACKENDS.get("realesrgan")
        devices: tuple[str, ...] = ()
        if backend is not None and backend.is_available():
            try:
                devices = backend.probe_devices()
            except Exception:
                devices = ()
        self.finished_probe.emit(devices)
