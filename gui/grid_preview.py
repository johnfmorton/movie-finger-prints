from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import QWidget

from core.fill_order import FillOrder, compute_fill_order


class GridPreviewWidget(QWidget):
    """Miniature numbered grid preview showing fill order with color gradient."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = 5
        self._cols = 5
        self._fill_order = FillOrder.STANDARD
        self.setMinimumHeight(120)
        self.setMaximumHeight(200)

    def set_grid(self, rows: int, cols: int):
        self._rows = max(1, rows)
        self._cols = max(1, cols)
        self.update()

    def set_fill_order(self, order: FillOrder):
        self._fill_order = order
        self.update()

    def paintEvent(self, event):
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
