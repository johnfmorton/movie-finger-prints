import os
import shutil
import tempfile

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from core.video import extract_frames, probe_video


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
    ):
        super().__init__()
        self.video_path = video_path
        self.rows = rows
        self.cols = cols
        self.output_width = output_width
        self.output_height = output_height
        self.skip_black = skip_black
        self.output_path = output_path
        self._tmp_dir = None

    def run(self):
        try:
            total_frames = self.rows * self.cols

            def on_progress(current, total):
                self.progress.emit(current, total, "Extracting frames")

            frame_paths = extract_frames(
                self.video_path,
                total_frames,
                skip_black=self.skip_black,
                progress_callback=on_progress,
            )

            self.progress.emit(0, 1, "Compositing image")

            compose_grid(
                frame_paths,
                self.rows,
                self.cols,
                self.output_width,
                self.output_height,
                self.output_path,
            )

            # Clean up temp frames
            if frame_paths:
                self._tmp_dir = os.path.dirname(frame_paths[0])
                shutil.rmtree(self._tmp_dir, ignore_errors=True)

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
        grid_layout = QHBoxLayout(grid_group)

        grid_layout.addWidget(QLabel("Columns:"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 200)
        self.cols_spin.setValue(30)
        self.cols_spin.valueChanged.connect(self._update_total_frames)
        grid_layout.addWidget(self.cols_spin)

        grid_layout.addSpacing(20)

        grid_layout.addWidget(QLabel("Rows:"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 200)
        self.rows_spin.setValue(20)
        self.rows_spin.valueChanged.connect(self._update_total_frames)
        grid_layout.addWidget(self.rows_spin)

        grid_layout.addSpacing(20)

        self.total_frames_label = QLabel("Total frames: 600")
        grid_layout.addWidget(self.total_frames_label)
        grid_layout.addStretch()
        layout.addWidget(grid_group)

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

        layout.addWidget(output_group)

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
            default_output = os.path.join(video_dir, f"{video_name}_fingerprint.png")
            self.output_path_edit.setText(default_output)

            self.status_label.setText(
                f"Loaded: {self._video_info.width}x{self._video_info.height}, "
                f"{self._video_info.duration:.1f}s, ~{self._video_info.frame_count} frames"
            )
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to probe video:\n{e}")
            self._video_info = None

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Output", "", "PNG Files (*.png);;All Files (*)"
        )
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            self.output_path_edit.setText(path)

    def _update_total_frames(self):
        total = self.cols_spin.value() * self.rows_spin.value()
        self.total_frames_label.setText(f"Total frames: {total}")

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

    def _set_controls_enabled(self, enabled: bool):
        self.generate_btn.setEnabled(enabled)
        self.cols_spin.setEnabled(enabled)
        self.rows_spin.setEnabled(enabled)
        self.size_combo.setEnabled(enabled)
        self.skip_black_cb.setEnabled(enabled)

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

        self._set_controls_enabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting...")

        self._worker = GenerateWorker(
            video_path, rows, cols, output_w, output_h, skip_black, output_path
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
