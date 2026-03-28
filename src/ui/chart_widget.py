"""Chart and visualization widgets for DiskExplorer (PyQt6)."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..models import FileNode, format_size

# Colour palette for pie chart slices
_PALETTE = [
    QColor("#4299e1"),
    QColor("#48bb78"),
    QColor("#ed8936"),
    QColor("#9f7aea"),
    QColor("#f56565"),
    QColor("#38b2ac"),
    QColor("#ed64a6"),
    QColor("#667eea"),
    QColor("#f6ad55"),
    QColor("#68d391"),
]


class PieChartWidget(QWidget):
    """Draws a simple pie chart from a name→size mapping."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._slices: List[Tuple[str, int]] = []
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: Dict[str, int]) -> None:
        """Update chart data.  Keys are labels, values are sizes in bytes."""
        total = sum(data.values())
        if total == 0:
            self._slices = []
            self.update()
            return

        # Sort descending, keep top-9, group rest as "Other"
        sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
        top = sorted_items[:9]
        rest = sorted_items[9:]
        if rest:
            other_size = sum(v for _, v in rest)
            top.append(("Other", other_size))
        self._slices = top
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._slices:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        total = sum(s for _, s in self._slices)
        if total == 0:
            return

        size = min(self.width(), self.height()) - 60
        x = (self.width() - size) // 2
        y = (self.height() - size) // 2
        rect = QRectF(x, y, size, size)

        start_angle = 90 * 16  # Qt uses 1/16 degrees
        for i, (label, value) in enumerate(self._slices):
            span = int(value / total * 360 * 16)
            color = _PALETTE[i % len(_PALETTE)]
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.GlobalColor.white, 1))
            painter.drawPie(rect, start_angle, span)
            start_angle += span

        painter.end()


class BarChartWidget(QWidget):
    """Draws a horizontal bar chart of the top children by size."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: List[Tuple[str, int, int]] = []  # (name, size, total)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_data(self, items: List[Tuple[str, int]], total: int) -> None:
        self._items = [(name, size, total) for name, size in items]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._items:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        padding = 10
        label_width = 160
        bar_height = 18
        gap = 6
        available_width = self.width() - padding * 2 - label_width - 80

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)

        for i, (name, size, total) in enumerate(self._items[:12]):
            y = padding + i * (bar_height + gap)
            if y + bar_height > self.height() - padding:
                break

            # Label
            painter.setPen(QColor("#333"))
            truncated = name if len(name) <= 20 else name[:17] + "…"
            painter.drawText(padding, y, label_width, bar_height,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             truncated)

            # Bar background
            bx = padding + label_width
            painter.setBrush(QBrush(QColor("#e2e8f0")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bx, y, available_width, bar_height, 3, 3)

            # Bar fill
            pct = size / total if total > 0 else 0
            fill_w = int(available_width * pct)
            color = _PALETTE[i % len(_PALETTE)]
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(bx, y, max(fill_w, 2), bar_height, 3, 3)

            # Size label
            painter.setPen(QColor("#333"))
            painter.drawText(bx + available_width + 4, y, 75, bar_height,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             format_size(size))

        painter.end()


class SizeChartWidget(QWidget):
    """Container that shows a title, pie chart and bar chart for a FileNode."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._title_label = QLabel("Select a folder to see its contents")
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self._title_label.setFont(font)
        layout.addWidget(self._title_label)

        self._info_label = QLabel("")
        layout.addWidget(self._info_label)

        self._pie = PieChartWidget()
        layout.addWidget(self._pie, stretch=2)

        self._bar = BarChartWidget()
        layout.addWidget(self._bar, stretch=3)

        self.setMinimumWidth(300)

    def display(self, node: Optional[FileNode]) -> None:
        if node is None:
            self._title_label.setText("No data")
            self._info_label.setText("")
            self._pie.set_data({})
            self._bar.set_data([], 0)
            return

        self._title_label.setText(node.name)
        info_parts = [node.formatted_size]
        if node.is_dir:
            info_parts.append(f"{node.file_count} files")
        self._info_label.setText("  |  ".join(info_parts))

        if node.is_dir and node.children:
            children_data = {
                child.name: child.size
                for child in node.get_children_sorted("size")[:10]
            }
            self._pie.set_data(children_data)
            bar_items = [(child.name, child.size)
                         for child in node.get_children_sorted("size")[:12]]
            self._bar.set_data(bar_items, node.size)
        else:
            # Leaf file – show type distribution of parent if available
            type_dist = node.type_distribution()
            self._pie.set_data(type_dist)
            self._bar.set_data(list(type_dist.items())[:12], node.size)
