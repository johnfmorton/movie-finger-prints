from __future__ import annotations

import os
import shutil
import tempfile

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.compositor import compose_grid
from core.fill_order import FillOrder, compute_fill_order
from core.highlights import (
    assign_highlights_to_cells,
    compute_weighted_timestamps,
    parse_timestamp,
)
from core.quadtree import SubdivisionStyle, generate_quadtree, cells_to_pixel_rects
from core.video import extract_frames, extract_frames_at_timestamps, probe_video
from gui.frame_picker import FramePickerDialog
from gui.grid_preview import GridPreviewWidget


VERSION = "1.1.1"

ARTWORK_PRESETS = {
    "MacBook Pro 16\" (3456x2234)": (3456, 2234),
    "MacBook Pro 14\" (3024x1964)": (3024, 1964),
    "MacBook Air 15\" (2880x1864)": (2880, 1864),
    "MacBook Air 13\" (2560x1664)": (2560, 1664),
    "iMac 24\" (4480x2520)": (4480, 2520),
    "Apple Studio Display (5120x2880)": (5120, 2880),
    "Pro Display XDR (6016x3384)": (6016, 3384),
    "4K UHD (3840x2160)": (3840, 2160),
    "1080p (1920x1080)": (1920, 1080),
    "Custom": (0, 0),
}

OUTPUT_FORMATS = {
    "PNG": {"format": "PNG", "ext": ".png", "has_quality": False},
    "JPEG": {"format": "JPEG", "ext": ".jpg", "has_quality": True},
    "WebP": {"format": "WEBP", "ext": ".webp", "has_quality": True},
    "TIFF": {"format": "TIFF", "ext": ".tiff", "has_quality": False},
}

BACKGROUND_COLORS = {
    "Black": (0, 0, 0),
    "White": (255, 255, 255),
    "Dark Gray": (40, 40, 40),
    "Custom...": None,
}


