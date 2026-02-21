from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import QWidget

from core.fill_order import FillOrder, compute_fill_order
from core.quadtree import QuadCell


class GridPreviewWidget(QWidget):
    """Miniature numbered grid preview showing fill order with color gradient."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = 5
        self._cols = 5
        self._fill_order = FillOrder.STANDARD
        self._quadtree_cells: list[QuadCell] | None = None
        self._highlight_cells: list[int] = []
        self._weighted_rects: list[tuple[float, float, float, float]] | None = None
        self._weighted_highlight_indices: list[int] = []
        self.setMinimumHeight(120)
        self.setMaximumHeight(200)

    def set_grid(self, rows: int, cols: int):
        self._rows = max(1, rows)
        self._cols = max(1, cols)
        self.update()

    def set_fill_order(self, order: FillOrder):
        self._fill_order = order
        self.update()

    def set_quadtree_cells(self, cells: list[QuadCell]):
        self._quadtree_cells = cells
        self.update()

    def clear_quadtree(self):
        self._quadtree_cells = None
        self._highlight_cells = []
        self._weighted_rects = None
        self._weighted_highlight_indices = []
        self.update()

    def set_weighted_cells(
        self,
        rows: int,
        cols: int,
        weights: list[float],
        highlight_indices: list[int],
    ):
        """Compute normalized rects from weights for weighted grid preview."""
        total_frames = len(weights)
        rects: list[tuple[float, float, float, float]] = []

        # Chunk weights into rows
        row_weights: list[list[float]] = []
        for r in range(rows):
            start = r * cols
            end = min(start + cols, total_frames)
            row_weights.append(weights[start:end])

        row_sums = [sum(rw) for rw in row_weights]
        total_weight = sum(row_sums)
        if total_weight <= 0:
            total_weight = 1.0

        y = 0.0
        for r, rw in enumerate(row_weights):
            row_sum = row_sums[r]
            row_h = row_sum / total_weight if total_weight > 0 else 1.0 / rows
            x = 0.0
            for w in rw:
                frame_w = w / row_sum if row_sum > 0 else 1.0 / cols
                rects.append((x, y, frame_w, row_h))
                x += frame_w
            y += row_h

        self._weighted_rects = rects
        self._weighted_highlight_indices = list(highlight_indices)
        self.update()

    def clear_weighted_cells(self):
        self._weighted_rects = None
        self._weighted_highlight_indices = []
        self.update()

    def set_highlight_cells(self, indices: list[int]):
        self._highlight_cells = list(indices)
        self.update()

    def paintEvent(self, event):
        if self._quadtree_cells is not None:
            self._paint_quadtree()
        elif self._weighted_rects is not None:
            self._paint_weighted_grid()
        else:
            self._paint_uniform_grid()

    def _paint_uniform_grid(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 4

        available_w = w - 2 * margin
        available_h = h - 2 * margin

        cell_w = available_w / self._cols
        cell_h = available_h / self._rows

        positions = compute_fill_order(self._rows, self._cols, self._fill_order)
        total = len(positions)

        # Build a map from (row, col) -> frame index
        pos_to_idx = {}
        for idx, (r, c) in enumerate(positions):
            pos_to_idx[(r, c)] = idx

        # Color gradient: cool blue (#3b82f6) -> warm orange (#f97316)
        color_start = QColor(59, 130, 246)
        color_end = QColor(249, 115, 22)

        pen = QPen(QColor(40, 40, 40), 1)
        painter.setPen(pen)

        font = QFont()
        font.setPixelSize(max(8, min(int(cell_h * 0.45), int(cell_w * 0.4), 14)))
        painter.setFont(font)

        for r in range(self._rows):
            for c in range(self._cols):
                x = margin + c * cell_w
                y = margin + r * cell_h

                idx = pos_to_idx.get((r, c), 0)
                t = idx / max(1, total - 1)

                # Interpolate color
                red = int(color_start.red() + t * (color_end.red() - color_start.red()))
                green = int(color_start.green() + t * (color_end.green() - color_start.green()))
                blue = int(color_start.blue() + t * (color_end.blue() - color_start.blue()))
                fill_color = QColor(red, green, blue)

                painter.setBrush(fill_color)
                painter.drawRect(int(x), int(y), int(cell_w), int(cell_h))

                # Draw number only if cells are large enough
                if cell_w >= 18 and cell_h >= 14:
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawText(
                        int(x), int(y), int(cell_w), int(cell_h),
                        Qt.AlignmentFlag.AlignCenter,
                        str(idx + 1),
                    )
                    painter.setPen(pen)

        painter.end()

    def _paint_weighted_grid(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 4

        available_w = w - 2 * margin
        available_h = h - 2 * margin

        rects = self._weighted_rects
        total = len(rects)

        color_start = QColor(59, 130, 246)
        color_end = QColor(249, 115, 22)

        pen = QPen(QColor(40, 40, 40), 1)
        painter.setPen(pen)

        for idx, (rx, ry, rw, rh) in enumerate(rects):
            px = margin + rx * available_w
            py = margin + ry * available_h
            pw = rw * available_w
            ph = rh * available_h

            t = idx / max(1, total - 1)
            red = int(color_start.red() + t * (color_end.red() - color_start.red()))
            green = int(color_start.green() + t * (color_end.green() - color_start.green()))
            blue = int(color_start.blue() + t * (color_end.blue() - color_start.blue()))
            fill_color = QColor(red, green, blue)

            painter.setBrush(fill_color)
            painter.drawRect(int(px), int(py), int(pw), int(ph))

            # Gold highlight border on key frames
            if idx in self._weighted_highlight_indices:
                gold_pen = QPen(QColor(255, 215, 0), 2)
                painter.setPen(gold_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(
                    int(px) + 1, int(py) + 1,
                    int(pw) - 2, int(ph) - 2,
                )
                painter.setPen(pen)

            # Draw number when cells are large enough
            if pw >= 18 and ph >= 14:
                font = QFont()
                font.setPixelSize(max(8, min(int(ph * 0.45), int(pw * 0.4), 14)))
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(
                    int(px), int(py), int(pw), int(ph),
                    Qt.AlignmentFlag.AlignCenter,
                    str(idx + 1),
                )
                painter.setPen(pen)

        painter.end()

    def _paint_quadtree(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 4

        available_w = w - 2 * margin
        available_h = h - 2 * margin

        cells = self._quadtree_cells
        total = len(cells)

        color_start = QColor(59, 130, 246)
        color_end = QColor(249, 115, 22)

        pen = QPen(QColor(40, 40, 40), 1)
        painter.setPen(pen)

        for idx, cell in enumerate(cells):
            px = margin + cell.x * available_w
            py = margin + cell.y * available_h
            pw = cell.w * available_w
            ph = cell.h * available_h

            t = idx / max(1, total - 1)
            red = int(color_start.red() + t * (color_end.red() - color_start.red()))
            green = int(color_start.green() + t * (color_end.green() - color_start.green()))
            blue = int(color_start.blue() + t * (color_end.blue() - color_start.blue()))
            fill_color = QColor(red, green, blue)

            painter.setBrush(fill_color)
            painter.drawRect(int(px), int(py), int(pw), int(ph))

            # Draw gold highlight border on selected cells
            if idx in self._highlight_cells:
                gold_pen = QPen(QColor(255, 215, 0), 2)  # #FFD700
                painter.setPen(gold_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(
                    int(px) + 1, int(py) + 1,
                    int(pw) - 2, int(ph) - 2,
                )
                painter.setPen(pen)

            # Draw number when cells are large enough
            if pw >= 18 and ph >= 14:
                font = QFont()
                font.setPixelSize(max(8, min(int(ph * 0.45), int(pw * 0.4), 14)))
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(
                    int(px), int(py), int(pw), int(ph),
                    Qt.AlignmentFlag.AlignCenter,
                    str(idx + 1),
                )
                painter.setPen(pen)

        painter.end()
