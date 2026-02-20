from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.video import VideoInfo


class ThumbnailStripWorker(QThread):
    """Extracts ~20 evenly-spaced frames for the overview strip."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list, list)
    error = pyqtSignal(str)

    def __init__(
        self, video_path: str, duration: float, tmp_dir: str, count: int = 20
    ):
        super().__init__()
        self._video_path = video_path
        self._duration = duration
        self._tmp_dir = tmp_dir
        self._count = count

    def run(self):
        try:
            paths: list[str] = []
            timestamps: list[float] = []
            for i in range(self._count):
                ts = (i + 0.5) * self._duration / self._count
                ts = min(ts, self._duration - 0.01)
                out_path = os.path.join(self._tmp_dir, f"strip_{i:03d}.jpg")
                cmd = [
                    "ffmpeg",
                    "-v", "quiet",
                    "-ss", str(ts),
                    "-i", self._video_path,
                    "-frames:v", "1",
                    "-q:v", "2",
                    out_path,
                ]
                result = subprocess.run(cmd, capture_output=True)
                if result.returncode == 0 and os.path.isfile(out_path):
                    paths.append(out_path)
                    timestamps.append(ts)
                self.progress.emit(i + 1, self._count)
            self.finished.emit(paths, timestamps)
        except Exception as e:
            self.error.emit(str(e))


class SingleFrameWorker(QThread):
    """Extracts one frame at a given timestamp for the large preview."""

    finished = pyqtSignal(str, float)
    error = pyqtSignal(str)

    def __init__(self, video_path: str, timestamp: float, tmp_dir: str):
        super().__init__()
        self._video_path = video_path
        self._timestamp = timestamp
        self._tmp_dir = tmp_dir

    def run(self):
        try:
            out_path = os.path.join(
                self._tmp_dir, f"preview_{self._timestamp:.3f}.jpg"
            )
            if os.path.isfile(out_path):
                self.finished.emit(out_path, self._timestamp)
                return
            cmd = [
                "ffmpeg",
                "-v", "quiet",
                "-ss", str(self._timestamp),
                "-i", self._video_path,
                "-frames:v", "1",
                "-q:v", "2",
                out_path,
            ]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode == 0 and os.path.isfile(out_path):
                self.finished.emit(out_path, self._timestamp)
            else:
                self.error.emit("Failed to extract preview frame")
        except Exception as e:
            self.error.emit(str(e))


class ClickableThumbnail(QLabel):
    """Small clickable thumbnail widget."""

    clicked = pyqtSignal(float)

    def __init__(self, timestamp: float, parent: QWidget | None = None):
        super().__init__(parent)
        self._timestamp = timestamp
        self.setFixedSize(80, 45)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            "border: 1px solid #555; background: #222;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_image(self, path: str):
        pix = QPixmap(path).scaled(
            80, 45,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pix)

    def mousePressEvent(self, ev):
        self.clicked.emit(self._timestamp)


class FramePickerDialog(QDialog):
    """Modal dialog for visually browsing and selecting highlight frames."""

    def __init__(
        self,
        video_path: str,
        video_info: VideoInfo,
        existing_timestamps: list[float] | None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Pick Highlight Frames")
        self.setMinimumSize(700, 550)

        self._video_path = video_path
        self._video_info = video_info
        self._selected_timestamps: list[float] = sorted(
            existing_timestamps or []
        )
        self._tmp_dir = tempfile.mkdtemp(prefix="frame_picker_")
        self._frame_cache: dict[float, str] = {}
        self._strip_worker: ThumbnailStripWorker | None = None
        self._preview_worker: SingleFrameWorker | None = None

        # Compute ms per frame for step buttons / keyboard nav
        if video_info.frame_count > 0 and video_info.duration > 0:
            self._frame_duration_ms = video_info.duration / video_info.frame_count * 1000
        else:
            self._frame_duration_ms = 33.3  # fallback ~30fps

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(200)
        self._debounce_timer.timeout.connect(self._extract_preview_frame)

        self._build_ui()

    # ---- UI construction ----

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 1. Thumbnail overview strip
        strip_help = QLabel(
            "Quick Navigation — Click a thumbnail to jump to that "
            "part of the video."
        )
        strip_help.setWordWrap(True)
        strip_help.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(strip_help)

        self._strip_loading_label = QLabel("Loading thumbnails...")
        self._strip_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._strip_loading_label)

        self._strip_scroll = QScrollArea()
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setFixedHeight(65)
        self._strip_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self._strip_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        strip_container = QWidget()
        self._strip_layout = QHBoxLayout(strip_container)
        self._strip_layout.setContentsMargins(2, 2, 2, 2)
        self._strip_layout.setSpacing(4)
        self._strip_layout.addStretch()
        self._strip_scroll.setWidget(strip_container)
        self._strip_scroll.setVisible(False)
        layout.addWidget(self._strip_scroll)

        # 2. Large preview
        preview_help = QLabel(
            "Frame Preview — Use the slider or step buttons to find "
            "the exact frame. Arrow keys step 1 frame; "
            "Option+Arrow steps 10 frames."
        )
        preview_help.setWordWrap(True)
        preview_help.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(preview_help)

        self._preview_label = QLabel("Select a position to preview")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(300)
        self._preview_label.setStyleSheet(
            "border: 1px solid #444; background: #111;"
        )
        layout.addWidget(self._preview_label, stretch=1)

        # 3. Slider row
        slider_row = QHBoxLayout()
        duration_ms = int(self._video_info.duration * 1000)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, max(duration_ms, 1))
        self._slider.setValue(0)
        self._slider.valueChanged.connect(self._on_slider_changed)
        slider_row.addWidget(self._slider, stretch=1)
        self._time_label = QLabel(self._format_time(0))
        self._time_label.setFixedWidth(70)
        slider_row.addWidget(self._time_label)
        layout.addLayout(slider_row)

        # 4. Frame step buttons
        step_row = QHBoxLayout()
        step_row.addStretch()

        btn_back_30 = QPushButton("\u25c0\u25c0 30")
        btn_back_30.setToolTip("Jump back 30 frames")
        btn_back_30.clicked.connect(lambda: self._step_frames(-30))
        step_row.addWidget(btn_back_30)

        btn_back_10 = QPushButton("\u25c0 10")
        btn_back_10.setToolTip("Jump back 10 frames")
        btn_back_10.clicked.connect(lambda: self._step_frames(-10))
        step_row.addWidget(btn_back_10)

        btn_back_1 = QPushButton("\u25c0 1")
        btn_back_1.setToolTip("Jump back 1 frame")
        btn_back_1.clicked.connect(lambda: self._step_frames(-1))
        step_row.addWidget(btn_back_1)

        btn_fwd_1 = QPushButton("1 \u25b6")
        btn_fwd_1.setToolTip("Jump forward 1 frame")
        btn_fwd_1.clicked.connect(lambda: self._step_frames(1))
        step_row.addWidget(btn_fwd_1)

        btn_fwd_10 = QPushButton("10 \u25b6")
        btn_fwd_10.setToolTip("Jump forward 10 frames")
        btn_fwd_10.clicked.connect(lambda: self._step_frames(10))
        step_row.addWidget(btn_fwd_10)

        btn_fwd_30 = QPushButton("30 \u25b6\u25b6")
        btn_fwd_30.setToolTip("Jump forward 30 frames")
        btn_fwd_30.clicked.connect(lambda: self._step_frames(30))
        step_row.addWidget(btn_fwd_30)

        step_row.addStretch()
        layout.addLayout(step_row)

        # 5. Selected frames strip
        sel_label = QLabel("Selected:")
        layout.addWidget(sel_label)

        sel_row = QHBoxLayout()
        self._sel_scroll = QScrollArea()
        self._sel_scroll.setWidgetResizable(True)
        self._sel_scroll.setFixedHeight(80)
        self._sel_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._sel_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        sel_container = QWidget()
        self._sel_layout = QHBoxLayout(sel_container)
        self._sel_layout.setContentsMargins(2, 2, 2, 2)
        self._sel_layout.setSpacing(4)
        self._sel_layout.addStretch()
        self._sel_scroll.setWidget(sel_container)
        sel_row.addWidget(self._sel_scroll, stretch=1)

        self._add_btn = QPushButton("+ Add Current Frame")
        self._add_btn.clicked.connect(self._add_current_frame)
        sel_row.addWidget(self._add_btn)
        layout.addLayout(sel_row)

        # 5. Button row
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        btn_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self.accept
        )
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ---- Lifecycle ----

    def showEvent(self, event):
        super().showEvent(event)
        self._start_thumbnail_extraction()

    def _start_thumbnail_extraction(self):
        if self._strip_worker is not None:
            return
        self._strip_worker = ThumbnailStripWorker(
            self._video_path, self._video_info.duration, self._tmp_dir
        )
        self._strip_worker.progress.connect(self._on_strip_progress)
        self._strip_worker.finished.connect(self._on_strip_finished)
        self._strip_worker.error.connect(self._on_strip_error)
        self._strip_worker.start()

    def _on_strip_progress(self, current: int, total: int):
        self._strip_loading_label.setText(
            f"Loading thumbnails... {current}/{total}"
        )

    def _on_strip_finished(self, paths: list[str], timestamps: list[float]):
        self._strip_loading_label.setVisible(False)
        self._strip_scroll.setVisible(True)

        # Remove the trailing stretch
        stretch_item = self._strip_layout.takeAt(
            self._strip_layout.count() - 1
        )
        if stretch_item:
            del stretch_item

        for path, ts in zip(paths, timestamps):
            self._frame_cache[round(ts, 1)] = path
            thumb = ClickableThumbnail(ts, self)
            thumb.set_image(path)
            thumb.clicked.connect(self._on_thumbnail_clicked)
            self._strip_layout.addWidget(thumb)

        self._strip_layout.addStretch()

        # Show first frame as preview
        if paths:
            self._show_preview(paths[0])

        # Rebuild selected strip now that cache has frames
        self._rebuild_selected_strip()

    def _on_strip_error(self, msg: str):
        self._strip_loading_label.setText(f"Error loading thumbnails: {msg}")

    # ---- Slider ----

    def _on_slider_changed(self, value_ms: int):
        ts = value_ms / 1000.0
        self._time_label.setText(self._format_time(ts))
        self._debounce_timer.start()

    def _extract_preview_frame(self):
        ts = self._slider.value() / 1000.0
        cache_key = round(ts, 1)
        if cache_key in self._frame_cache:
            self._show_preview(self._frame_cache[cache_key])
            return

        # Stop previous worker if still running
        if self._preview_worker is not None and self._preview_worker.isRunning():
            self._preview_worker.quit()
            self._preview_worker.wait(500)

        self._preview_worker = SingleFrameWorker(
            self._video_path, ts, self._tmp_dir
        )
        self._preview_worker.finished.connect(self._on_preview_finished)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()

    def _on_preview_finished(self, path: str, timestamp: float):
        self._frame_cache[round(timestamp, 1)] = path
        self._show_preview(path)

    def _on_preview_error(self, msg: str):
        self._preview_label.setText(f"Preview error: {msg}")

    def _show_preview(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            return
        scaled = pix.scaled(
            self._preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)

    # ---- Frame stepping ----

    def _step_frames(self, count: int):
        delta = int(round(count * self._frame_duration_ms))
        new_val = max(0, min(self._slider.value() + delta, self._slider.maximum()))
        self._slider.setValue(new_val)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            alt = event.modifiers() & Qt.KeyboardModifier.AltModifier
            step = 10 if alt else 1
            if event.key() == Qt.Key.Key_Left:
                step = -step
            self._step_frames(step)
            event.accept()
            return
        super().keyPressEvent(event)

    # ---- Thumbnail click ----

    def _on_thumbnail_clicked(self, timestamp: float):
        ms = int(timestamp * 1000)
        self._slider.setValue(ms)

    # ---- Selected frames ----

    def _add_current_frame(self):
        ts = round(self._slider.value() / 1000.0, 2)
        if ts in self._selected_timestamps:
            return
        self._selected_timestamps.append(ts)
        self._selected_timestamps.sort()
        self._rebuild_selected_strip()

    def _remove_timestamp(self, timestamp: float):
        if timestamp in self._selected_timestamps:
            self._selected_timestamps.remove(timestamp)
            self._rebuild_selected_strip()

    def _rebuild_selected_strip(self):
        # Clear existing widgets
        while self._sel_layout.count():
            item = self._sel_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for ts in self._selected_timestamps:
            frame_widget = QWidget()
            frame_layout = QVBoxLayout(frame_widget)
            frame_layout.setContentsMargins(0, 0, 0, 0)
            frame_layout.setSpacing(2)

            thumb = ClickableThumbnail(ts, frame_widget)
            thumb.clicked.connect(self._on_thumbnail_clicked)

            # Try to find a cached image for this timestamp
            cache_key = round(ts, 1)
            if cache_key in self._frame_cache:
                thumb.set_image(self._frame_cache[cache_key])

            frame_layout.addWidget(thumb)

            info_row = QHBoxLayout()
            info_row.setContentsMargins(0, 0, 0, 0)
            time_lbl = QLabel(self._format_time(ts))
            time_lbl.setStyleSheet("font-size: 10px;")
            info_row.addWidget(time_lbl)

            remove_btn = QPushButton("X")
            remove_btn.setFixedSize(18, 18)
            remove_btn.setStyleSheet("font-size: 10px; padding: 0;")
            remove_btn.clicked.connect(lambda _, t=ts: self._remove_timestamp(t))
            info_row.addWidget(remove_btn)
            frame_layout.addLayout(info_row)

            self._sel_layout.addWidget(frame_widget)

        self._sel_layout.addStretch()

    # ---- Dialog result ----

    def get_timestamps(self) -> list[float]:
        return list(self._selected_timestamps)

    def accept(self):
        super().accept()

    def reject(self):
        self._selected_timestamps.clear()
        super().reject()

    def closeEvent(self, event):
        self._debounce_timer.stop()
        if self._strip_worker is not None and self._strip_worker.isRunning():
            self._strip_worker.quit()
            self._strip_worker.wait(1000)
        if self._preview_worker is not None and self._preview_worker.isRunning():
            self._preview_worker.quit()
            self._preview_worker.wait(1000)
        if os.path.isdir(self._tmp_dir):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        super().closeEvent(event)

    # ---- Helpers ----

    @staticmethod
    def _format_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:05.2f}"
        return f"{m}:{s:05.2f}"