class GenerateWorker(QThread):
    """Background worker thread for frame extraction and compositing."""

    progress = pyqtSignal(int, int, str)  # current, total, stage description
    finished = pyqtSignal(str)  # output path
    error = pyqtSignal(str)  # error message

    def __init__(
        self,
        video_path: str,
        rows: int,
        cols: int,
        output_width: int,
        output_height: int,
        skip_black: bool,
        output_path: str,
        output_format: str = "PNG",
        jpeg_quality: int = 90,
        padding: int = 0,
        background_color: tuple[int, int, int] = (0, 0, 0),
        cell_labels: str = "none",
        fill_positions: list[tuple[int, int]] | None = None,
        video_duration: float = 0.0,
        cell_rects: list[tuple[int, int, int, int]] | None = None,
        total_frames_override: int | None = None,
        highlight_timestamps: list[float] | None = None,
        highlight_cell_indices: list[int] | None = None,
        highlight_boost: float = 2.0,
        cell_aspect_ratio: tuple[int, int] | None = None,
    ):
        super().__init__()
        self.video_path = video_path
        self.rows = rows
        self.cols = cols
        self.output_width = output_width
        self.output_height = output_height
        self.skip_black = skip_black
        self.output_path = output_path
        self.output_format = output_format
        self.jpeg_quality = jpeg_quality
        self.padding = padding
        self.background_color = background_color
        self.cell_labels = cell_labels
        self.fill_positions = fill_positions
        self.video_duration = video_duration
        self.cell_rects = cell_rects
        self.total_frames_override = total_frames_override
        self.highlight_timestamps = highlight_timestamps or []
        self.highlight_cell_indices = highlight_cell_indices or []
        self.highlight_boost = highlight_boost
        self.cell_aspect_ratio = cell_aspect_ratio
        self._tmp_dir = None

    def run(self):
        try:
            total_frames = self.total_frames_override or self.rows * self.cols
            tmp_dirs: list[str] = []

            has_highlights = (
                bool(self.highlight_timestamps)
                and bool(self.highlight_cell_indices)
                and self.cell_rects is not None
            )

            if has_highlights:
                num_highlights = len(self.highlight_timestamps)
                num_regular = total_frames - num_highlights
                total_extractions = total_frames  # for progress

                # 1. Extract highlight frames at exact timestamps
                sorted_hl = sorted(self.highlight_timestamps)
                hl_paths = extract_frames_at_timestamps(
                    self.video_path,
                    sorted_hl,
                    progress_callback=lambda c, t: self.progress.emit(
                        c, total_extractions + 1, "Extracting highlight frames"
                    ),
                    progress_offset=0,
                    progress_total=total_extractions + 1,
                )
                if hl_paths:
                    tmp_dirs.append(os.path.dirname(hl_paths[0]))

                # 2. Compute weighted timestamps for regular frames
                if num_regular > 0:
                    regular_timestamps = compute_weighted_timestamps(
                        self.video_duration,
                        num_regular,
                        sorted_hl,
                        boost_factor=self.highlight_boost,
                    )

                    reg_paths = extract_frames(
                        self.video_path,
                        num_regular,
                        skip_black=self.skip_black,
                        progress_callback=lambda c, t: self.progress.emit(
                            num_highlights + c,
                            total_extractions + 1,
                            "Extracting frames",
                        ),
                        timestamps=regular_timestamps,
                    )
                    if reg_paths:
                        tmp_dirs.append(os.path.dirname(reg_paths[0]))
                else:
                    reg_paths = []
                    regular_timestamps = []

                # 3. Merge: place highlight frames at their cell indices,
                #    fill remaining cells with regular frames
                hl_set = set(self.highlight_cell_indices)
                # Map sorted highlight times -> paths (preserve order matching
                # sorted_hl since extract returns in that order)
                # Map original highlight_timestamps order to hl_paths via sorting
                hl_time_to_path = dict(zip(sorted_hl, hl_paths))
                # Assign highlight cells in order: cell indices sorted,
                # highlight times sorted, so pair them up
                sorted_cell_indices = sorted(self.highlight_cell_indices)
                hl_cell_to_path = dict(zip(
                    sorted_cell_indices,
                    [hl_time_to_path[t] for t in sorted_hl],
                ))

                frame_paths: list[str] = []
                reg_idx = 0
                all_timestamps: list[float] = []  # for timestamp labels
                for i in range(total_frames):
                    if i in hl_cell_to_path:
                        frame_paths.append(hl_cell_to_path[i])
                        # Find the highlight time for this cell
                        ci = sorted_cell_indices.index(i)
                        all_timestamps.append(sorted_hl[ci])
                    else:
                        if reg_idx < len(reg_paths):
                            frame_paths.append(reg_paths[reg_idx])
                            if reg_idx < len(regular_timestamps):
                                all_timestamps.append(regular_timestamps[reg_idx])
                            else:
                                all_timestamps.append(0.0)
                            reg_idx += 1
                        else:
                            # Shouldn't happen, but safety fallback
                            frame_paths.append("")
                            all_timestamps.append(0.0)
            else:
                # No highlights — standard path
                def on_progress(current, total):
                    self.progress.emit(current, total, "Extracting frames")

                frame_paths = extract_frames(
                    self.video_path,
                    total_frames,
                    skip_black=self.skip_black,
                    progress_callback=on_progress,
                )
                if frame_paths:
                    tmp_dirs.append(os.path.dirname(frame_paths[0]))
                all_timestamps = None

            self.progress.emit(0, 1, "Compositing image")

            # Compute timestamp labels if needed
            frame_timestamps = None
            if self.cell_labels == "timestamp" and self.video_duration > 0:
                if all_timestamps:
                    frame_timestamps = []
                    for t in all_timestamps:
                        mins = int(t // 60)
                        secs = int(t % 60)
                        frame_timestamps.append(f"{mins}:{secs:02d}")
                else:
                    frame_timestamps = []
                    for i in range(len(frame_paths)):
                        t = self.video_duration * (i + 0.5) / total_frames
                        mins = int(t // 60)
                        secs = int(t % 60)
                        frame_timestamps.append(f"{mins}:{secs:02d}")

            compose_grid(
                frame_paths,
                self.rows,
                self.cols,
                self.output_width,
                self.output_height,
                self.output_path,
                output_format=self.output_format,
                jpeg_quality=self.jpeg_quality,
                padding=self.padding,
                background_color=self.background_color,
                cell_labels=self.cell_labels,
                fill_positions=self.fill_positions,
                frame_timestamps=frame_timestamps,
                cell_rects=self.cell_rects,
                cell_aspect_ratio=self.cell_aspect_ratio,
            )

            # Clean up temp frames
            for d in tmp_dirs:
                shutil.rmtree(d, ignore_errors=True)

            self.finished.emit(self.output_path)

        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Movie Finger Print")
        self.setMinimumWidth(520)

        self._video_info = None
        self._worker = None
        self._custom_bg_color = (0, 0, 0)
        self._quadtree_cells = []
        self._highlight_timestamps: list[float] = []

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)

        # --- Video file ---
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Video File:"))
        self.video_path_edit = QLineEdit()
        self.video_path_edit.setReadOnly(True)
        self.video_path_edit.setPlaceholderText("No file selected")
        file_layout.addWidget(self.video_path_edit, stretch=1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_video)
        file_layout.addWidget(browse_btn)
        layout.addLayout(file_layout)

        # --- Grid Settings ---
        grid_group = QGroupBox("Grid Settings")
        grid_layout = QVBoxLayout(grid_group)

        # Grid Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Grid Mode:"))
        self.grid_mode_combo = QComboBox()
        self.grid_mode_combo.addItems(["Standard", "Quadtree"])
        self.grid_mode_combo.currentTextChanged.connect(self._on_grid_mode_changed)
        mode_row.addWidget(self.grid_mode_combo)
        mode_row.addStretch()
        grid_layout.addLayout(mode_row)

        # Standard mode controls
        self._standard_row = QWidget()
        std_layout = QHBoxLayout(self._standard_row)
        std_layout.setContentsMargins(0, 0, 0, 0)

        std_layout.addWidget(QLabel("Columns:"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 200)
        self.cols_spin.setValue(30)
        self.cols_spin.valueChanged.connect(self._update_total_frames)
        std_layout.addWidget(self.cols_spin)

        std_layout.addSpacing(20)

        std_layout.addWidget(QLabel("Rows:"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 200)
        self.rows_spin.setValue(20)
        self.rows_spin.valueChanged.connect(self._update_total_frames)
        std_layout.addWidget(self.rows_spin)

        std_layout.addSpacing(20)

        self.total_frames_label = QLabel("Total frames: 600")
        std_layout.addWidget(self.total_frames_label)
        std_layout.addStretch()
        grid_layout.addWidget(self._standard_row)

        # Quadtree mode controls
        self._quadtree_row = QWidget()
        qt_layout = QHBoxLayout(self._quadtree_row)
        qt_layout.setContentsMargins(0, 0, 0, 0)

        qt_layout.addWidget(QLabel("Depth:"))
        self.qt_depth_spin = QSpinBox()
        self.qt_depth_spin.setRange(1, 6)
        self.qt_depth_spin.setValue(3)
        self.qt_depth_spin.valueChanged.connect(self._update_quadtree)
        qt_layout.addWidget(self.qt_depth_spin)

        qt_layout.addSpacing(10)

        qt_layout.addWidget(QLabel("Style:"))
        self.qt_style_combo = QComboBox()
        for style in SubdivisionStyle:
            self.qt_style_combo.addItem(style.value)
        self.qt_style_combo.currentTextChanged.connect(self._update_quadtree)
        qt_layout.addWidget(self.qt_style_combo)

        qt_layout.addSpacing(10)

        qt_layout.addWidget(QLabel("Seed:"))
        self.qt_seed_spin = QSpinBox()
        self.qt_seed_spin.setRange(0, 9999)
        self.qt_seed_spin.setValue(42)
        self.qt_seed_spin.valueChanged.connect(self._update_quadtree)
        qt_layout.addWidget(self.qt_seed_spin)

        qt_layout.addSpacing(10)

        self.qt_total_label = QLabel("Cells: —")
        qt_layout.addWidget(self.qt_total_label)
        qt_layout.addStretch()
        self._quadtree_row.setVisible(False)
        grid_layout.addWidget(self._quadtree_row)

        layout.addWidget(grid_group)

        # --- Grid Preview ---
        preview_group = QGroupBox("Grid Preview")
        preview_layout = QVBoxLayout(preview_group)

        self._fill_order_row = QWidget()
        order_row_layout = QHBoxLayout(self._fill_order_row)
        order_row_layout.setContentsMargins(0, 0, 0, 0)
        order_row_layout.addWidget(QLabel("Fill Order:"))
        self.fill_order_combo = QComboBox()
        for order in FillOrder:
            self.fill_order_combo.addItem(order.value)
        self.fill_order_combo.currentTextChanged.connect(self._on_fill_order_changed)
        order_row_layout.addWidget(self.fill_order_combo, stretch=1)
        order_row_layout.addStretch()
        preview_layout.addWidget(self._fill_order_row)

        self.grid_preview = GridPreviewWidget()
        preview_layout.addWidget(self.grid_preview)
        layout.addWidget(preview_group)

        # Connect grid size changes to preview
        self.cols_spin.valueChanged.connect(self._update_preview)
        self.rows_spin.valueChanged.connect(self._update_preview)

        # --- Highlight Frames ---
        highlight_group = QGroupBox("Highlight Frames")
        highlight_layout = QVBoxLayout(highlight_group)

        highlight_layout.addWidget(
            QLabel("Feature key moments in larger cells")
        )

        hl_add_row = QHBoxLayout()
        self.hl_timestamp_edit = QLineEdit()
        self.hl_timestamp_edit.setPlaceholderText("e.g. 1:23:45")
        self.hl_timestamp_edit.returnPressed.connect(self._add_highlight)
        hl_add_row.addWidget(self.hl_timestamp_edit)
        hl_add_btn = QPushButton("Add")
        hl_add_btn.clicked.connect(self._add_highlight)
        hl_add_row.addWidget(hl_add_btn)
        self.hl_pick_btn = QPushButton("Pick Frames...")
        self.hl_pick_btn.setEnabled(False)
        self.hl_pick_btn.clicked.connect(self._open_frame_picker)
        hl_add_row.addWidget(self.hl_pick_btn)
        highlight_layout.addLayout(hl_add_row)

        self.hl_list = QListWidget()
        self.hl_list.setMaximumHeight(80)
        highlight_layout.addWidget(self.hl_list)

        hl_bottom_row = QHBoxLayout()
        hl_remove_btn = QPushButton("Remove")
        hl_remove_btn.clicked.connect(self._remove_highlight)
        hl_bottom_row.addWidget(hl_remove_btn)
        self.hl_count_label = QLabel("0 highlights")
        hl_bottom_row.addWidget(self.hl_count_label)
        hl_bottom_row.addStretch()
        hl_bottom_row.addWidget(QLabel("Boost:"))
        self.hl_boost_spin = QDoubleSpinBox()
        self.hl_boost_spin.setRange(1.0, 5.0)
        self.hl_boost_spin.setValue(2.0)
        self.hl_boost_spin.setSingleStep(0.5)
        hl_bottom_row.addWidget(self.hl_boost_spin)
        highlight_layout.addLayout(hl_bottom_row)

        self._hl_mode_note = QLabel("Applies to variable-sized grid modes")
        self._hl_mode_note.setStyleSheet("color: gray; font-size: 11px;")
        self._hl_mode_note.setVisible(not self._is_quadtree_mode())
        highlight_layout.addWidget(self._hl_mode_note)

        layout.addWidget(highlight_group)

        # --- Cell Aspect Ratio ---
        aspect_group = QGroupBox("Cell Aspect Ratio")
        aspect_layout = QVBoxLayout(aspect_group)

        self.aspect_from_video = QRadioButton("From video")
        self.aspect_from_video.setChecked(True)
        self.aspect_from_video.toggled.connect(self._on_aspect_changed)
        aspect_layout.addWidget(self.aspect_from_video)

        presets_row = QHBoxLayout()
        self.aspect_16_9 = QRadioButton("16:9")
        self.aspect_16_9.toggled.connect(self._on_aspect_changed)
        presets_row.addWidget(self.aspect_16_9)
        self.aspect_4_3 = QRadioButton("4:3")
        self.aspect_4_3.toggled.connect(self._on_aspect_changed)
        presets_row.addWidget(self.aspect_4_3)
        self.aspect_1_1 = QRadioButton("1:1")
        self.aspect_1_1.toggled.connect(self._on_aspect_changed)
        presets_row.addWidget(self.aspect_1_1)
        self.aspect_custom = QRadioButton("Custom")
        self.aspect_custom.toggled.connect(self._on_aspect_changed)
        presets_row.addWidget(self.aspect_custom)
        presets_row.addStretch()
        aspect_layout.addLayout(presets_row)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Custom W:"))
        self.custom_aspect_w = QSpinBox()
        self.custom_aspect_w.setRange(1, 999)
        self.custom_aspect_w.setValue(16)
        self.custom_aspect_w.setEnabled(False)
        custom_row.addWidget(self.custom_aspect_w)
        custom_row.addSpacing(10)
        custom_row.addWidget(QLabel("H:"))
        self.custom_aspect_h = QSpinBox()
        self.custom_aspect_h.setRange(1, 999)
        self.custom_aspect_h.setValue(9)
        self.custom_aspect_h.setEnabled(False)
        custom_row.addWidget(self.custom_aspect_h)
        custom_row.addStretch()
        aspect_layout.addLayout(custom_row)

        layout.addWidget(aspect_group)

        # --- Output Settings ---
        output_group = QGroupBox("Output Settings")
        output_layout = QVBoxLayout(output_group)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Artwork Size:"))
        self.size_combo = QComboBox()
        for name in ARTWORK_PRESETS:
            self.size_combo.addItem(name)
        self.size_combo.currentTextChanged.connect(self._on_size_preset_changed)
        size_row.addWidget(self.size_combo, stretch=1)
        output_layout.addLayout(size_row)

        dims_row = QHBoxLayout()
        dims_row.addWidget(QLabel("Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 20000)
        self.width_spin.setValue(3456)
        self.width_spin.setEnabled(False)
        dims_row.addWidget(self.width_spin)
        dims_row.addSpacing(10)
        dims_row.addWidget(QLabel("Height:"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 20000)
        self.height_spin.setValue(2234)
        self.height_spin.setEnabled(False)
        dims_row.addWidget(self.height_spin)
        dims_row.addStretch()
        output_layout.addLayout(dims_row)

        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        for name in OUTPUT_FORMATS:
            self.format_combo.addItem(name)
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        format_row.addWidget(self.format_combo)
        format_row.addSpacing(20)
        self.quality_label = QLabel("Quality:")
        self.quality_label.setEnabled(False)
        format_row.addWidget(self.quality_label)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(90)
        self.quality_spin.setEnabled(False)
        format_row.addWidget(self.quality_spin)
        format_row.addStretch()
        output_layout.addLayout(format_row)

        layout.addWidget(output_group)

        # --- Styling ---
        style_group = QGroupBox("Styling")
        style_layout = QVBoxLayout(style_group)

        padding_row = QHBoxLayout()
        padding_row.addWidget(QLabel("Padding:"))
        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 50)
        self.padding_spin.setValue(0)
        self.padding_spin.setSuffix(" px")
        padding_row.addWidget(self.padding_spin)
        padding_row.addStretch()
        style_layout.addLayout(padding_row)

        bg_row = QHBoxLayout()
        bg_row.addWidget(QLabel("Background:"))
        self.bg_color_combo = QComboBox()
        for name in BACKGROUND_COLORS:
            self.bg_color_combo.addItem(name)
        self.bg_color_combo.currentTextChanged.connect(self._on_bg_color_changed)
        bg_row.addWidget(self.bg_color_combo)
        bg_row.addStretch()
        style_layout.addLayout(bg_row)

        labels_row = QHBoxLayout()
        labels_row.addWidget(QLabel("Cell Labels:"))
        self.cell_labels_combo = QComboBox()
        self.cell_labels_combo.addItems(["None", "Frame Number", "Timestamp"])
        labels_row.addWidget(self.cell_labels_combo)
        labels_row.addStretch()
        style_layout.addLayout(labels_row)

        layout.addWidget(style_group)

        # --- Skip black frames ---
        self.skip_black_cb = QCheckBox("Skip black frames")
        self.skip_black_cb.setChecked(True)
        layout.addWidget(self.skip_black_cb)

        # --- Output file ---
        out_file_layout = QHBoxLayout()
        out_file_layout.addWidget(QLabel("Output file:"))
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("output.png")
        out_file_layout.addWidget(self.output_path_edit, stretch=1)
        out_browse_btn = QPushButton("Browse...")
        out_browse_btn.clicked.connect(self._browse_output)
        out_file_layout.addWidget(out_browse_btn)
        layout.addLayout(out_file_layout)

        # --- Progress bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # --- Generate button ---
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setMinimumHeight(40)
        self.generate_btn.clicked.connect(self._generate)
        layout.addWidget(self.generate_btn)

        layout.addStretch()

        # --- Version footer ---
        version_label = QLabel(f"v{VERSION}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        version_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(version_label)

        # Initialize preview
        self._update_preview()

    # --- Slots ---

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm);;All Files (*)",
        )
        if path:
            self.video_path_edit.setText(path)
            self._load_video_info(path)

    def _load_video_info(self, path: str):
        try:
            self._video_info = probe_video(path)
            ar = self._video_info.aspect_ratio
            self.aspect_from_video.setText(f"From video ({ar[0]}:{ar[1]})")

            # Default output name next to the video file
            video_dir = os.path.dirname(path)
            video_name = os.path.splitext(os.path.basename(path))[0]
            ext = self._current_format_ext()
            default_output = os.path.join(video_dir, f"{video_name}_fingerprint{ext}")
            self.output_path_edit.setText(default_output)

            self.status_label.setText(
                f"Loaded: {self._video_info.width}x{self._video_info.height}, "
                f"{self._video_info.duration:.1f}s, ~{self._video_info.frame_count} frames"
            )
            self.hl_pick_btn.setEnabled(True)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to probe video:\n{e}")
            self._video_info = None
            self.hl_pick_btn.setEnabled(False)

    def _current_format_ext(self) -> str:
        fmt_name = self.format_combo.currentText()
        return OUTPUT_FORMATS.get(fmt_name, OUTPUT_FORMATS["PNG"])["ext"]

    def _browse_output(self):
        fmt_name = self.format_combo.currentText()
        fmt_info = OUTPUT_FORMATS.get(fmt_name, OUTPUT_FORMATS["PNG"])
        ext = fmt_info["ext"]
        filter_str = f"{fmt_name} Files (*{ext});;All Files (*)"

        path, _ = QFileDialog.getSaveFileName(self, "Save Output", "", filter_str)
        if path:
            if not path.lower().endswith(ext):
                path += ext
            self.output_path_edit.setText(path)

    def _is_quadtree_mode(self) -> bool:
        return self.grid_mode_combo.currentText() == "Quadtree"

    def _on_grid_mode_changed(self):
        qt_mode = self._is_quadtree_mode()
        self._standard_row.setVisible(not qt_mode)
        self._quadtree_row.setVisible(qt_mode)
        self._fill_order_row.setVisible(not qt_mode)
        self._hl_mode_note.setVisible(not qt_mode)
        if qt_mode:
            self._update_quadtree()
        else:
            self.grid_preview.clear_quadtree()
            self._update_preview()
            self._update_total_frames()

    def _update_quadtree(self):
        style_text = self.qt_style_combo.currentText()
        style = SubdivisionStyle.BALANCED
        for s in SubdivisionStyle:
            if s.value == style_text:
                style = s
                break
        cells = generate_quadtree(
            self.qt_depth_spin.value(),
            style,
            seed=self.qt_seed_spin.value(),
        )
        self._quadtree_cells = cells
        self.qt_total_label.setText(f"Cells: {len(cells)}")
        self.grid_preview.set_quadtree_cells(cells)
        self._update_highlight_preview()

    def _update_total_frames(self):
        total = self.cols_spin.value() * self.rows_spin.value()
        self.total_frames_label.setText(f"Total frames: {total}")

    def _update_preview(self):
        self.grid_preview.set_grid(self.rows_spin.value(), self.cols_spin.value())

    def _on_fill_order_changed(self, text: str):
        for order in FillOrder:
            if order.value == text:
                self.grid_preview.set_fill_order(order)
                break

    # --- Highlight frame slots ---

    def _add_highlight(self):
        text = self.hl_timestamp_edit.text().strip()
        if not text:
            return
        try:
            ts = parse_timestamp(text)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Timestamp", str(e))
            return

        # Validate against video duration if loaded
        if self._video_info and ts > self._video_info.duration:
            QMessageBox.warning(
                self,
                "Out of Range",
                f"Timestamp {text} exceeds video duration "
                f"({self._video_info.duration:.1f}s).",
            )
            return

        # Deduplicate
        if ts in self._highlight_timestamps:
            self.hl_timestamp_edit.clear()
            return

        self._highlight_timestamps.append(ts)
        self._highlight_timestamps.sort()
        self._refresh_highlight_list()
        self.hl_timestamp_edit.clear()
        self._update_highlight_preview()

    def _remove_highlight(self):
        row = self.hl_list.currentRow()
        if row < 0:
            return
        del self._highlight_timestamps[row]
        self._refresh_highlight_list()
        self._update_highlight_preview()

    def _open_frame_picker(self):
        video_path = self.video_path_edit.text()
        if not video_path or not self._video_info:
            return
        dialog = FramePickerDialog(
            video_path,
            self._video_info,
            self._highlight_timestamps or None,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._highlight_timestamps = dialog.get_timestamps()
            self._refresh_highlight_list()
            self._update_highlight_preview()

    def _refresh_highlight_list(self):
        self.hl_list.clear()
        for ts in self._highlight_timestamps:
            h = int(ts // 3600)
            m = int((ts % 3600) // 60)
            s = ts % 60
            if h > 0:
                label = f"{h}:{m:02d}:{s:05.2f}"
            else:
                label = f"{m}:{s:05.2f}"
            self.hl_list.addItem(label)
        n = len(self._highlight_timestamps)
        self.hl_count_label.setText(
            f"{n} highlight{'s' if n != 1 else ''}"
        )

    def _update_highlight_preview(self):
        if self._is_quadtree_mode() and self._highlight_timestamps and self._quadtree_cells:
            indices = assign_highlights_to_cells(
                self._quadtree_cells,
                len(self._highlight_timestamps),
            )
            self.grid_preview.set_highlight_cells(indices)
        else:
            self.grid_preview.set_highlight_cells([])

    def _get_cell_aspect_ratio(self) -> tuple[int, int] | None:
        """Return the selected cell aspect ratio as (w, h), or None for 'From video'."""
        if self.aspect_from_video.isChecked():
            return None
        if self.aspect_16_9.isChecked():
            return (16, 9)
        if self.aspect_4_3.isChecked():
            return (4, 3)
        if self.aspect_1_1.isChecked():
            return (1, 1)
        if self.aspect_custom.isChecked():
            return (self.custom_aspect_w.value(), self.custom_aspect_h.value())
        return None

    def _on_aspect_changed(self):
        is_custom = self.aspect_custom.isChecked()
        self.custom_aspect_w.setEnabled(is_custom)
        self.custom_aspect_h.setEnabled(is_custom)

    def _on_size_preset_changed(self, text: str):
        is_custom = text == "Custom"
        self.width_spin.setEnabled(is_custom)
        self.height_spin.setEnabled(is_custom)
        if not is_custom and text in ARTWORK_PRESETS:
            w, h = ARTWORK_PRESETS[text]
            self.width_spin.setValue(w)
            self.height_spin.setValue(h)

    def _on_format_changed(self, text: str):
        fmt_info = OUTPUT_FORMATS.get(text, OUTPUT_FORMATS["PNG"])
        has_quality = fmt_info["has_quality"]
        self.quality_label.setEnabled(has_quality)
        self.quality_spin.setEnabled(has_quality)

        # Update output path extension if one is set
        current_path = self.output_path_edit.text().strip()
        if current_path:
            base, _ = os.path.splitext(current_path)
            self.output_path_edit.setText(base + fmt_info["ext"])

    def _on_bg_color_changed(self, text: str):
        if text == "Custom...":
            from PyQt6.QtGui import QColor
            color = QColorDialog.getColor(
                QColor(*self._custom_bg_color), self, "Choose Background Color"
            )
            if color.isValid():
                self._custom_bg_color = (color.red(), color.green(), color.blue())

    def _get_background_color(self) -> tuple[int, int, int]:
        text = self.bg_color_combo.currentText()
        if text == "Custom...":
            return self._custom_bg_color
        return BACKGROUND_COLORS.get(text, (0, 0, 0))

    def _get_cell_labels(self) -> str:
        text = self.cell_labels_combo.currentText()
        if text == "Frame Number":
            return "frame_number"
        elif text == "Timestamp":
            return "timestamp"
        return "none"

    def _get_fill_order(self) -> FillOrder:
        text = self.fill_order_combo.currentText()
        for order in FillOrder:
            if order.value == text:
                return order
        return FillOrder.STANDARD

    def _set_controls_enabled(self, enabled: bool):
        self.generate_btn.setEnabled(enabled)
        self.cols_spin.setEnabled(enabled)
        self.rows_spin.setEnabled(enabled)
        self.size_combo.setEnabled(enabled)
        self.skip_black_cb.setEnabled(enabled)
        self.format_combo.setEnabled(enabled)
        self.padding_spin.setEnabled(enabled)
        self.bg_color_combo.setEnabled(enabled)
        self.cell_labels_combo.setEnabled(enabled)
        self.fill_order_combo.setEnabled(enabled)
        self.grid_mode_combo.setEnabled(enabled)
        self.qt_depth_spin.setEnabled(enabled)
        self.qt_style_combo.setEnabled(enabled)
        self.qt_seed_spin.setEnabled(enabled)
        self.hl_timestamp_edit.setEnabled(enabled)
        self.hl_pick_btn.setEnabled(enabled and self._video_info is not None)
        self.hl_boost_spin.setEnabled(enabled)

    def _generate(self):
        video_path = self.video_path_edit.text()
        if not video_path or not os.path.isfile(video_path):
            QMessageBox.warning(self, "Error", "Please select a valid video file.")
            return

        output_path = self.output_path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "Error", "Please specify an output file path.")
            return

        rows = self.rows_spin.value()
        cols = self.cols_spin.value()
        output_w = self.width_spin.value()
        output_h = self.height_spin.value()
        skip_black = self.skip_black_cb.isChecked()

        # Format params
        fmt_name = self.format_combo.currentText()
        fmt_info = OUTPUT_FORMATS.get(fmt_name, OUTPUT_FORMATS["PNG"])
        output_format = fmt_info["format"]
        jpeg_quality = self.quality_spin.value()

        # Styling params
        padding = self.padding_spin.value()
        background_color = self._get_background_color()
        cell_labels = self._get_cell_labels()

        # Cell aspect ratio
        cell_aspect_ratio = self._get_cell_aspect_ratio()

        # Video duration for timestamps
        video_duration = self._video_info.duration if self._video_info else 0.0

        # Quadtree or standard mode
        cell_rects = None
        total_frames_override = None
        fill_positions = None
        highlight_timestamps = None
        highlight_cell_indices = None

        if self._is_quadtree_mode():
            cell_rects = cells_to_pixel_rects(
                self._quadtree_cells, output_w, output_h, padding=padding,
            )
            total_frames_override = len(self._quadtree_cells)

            # Highlights in quadtree mode
            if self._highlight_timestamps:
                hl_count = len(self._highlight_timestamps)
                if hl_count > len(self._quadtree_cells):
                    QMessageBox.warning(
                        self,
                        "Too Many Highlights",
                        f"You have {hl_count} highlights but only "
                        f"{len(self._quadtree_cells)} cells. "
                        f"Using the first {len(self._quadtree_cells)}.",
                    )
                highlight_timestamps = self._highlight_timestamps[:]
                highlight_cell_indices = assign_highlights_to_cells(
                    self._quadtree_cells,
                    len(highlight_timestamps),
                )
        else:
            fill_order = self._get_fill_order()
            fill_positions = compute_fill_order(rows, cols, fill_order)

        self._set_controls_enabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting...")

        self._worker = GenerateWorker(
            video_path,
            rows,
            cols,
            output_w,
            output_h,
            skip_black,
            output_path,
            output_format=output_format,
            jpeg_quality=jpeg_quality,
            padding=padding,
            background_color=background_color,
            cell_labels=cell_labels,
            fill_positions=fill_positions,
            video_duration=video_duration,
            cell_rects=cell_rects,
            total_frames_override=total_frames_override,
            highlight_timestamps=highlight_timestamps,
            highlight_cell_indices=highlight_cell_indices,
            highlight_boost=self.hl_boost_spin.value(),
            cell_aspect_ratio=cell_aspect_ratio,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current: int, total: int, stage: str):
        if total > 0:
            pct = int(current / total * 100)
            self.progress_bar.setValue(pct)
        self.status_label.setText(f"{stage}... ({current}/{total})")

    def _on_finished(self, output_path: str):
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Done! Saved to {output_path}")
        self._set_controls_enabled(True)
        QMessageBox.information(
            self, "Complete", f"Fingerprint saved to:\n{output_path}"
        )

    def _on_error(self, message: str):
        self.progress_bar.setValue(0)
        self.status_label.setText("Error occurred")
        self._set_controls_enabled(True)
        QMessageBox.critical(self, "Error", f"Generation failed:\n{message}")
