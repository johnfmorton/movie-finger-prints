from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A collapsible section widget with a clickable header and togglable content area."""

    def __init__(self, title: str, expanded: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("collapsibleSection")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header button with disclosure triangle
        self._header = QPushButton(f"\u25bc  {title}")
        self._header.setObjectName("sectionHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._toggle)
        outer.addWidget(self._header)

        # Content area
        self._content = QWidget()
        self._content.setObjectName("sectionContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(14, 10, 14, 14)
        self._content_layout.setSpacing(8)
        outer.addWidget(self._content)

        self._title = title
        self._expanded = expanded
        if not expanded:
            self._content.setVisible(False)
            self._header.setText(f"\u25b6  {title}")

    def content_layout(self) -> QVBoxLayout:
        """Return the inner layout — drop-in replacement for QGroupBox's layout."""
        return self._content_layout

    def _toggle(self):
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        arrow = "\u25bc" if self._expanded else "\u25b6"
        self._header.setText(f"{arrow}  {self._title}")
