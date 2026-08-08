"""Right-hand inspector: every knob that feeds an ``EditSettings``."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import imageio
from ...core.backends import BACKENDS, available_backends
from ...core.backends.classic import RESAMPLER_LABELS
from ...core.models import (
    Adjustments,
    CropRect,
    EditSettings,
    FitMode,
    Rotation,
    SizeMode,
)
from ...core.presets import ASPECT_RATIOS, LOOK_PRESETS, RESOLUTION_PRESETS
from .. import icons
from .controls import (
    Card,
    IconButton,
    LabeledToggle,
    SegmentedControl,
    SliderRow,
    divider,
    hint,
)

_SIZE_MODES = (SizeMode.SCALE, SizeMode.EXACT, SizeMode.LONG_EDGE, SizeMode.PERCENT)
_FIT_MODES = (
    (FitMode.COVER, "Cover — fill the box, crop the overflow"),
    (FitMode.CONTAIN, "Contain — fit inside, keep aspect"),
    (FitMode.PAD, "Pad — fit inside, letterbox to exact size"),
    (FitMode.STRETCH, "Stretch — exact size, distorts aspect"),
)


def _scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(14, 14, 16, 18)
    layout.setSpacing(12)
    area.setWidget(inner)
    return area, layout


class SettingsPanel(QWidget):
    """Edits a single ``EditSettings`` and announces every change."""

    changed = Signal()
    crop_mode_requested = Signal(bool)
    crop_ratio_changed = Signal(object)
    crop_reset_requested = Signal()
    apply_to_all_requested = Signal()

    def __init__(self, settings: EditSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._loading = False
        self._source_size = (0, 0)
        self.output_dir: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_size_tab(), "Size")
        self.tabs.addTab(self._build_enhance_tab(), "Enhance")
        self.tabs.addTab(self._build_adjust_tab(), "Adjust")
        self.tabs.addTab(self._build_export_tab(), "Export")

        # Long entries must not be allowed to widen the whole inspector.
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(8)
            combo.view().setTextElideMode(Qt.TextElideMode.ElideRight)

        self.load(settings)

    # =============================================================== SIZE
    def _build_size_tab(self) -> QWidget:
        page, layout = _scroll_page()

        card = Card("Target resolution")
        self.size_mode = SegmentedControl(["Scale", "Exact", "Long edge", "%"])
        self.size_mode.changed.connect(self._on_size_mode)
        card.add(self.size_mode)

        self.size_stack = QStackedWidget()
        self.size_stack.addWidget(self._build_scale_page())
        self.size_stack.addWidget(self._build_exact_page())
        self.size_stack.addWidget(self._build_long_edge_page())
        self.size_stack.addWidget(self._build_percent_page())
        card.add(self.size_stack)

        self.result_label = QLabel("—")
        self.result_label.setObjectName("Mono")
        self.result_label.setWordWrap(True)
        card.add(divider())
        card.add(self.result_label)
        layout.addWidget(card)

        # ------------------------------------------------------------ crop
        crop_card = Card("Crop and orientation")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.crop_toggle = QPushButton("  Crop")
        self.crop_toggle.setCheckable(True)
        self.crop_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.crop_toggle.toggled.connect(self.crop_mode_requested.emit)
        self.crop_reset = QPushButton("Reset")
        self.crop_reset.setObjectName("Ghost")
        self.crop_reset.clicked.connect(self.crop_reset_requested.emit)
        row.addWidget(self.crop_toggle, 1)
        row.addWidget(self.crop_reset, 0)
        crop_card.add_layout(row)

        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(8)
        ratio_label = QLabel("Ratio")
        ratio_label.setObjectName("Hint")
        self.crop_ratio = QComboBox()
        for label, _ in ASPECT_RATIOS:
            self.crop_ratio.addItem(label)
        self.crop_ratio.currentIndexChanged.connect(self._on_crop_ratio)
        ratio_row.addWidget(ratio_label, 0)
        ratio_row.addWidget(self.crop_ratio, 1)
        crop_card.add_layout(ratio_row)

        self.crop_info = QLabel("Full image")
        self.crop_info.setObjectName("Mono")
        crop_card.add(self.crop_info)

        crop_card.add(divider())
        transform_row = QHBoxLayout()
        transform_row.setSpacing(6)
        self.btn_rot_ccw = IconButton("rotate_ccw", "Rotate left (Ctrl+[)")
        self.btn_rot_cw = IconButton("rotate_cw", "Rotate right (Ctrl+])")
        self.btn_flip_h = IconButton("flip_h", "Flip horizontal", checkable=True)
        self.btn_flip_v = IconButton("flip_v", "Flip vertical", checkable=True)
        self.btn_rot_ccw.clicked.connect(lambda: self._rotate(-90))
        self.btn_rot_cw.clicked.connect(lambda: self._rotate(90))
        self.btn_flip_h.toggled.connect(lambda v: self._set("flip_h", v))
        self.btn_flip_v.toggled.connect(lambda v: self._set("flip_v", v))
        self.rotation_label = QLabel("0°")
        self.rotation_label.setObjectName("Hint")
        for widget in (self.btn_rot_ccw, self.btn_rot_cw, self.btn_flip_h, self.btn_flip_v):
            transform_row.addWidget(widget)
        transform_row.addWidget(self.rotation_label)
        transform_row.addStretch(1)
        crop_card.add_layout(transform_row)
        layout.addWidget(crop_card)

        layout.addStretch(1)
        return page

    def _build_scale_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)

        chips = QGridLayout()
        chips.setSpacing(6)
        self.scale_group = QButtonGroup(self)
        self.scale_group.setExclusive(True)
        for index, value in enumerate((1.5, 2.0, 3.0, 4.0, 6.0, 8.0)):
            button = QPushButton(f"x{value:g}")
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.scale_group.addButton(button, index)
            chips.addWidget(button, index // 3, index % 3)
            button.clicked.connect(lambda _=False, v=value: self.scale_slider.set_value(v))
        layout.addLayout(chips)

        self.scale_slider = SliderRow("Factor", 1.0, 8.0, 2.0, scale=10, decimals=2,
                                      suffix="x")
        self.scale_slider.valueChanged.connect(lambda v: self._set("scale", v))
        layout.addWidget(self.scale_slider)
        return widget

    def _build_exact_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        width_label = QLabel("Width")
        width_label.setObjectName("Hint")
        height_label = QLabel("Height")
        height_label.setObjectName("Hint")

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 32768)
        self.width_spin.setSuffix(" px")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 32768)
        self.height_spin.setSuffix(" px")
        self.width_spin.valueChanged.connect(lambda v: self._on_dimension("w", v))
        self.height_spin.valueChanged.connect(lambda v: self._on_dimension("h", v))

        self.lock_aspect = IconButton("lock", "Lock aspect ratio", checkable=True)
        self.lock_aspect.setChecked(True)
        self.lock_aspect.toggled.connect(self._on_lock)
        self.swap_button = IconButton("swap", "Swap width and height")
        self.swap_button.clicked.connect(self._swap_dimensions)

        grid.addWidget(width_label, 0, 0)
        grid.addWidget(height_label, 0, 1)
        grid.addWidget(self.width_spin, 1, 0)
        grid.addWidget(self.height_spin, 1, 1)
        grid.addWidget(self.lock_aspect, 1, 2)
        grid.addWidget(self.swap_button, 1, 3)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        preset_label = QLabel("Preset")
        preset_label.setObjectName("Hint")
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Custom", None)
        for preset in RESOLUTION_PRESETS:
            text = f"{preset.label}  ·  {preset.width}x{preset.height}"
            self.preset_combo.addItem(text, preset.key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        layout.addWidget(preset_label)
        layout.addWidget(self.preset_combo)

        fit_label = QLabel("Fit")
        fit_label.setObjectName("Hint")
        self.fit_combo = QComboBox()
        for mode, text in _FIT_MODES:
            self.fit_combo.addItem(text, mode.value)
        self.fit_combo.currentIndexChanged.connect(self._on_fit)
        layout.addWidget(fit_label)
        layout.addWidget(self.fit_combo)
        return widget

    def _build_long_edge_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)

        chips = QGridLayout()
        chips.setSpacing(6)
        for index, value in enumerate((1280, 1920, 2560, 3840, 5120, 7680)):
            button = QPushButton(str(value))
            button.setObjectName("Chip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, v=value: self.long_edge_spin.setValue(v))
            chips.addWidget(button, index // 3, index % 3)
        layout.addLayout(chips)

        row = QHBoxLayout()
        label = QLabel("Longest side")
        label.setObjectName("Hint")
        self.long_edge_spin = QSpinBox()
        self.long_edge_spin.setRange(16, 32768)
        self.long_edge_spin.setSuffix(" px")
        self.long_edge_spin.valueChanged.connect(lambda v: self._set("long_edge", v))
        row.addWidget(label, 1)
        row.addWidget(self.long_edge_spin, 0)
        layout.addLayout(row)
        layout.addWidget(hint("Aspect ratio is always preserved."))
        return widget

    def _build_percent_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)
        self.percent_slider = SliderRow("Size", 10.0, 800.0, 200.0, scale=1, decimals=0,
                                        suffix=" %")
        self.percent_slider.valueChanged.connect(lambda v: self._set("percent", v))
        layout.addWidget(self.percent_slider)
        return widget

    # ============================================================ ENHANCE
    def _build_enhance_tab(self) -> QWidget:
        page, layout = _scroll_page()

        card = Card("Upscaler")
        self._backend_keys = [b.key for b in available_backends()]
        labels = [BACKENDS[k].label for k in self._backend_keys]
        self.backend_seg = SegmentedControl(labels)
        self.backend_seg.changed.connect(self._on_backend)
        card.add(self.backend_seg)

        self.backend_hint = hint("")
        card.add(self.backend_hint)

        model_label = QLabel("Model")
        model_label.setObjectName("Hint")
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._on_model)
        card.add(model_label)
        card.add(self.model_combo)
        self.model_hint = hint("")
        card.add(self.model_hint)
        layout.addWidget(card)

        quality_card = Card("Resampling")
        resample_label = QLabel("Final resample")
        resample_label.setObjectName("Hint")
        self.resample_combo = QComboBox()
        for key, text in RESAMPLER_LABELS.items():
            self.resample_combo.addItem(text, key)
        self.resample_combo.currentIndexChanged.connect(
            lambda: self._set("resample", self.resample_combo.currentData())
        )
        quality_card.add(resample_label)
        quality_card.add(self.resample_combo)
        quality_card.add(
            hint("Used for the exact-size step after the AI pass, and for every "
                 "downscale.")
        )
        layout.addWidget(quality_card)

        device_card = Card("Compute")
        self.gpu_toggle = LabeledToggle("Use GPU", True,
                                        "Turn off to run on CPU. Much slower.")
        device_card.add(self.gpu_toggle)
        gpu_label = QLabel("Device")
        gpu_label.setObjectName("Hint")
        self.gpu_combo = QComboBox()
        self.gpu_combo.addItem("Detecting devices…", 0)
        device_card.add(gpu_label)
        device_card.add(self.gpu_combo)

        tile_label = QLabel("Tile size")
        tile_label.setObjectName("Hint")
        self.tile_combo = QComboBox()
        for text, value in (("Auto", 0), ("128 — low VRAM", 128), ("200", 200),
                            ("256", 256), ("400", 400), ("512", 512)):
            self.tile_combo.addItem(text, value)
        device_card.add(tile_label)
        device_card.add(self.tile_combo)
        device_card.add(hint("Smaller tiles use less video memory but run slower. "
                             "Drop this if a big image fails."))
        layout.addWidget(device_card)

        self.plan_card = Card("Plan")
        self.plan_label = QLabel("Load an image to see the plan.")
        self.plan_label.setObjectName("Mono")
        self.plan_label.setWordWrap(True)
        self.plan_card.add(self.plan_label)
        layout.addWidget(self.plan_card)

        layout.addStretch(1)
        return page

    # ============================================================= ADJUST
    def _build_adjust_tab(self) -> QWidget:
        page, layout = _scroll_page()

        look_card = Card("Look")
        looks = QGridLayout()
        looks.setSpacing(6)
        self.look_group = QButtonGroup(self)
        self.look_group.setExclusive(True)
        for index, preset in enumerate(LOOK_PRESETS):
            button = QPushButton(preset.label)
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.look_group.addButton(button, index)
            looks.addWidget(button, index // 3, index % 3)
            button.clicked.connect(lambda _=False, p=preset: self._apply_look(p))
        look_card.add_layout(looks)
        layout.addWidget(look_card)

        tone_card = Card("Tone")
        self.sliders: dict[str, SliderRow] = {}
        for key, label, low, high, default, scale, decimals, suffix in (
            ("brightness", "Brightness", 0.0, 2.5, 1.0, 100, 2, ""),
            ("contrast", "Contrast", 0.0, 2.5, 1.0, 100, 2, ""),
            ("saturation", "Saturation", 0.0, 2.5, 1.0, 100, 2, ""),
            ("gamma", "Gamma", 0.2, 2.5, 1.0, 100, 2, ""),
        ):
            row = SliderRow(label, low, high, default, scale=scale, decimals=decimals,
                            suffix=suffix)
            row.valueChanged.connect(lambda v, k=key: self._set_adjust(k, v))
            self.sliders[key] = row
            tone_card.add(row)
        layout.addWidget(tone_card)

        color_card = Card("Colour")
        for key, label, low, high, default in (
            ("temperature", "Temperature", -100.0, 100.0, 0.0),
            ("tint", "Tint", -100.0, 100.0, 0.0),
        ):
            row = SliderRow(label, low, high, default, scale=1, decimals=0)
            row.valueChanged.connect(lambda v, k=key: self._set_adjust(k, v))
            self.sliders[key] = row
            color_card.add(row)

        toggles = QGridLayout()
        toggles.setSpacing(6)
        self.flag_toggles: dict[str, LabeledToggle] = {}
        for index, (key, label) in enumerate((
            ("grayscale", "Black and white"),
            ("sepia", "Sepia"),
            ("invert", "Invert"),
            ("auto_contrast", "Auto contrast"),
            ("equalize", "Equalize"),
        )):
            toggle = LabeledToggle(label)
            toggle.toggled.connect(lambda v, k=key: self._set_adjust(k, v))
            self.flag_toggles[key] = toggle
            toggles.addWidget(toggle, index // 1, 0)
        color_card.add(divider())
        color_card.add_layout(toggles)
        layout.addWidget(color_card)

        detail_card = Card("Detail")
        for key, label, low, high, default, scale, decimals, suffix in (
            ("sharpness", "Sharpness", 0.0, 4.0, 1.0, 100, 2, ""),
            ("unsharp_amount", "Unsharp mask", 0.0, 300.0, 0.0, 1, 0, " %"),
            ("unsharp_radius", "Mask radius", 0.5, 8.0, 2.0, 10, 1, " px"),
            ("denoise", "Denoise", 0.0, 100.0, 0.0, 1, 0, ""),
            ("blur", "Blur", 0.0, 12.0, 0.0, 10, 1, " px"),
            ("vignette", "Vignette", 0.0, 100.0, 0.0, 1, 0, ""),
        ):
            row = SliderRow(label, low, high, default, scale=scale, decimals=decimals,
                            suffix=suffix)
            row.valueChanged.connect(lambda v, k=key: self._set_adjust(k, v))
            self.sliders[key] = row
            detail_card.add(row)
        layout.addWidget(detail_card)

        reset_row = QHBoxLayout()
        self.reset_adjust = QPushButton("Reset all adjustments")
        self.reset_adjust.setObjectName("Ghost")
        self.reset_adjust.clicked.connect(self._reset_adjustments)
        reset_row.addStretch(1)
        reset_row.addWidget(self.reset_adjust)
        layout.addLayout(reset_row)

        layout.addStretch(1)
        return page

    # ============================================================= EXPORT
    def _build_export_tab(self) -> QWidget:
        page, layout = _scroll_page()

        format_card = Card("File format")
        self.format_combo = QComboBox()
        for spec in imageio.output_formats():
            label = spec.label if spec.available else f"{spec.label}  (not installed)"
            self.format_combo.addItem(label, spec.key)
            index = self.format_combo.count() - 1
            if not spec.available:
                self.format_combo.model().item(index).setEnabled(False)
        self.format_combo.currentIndexChanged.connect(self._on_format)
        format_card.add(self.format_combo)

        self.jpeg_quality = SliderRow("JPEG quality", 40.0, 100.0, 92.0, scale=1,
                                      decimals=0)
        self.jpeg_quality.valueChanged.connect(
            lambda v: self._set_export("jpeg_quality", int(v))
        )
        self.webp_quality = SliderRow("WebP quality", 40.0, 100.0, 90.0, scale=1,
                                      decimals=0)
        self.webp_quality.valueChanged.connect(
            lambda v: self._set_export("webp_quality", int(v))
        )
        self.png_compression = SliderRow("PNG compression", 0.0, 9.0, 6.0, scale=1,
                                         decimals=0)
        self.png_compression.valueChanged.connect(
            lambda v: self._set_export("png_compression", int(v))
        )
        self.webp_lossless = LabeledToggle("WebP lossless")
        self.webp_lossless.toggled.connect(
            lambda v: self._set_export("webp_lossless", v)
        )
        for widget in (self.jpeg_quality, self.webp_quality, self.webp_lossless,
                       self.png_compression):
            format_card.add(widget)
        layout.addWidget(format_card)

        meta_card = Card("Metadata")
        self.keep_metadata = LabeledToggle("Keep EXIF and colour profile", True)
        self.keep_metadata.toggled.connect(lambda v: self._set_export("keep_metadata", v))
        self.strip_gps = LabeledToggle("Remove GPS location", False,
                                       "Strips coordinates while keeping the rest of "
                                       "the EXIF block.")
        self.strip_gps.toggled.connect(lambda v: self._set_export("strip_gps", v))
        meta_card.add(self.keep_metadata)
        meta_card.add(self.strip_gps)
        layout.addWidget(meta_card)

        dest_card = Card("Destination")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Same folder as the source file")
        self.output_edit.setReadOnly(True)
        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self._pick_output_dir)
        self.clear_output = IconButton("close", "Use the source folder", 14)
        self.clear_output.clicked.connect(self._clear_output_dir)
        row.addWidget(self.output_edit, 1)
        row.addWidget(self.browse_button, 0)
        row.addWidget(self.clear_output, 0)
        dest_card.add_layout(row)

        suffix_row = QHBoxLayout()
        suffix_label = QLabel("Suffix")
        suffix_label.setObjectName("Hint")
        self.suffix_edit = QLineEdit("_upscaled")
        self.suffix_edit.setMaximumWidth(160)
        self.suffix_edit.textChanged.connect(lambda v: self._set_export("suffix", v))
        suffix_row.addWidget(suffix_label, 0)
        suffix_row.addWidget(self.suffix_edit, 1)
        dest_card.add_layout(suffix_row)

        policy_row = QHBoxLayout()
        policy_label = QLabel("If the file exists")
        policy_label.setObjectName("Hint")
        self.policy_combo = QComboBox()
        for text, value in (("Add a number", "suffix"), ("Overwrite", "overwrite"),
                            ("Skip", "skip")):
            self.policy_combo.addItem(text, value)
        self.policy_combo.currentIndexChanged.connect(
            lambda: self._set_export("overwrite_policy", self.policy_combo.currentData())
        )
        policy_row.addWidget(policy_label, 1)
        policy_row.addWidget(self.policy_combo, 1)
        dest_card.add_layout(policy_row)
        layout.addWidget(dest_card)

        bg_card = Card("Background")
        bg_row = QHBoxLayout()
        bg_row.setSpacing(8)
        self.bg_button = QPushButton("Pick colour")
        self.bg_button.clicked.connect(self._pick_background)
        self.bg_preview = QLabel()
        self.bg_preview.setFixedSize(30, 26)
        bg_row.addWidget(self.bg_preview, 0)
        bg_row.addWidget(self.bg_button, 1)
        bg_card.add_layout(bg_row)
        bg_card.add(hint("Fills letterbox bars, and replaces transparency when the "
                         "format has no alpha channel."))
        layout.addWidget(bg_card)

        apply_row = QHBoxLayout()
        self.apply_all_button = QPushButton("Apply to all queued files")
        self.apply_all_button.setToolTip(
            "Copy every setting except the crop onto the other queued images."
        )
        self.apply_all_button.clicked.connect(self.apply_to_all_requested.emit)
        apply_row.addWidget(self.apply_all_button)
        layout.addLayout(apply_row)

        layout.addStretch(1)
        return page

    # ========================================================== data flow
    def load(self, settings: EditSettings) -> None:
        """Populate every widget from ``settings`` without emitting changes."""
        self.settings = settings
        self._loading = True
        try:
            self.size_mode.set_current(_SIZE_MODES.index(settings.size_mode))
            self.size_stack.setCurrentIndex(_SIZE_MODES.index(settings.size_mode))
            self.scale_slider.set_value(settings.scale)
            self.width_spin.setValue(settings.target_width)
            self.height_spin.setValue(settings.target_height)
            self.long_edge_spin.setValue(settings.long_edge)
            self.percent_slider.set_value(settings.percent)
            self.lock_aspect.setChecked(settings.lock_aspect)
            self._select_data(self.fit_combo, settings.fit_mode.value)
            self.btn_flip_h.setChecked(settings.flip_h)
            self.btn_flip_v.setChecked(settings.flip_v)
            self.rotation_label.setText(f"{int(settings.rotation)}°")

            if settings.backend in self._backend_keys:
                self.backend_seg.set_current(self._backend_keys.index(settings.backend))
            self._reload_models(settings.model)
            self._select_data(self.resample_combo, settings.resample)

            adjustments = settings.adjustments
            for key, row in self.sliders.items():
                row.set_value(float(getattr(adjustments, key)))
            for key, toggle in self.flag_toggles.items():
                toggle.setChecked(bool(getattr(adjustments, key)))

            export = settings.export
            self._select_data(self.format_combo, export.format)
            self.jpeg_quality.set_value(export.jpeg_quality)
            self.webp_quality.set_value(export.webp_quality)
            self.png_compression.set_value(export.png_compression)
            self.webp_lossless.setChecked(export.webp_lossless)
            self.keep_metadata.setChecked(export.keep_metadata)
            self.strip_gps.setChecked(export.strip_gps)
            self.suffix_edit.setText(export.suffix)
            self._select_data(self.policy_combo, export.overwrite_policy)
            self._paint_background(export.background)
            self._sync_format_widgets(export.format)
            self._sync_crop_info()
        finally:
            self._loading = False
        self._refresh_result_label()

    def set_source_size(self, width: int, height: int) -> None:
        self._source_size = (width, height)
        self._refresh_result_label()
        self._sync_crop_info()

    def set_plan_text(self, text: str) -> None:
        self.plan_label.setText(text)

    def set_devices(self, devices: tuple[str, ...], selected: int = 0) -> None:
        self.gpu_combo.clear()
        if not devices:
            self.gpu_combo.addItem("Default device", 0)
        else:
            for index, name in enumerate(devices):
                self.gpu_combo.addItem(f"{index}: {name}", index)
        self.gpu_combo.setCurrentIndex(min(selected, self.gpu_combo.count() - 1))

    def crop_button_set_checked(self, value: bool) -> None:
        self.crop_toggle.blockSignals(True)
        self.crop_toggle.setChecked(value)
        self.crop_toggle.blockSignals(False)

    def apply_color(self, palette) -> None:
        """Recolour every icon-bearing child after a theme switch."""
        for button in (self.btn_rot_ccw, self.btn_rot_cw, self.btn_flip_h,
                       self.btn_flip_v, self.lock_aspect, self.swap_button,
                       self.clear_output):
            button.apply_color(palette.text_dim)
        for row in (*self.sliders.values(), self.scale_slider, self.percent_slider,
                    self.jpeg_quality, self.webp_quality, self.png_compression):
            row.apply_color(palette.text_faint)
        for toggle in (*self.flag_toggles.values(), self.gpu_toggle, self.keep_metadata,
                       self.strip_gps, self.webp_lossless):
            toggle.switch.set_colors(palette.surface_high, palette.accent, palette.text)
        self.crop_toggle.setIcon(icons.icon("crop", palette.text, 16))

    # -------------------------------------------------------- change hooks
    def _emit(self) -> None:
        if not self._loading:
            self._refresh_result_label()
            self.changed.emit()

    def _set(self, field: str, value) -> None:
        setattr(self.settings, field, value)
        self._emit()

    def _set_adjust(self, field: str, value) -> None:
        setattr(self.settings.adjustments, field, value)
        if not self._loading:
            self.look_group.setExclusive(False)
            for button in self.look_group.buttons():
                button.setChecked(False)
            self.look_group.setExclusive(True)
        self._emit()

    def _set_export(self, field: str, value) -> None:
        setattr(self.settings.export, field, value)
        self._emit()

    def _on_size_mode(self, index: int) -> None:
        self.size_stack.setCurrentIndex(index)
        self._set("size_mode", _SIZE_MODES[index])

    def _on_dimension(self, which: str, value: int) -> None:
        if self._loading:
            return
        if self.settings.lock_aspect and all(self._source_size):
            src_w, src_h = self._source_size
            ratio = src_w / src_h
            self._loading = True
            if which == "w":
                self.height_spin.setValue(max(1, round(value / ratio)))
            else:
                self.width_spin.setValue(max(1, round(value * ratio)))
            self._loading = False
        self.settings.target_width = self.width_spin.value()
        self.settings.target_height = self.height_spin.value()
        self._match_preset()
        self._emit()

    def _on_lock(self, value: bool) -> None:
        self.lock_aspect.apply_color("#9AA3B8")
        self.lock_aspect._name = "lock" if value else "unlock"
        self.lock_aspect.setToolTip(
            "Aspect ratio locked" if value else "Width and height independent"
        )
        self._set("lock_aspect", value)

    def _swap_dimensions(self) -> None:
        width, height = self.height_spin.value(), self.width_spin.value()
        self._loading = True
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)
        self._loading = False
        self.settings.target_width = width
        self.settings.target_height = height
        self._emit()

    def _on_preset(self, index: int) -> None:
        key = self.preset_combo.currentData()
        if key is None or self._loading:
            return
        preset = next(p for p in RESOLUTION_PRESETS if p.key == key)
        self._loading = True
        self.width_spin.setValue(preset.width)
        self.height_spin.setValue(preset.height)
        self._loading = False
        self.settings.target_width = preset.width
        self.settings.target_height = preset.height
        self._emit()

    def _match_preset(self) -> None:
        width, height = self.width_spin.value(), self.height_spin.value()
        for index in range(self.preset_combo.count()):
            key = self.preset_combo.itemData(index)
            if key is None:
                continue
            preset = next(p for p in RESOLUTION_PRESETS if p.key == key)
            if (preset.width, preset.height) == (width, height):
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(index)
                self.preset_combo.blockSignals(False)
                return
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _on_fit(self) -> None:
        value = self.fit_combo.currentData()
        if value:
            self._set("fit_mode", FitMode(value))

    def _rotate(self, delta: int) -> None:
        current = int(self.settings.rotation)
        value = (current + delta) % 360
        self.settings.rotation = Rotation(value)
        self.rotation_label.setText(f"{value}°")
        self._emit()

    def _on_crop_ratio(self, index: int) -> None:
        _, ratio = ASPECT_RATIOS[index]
        if ratio == 0.0 and all(self._source_size):
            ratio = self._source_size[0] / self._source_size[1]
        elif ratio == 0.0:
            ratio = None
        self.crop_ratio_changed.emit(ratio)

    def _sync_crop_info(self) -> None:
        crop = self.settings.crop
        if crop.is_empty:
            self.crop_info.setText("Full image")
        else:
            self.crop_info.setText(
                f"{crop.width} x {crop.height} px  at  ({crop.x}, {crop.y})"
            )

    def set_crop(self, crop: CropRect) -> None:
        self.settings.crop = crop
        self._sync_crop_info()
        self._emit()

    def _apply_look(self, preset) -> None:
        self.settings.adjustments = Adjustments(**preset.adjustments.__dict__)
        self._loading = True
        for key, row in self.sliders.items():
            row.set_value(float(getattr(self.settings.adjustments, key)))
        for key, toggle in self.flag_toggles.items():
            toggle.setChecked(bool(getattr(self.settings.adjustments, key)))
        self._loading = False
        self._emit()

    def _reset_adjustments(self) -> None:
        self.settings.adjustments = Adjustments()
        self._loading = True
        for key, row in self.sliders.items():
            row.set_value(float(getattr(self.settings.adjustments, key)))
        for toggle in self.flag_toggles.values():
            toggle.setChecked(False)
        self.look_group.setExclusive(False)
        for button in self.look_group.buttons():
            button.setChecked(False)
        self.look_group.setExclusive(True)
        self._loading = False
        self._emit()

    def _on_backend(self, index: int) -> None:
        key = self._backend_keys[index]
        self.settings.backend = key
        self.backend_hint.setText(BACKENDS[key].description)
        self._reload_models(None)
        self._emit()

    def _reload_models(self, preferred: str | None) -> None:
        backend = BACKENDS[self.settings.backend]
        self.backend_hint.setText(backend.description)
        models = backend.models()
        was_loading = self._loading
        self._loading = True
        self.model_combo.clear()
        for info in models:
            self.model_combo.addItem(info.label, info.key)
        target = preferred or self.settings.model
        position = max(0, self.model_combo.findData(target))
        self.model_combo.setCurrentIndex(position)
        self._loading = was_loading
        if models:
            self.settings.model = self.model_combo.currentData()
            self.model_hint.setText(models[position].description)

    def _on_model(self) -> None:
        key = self.model_combo.currentData()
        if not key:
            return
        backend = BACKENDS[self.settings.backend]
        for info in backend.models():
            if info.key == key:
                self.model_hint.setText(info.description)
                break
        self._set("model", key)

    def _on_format(self) -> None:
        key = self.format_combo.currentData()
        if not key:
            return
        self._sync_format_widgets(key)
        self._set_export("format", key)

    def _sync_format_widgets(self, fmt: str) -> None:
        fmt = fmt.upper()
        self.jpeg_quality.setVisible(fmt in ("JPEG", "HEIF"))
        self.webp_quality.setVisible(fmt in ("WEBP", "AVIF"))
        self.webp_lossless.setVisible(fmt == "WEBP")
        self.png_compression.setVisible(fmt == "PNG")

    def _pick_output_dir(self) -> None:
        start = str(self.output_dir) if self.output_dir else ""
        chosen = QFileDialog.getExistingDirectory(self, "Choose an output folder", start)
        if chosen:
            self.output_dir = Path(chosen)
            self.output_edit.setText(chosen)
            self._emit()

    def _clear_output_dir(self) -> None:
        self.output_dir = None
        self.output_edit.clear()
        self._emit()

    def _pick_background(self) -> None:
        current = QColor(self.settings.export.background)
        chosen = QColorDialog.getColor(current, self, "Background colour")
        if chosen.isValid():
            self._paint_background(chosen.name())
            self._set_export("background", chosen.name())

    def _paint_background(self, color: str) -> None:
        self.bg_preview.setStyleSheet(
            f"background: {color}; border: 1px solid rgba(255,255,255,40);"
            " border-radius: 6px;"
        )

    # ------------------------------------------------------------ helpers
    def _select_data(self, combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _refresh_result_label(self) -> None:
        if not all(self._source_size):
            self.result_label.setText("Load an image to see the output size.")
            return
        from ...core import geometry

        src_w, src_h = geometry.source_after_transform(*self._source_size, self.settings)
        out_w, out_h = geometry.resolve_target(src_w, src_h, self.settings)
        megapixels = out_w * out_h / 1_000_000
        self.result_label.setText(
            f"Output  {out_w} x {out_h} px   ·   {megapixels:.1f} MP   "
            f"·   from {src_w} x {src_h}"
        )

    def gpu_settings(self) -> tuple[bool, int, int]:
        return (
            self.gpu_toggle.isChecked(),
            int(self.gpu_combo.currentData() or 0),
            int(self.tile_combo.currentData() or 0),
        )
