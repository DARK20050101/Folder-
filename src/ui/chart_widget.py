"""Chart and visualization widgets for DiskExplorer (PyQt6)."""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget

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

_PIXEL_THEMES = {
    "meadow": {
        "bg": QColor("#f3f8ef"),
        "cover_fill": QColor("#fffdf8"),
        "accent": QColor("#9ec8a7"),
        "title": QColor("#48674a"),
    },
    "dungeon": {
        "bg": QColor("#1f2238"),
        "cover_fill": QColor("#1c2034"),
        "accent": QColor("#ff8ea1"),
        "title": QColor("#e2ecff"),
    },
}


class CoverWidget(QWidget):
    """Welcome cover that can show a custom image or a text poster."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._title = "Folder"
        self._subtitle = "让你的磁盘更干净"
        self._theme_key = "meadow"
        self._cover_image_path = ""
        self._cover_image = QPixmap()

    def set_cover_image(self, image_path: str) -> bool:
        image_path = (image_path or "").strip()
        if not image_path:
            self._cover_image_path = ""
            self._cover_image = QPixmap()
            self.update()
            return True
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return False
        self._cover_image_path = image_path
        self._cover_image = pixmap
        self.update()
        return True

    def cover_image_path(self) -> str:
        return self._cover_image_path

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = theme_key if theme_key in _PIXEL_THEMES else "meadow"
        self.update()

    def set_language(self, language: str) -> None:
        if language == "zh":
            self._title = "Folder"
            self._subtitle = "让你的磁盘更干净"
        else:
            self._title = "Folder"
            self._subtitle = "Make your disk cleaner"
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        theme = _PIXEL_THEMES[self._theme_key]

        if not self._cover_image.isNull():
            painter.fillRect(self.rect(), theme["cover_fill"])
            scaled = self._cover_image.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()
            return

        rect = self.rect()
        if self._theme_key == "meadow":
            # Keep outer background minimal so focus stays on the center card.
            painter.fillRect(rect, QColor("#E6F2E6"))
        else:
            painter.fillRect(rect, theme["bg"])

        # Subtle background atmosphere matching current theme.
        painter.setPen(Qt.PenStyle.NoPen)
        if self._theme_key == "meadow":
            # Intentionally no decorative blobs for meadow: cleaner outer frame.
            pass
        else:
            painter.setBrush(QColor(255, 255, 255, 20))
            painter.drawEllipse(rect.width() - 190, -26, 220, 150)
            painter.setBrush(QColor(255, 255, 255, 10))
            painter.drawEllipse(-80, rect.height() - 110, 210, 140)

        card_w = min(max(rect.width() - 72, 300), 640)
        card_h = min(max(rect.height() - 92, 190), 330)
        card_x = (rect.width() - card_w) // 2
        card_y = (rect.height() - card_h) // 2
        card = QRect(card_x, card_y, card_w, card_h)

        # Card shadow and body.
        if self._theme_key == "meadow":
            painter.setBrush(QColor(46, 94, 46, 30))
            painter.drawRoundedRect(card.adjusted(0, 4, 0, 4), 8, 8)
            painter.setBrush(QColor("#FFFFFF"))
        else:
            painter.setBrush(QColor(0, 0, 0, 42))
            painter.drawRoundedRect(card.adjusted(3, 5, 3, 5), 22, 22)
            painter.setBrush(theme["cover_fill"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(card, 8 if self._theme_key == "meadow" else 22, 8 if self._theme_key == "meadow" else 22)

        # Thin border for a clean UI look.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._theme_key == "meadow":
            painter.setPen(QPen(QColor(227, 238, 227), 1))
            painter.drawRoundedRect(card.adjusted(0, 0, -1, -1), 8, 8)
        else:
            painter.setPen(QPen(QColor(112, 132, 174, 220), 1.5))
            painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 21, 21)

        # Title/subtitle block: centered layout with controlled line-height ratio.
        content_rect = QRect(card_x + 34, card_y + 26, card_w - 68, card_h - 68)
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap

        max_title_width = content_rect.width()
        font_size = min(36, max(30, card_w // 14))
        title_font = QFont("Segoe UI", font_size)
        title_font.setWeight(QFont.Weight.Bold)
        metrics = QFontMetrics(title_font)

        while font_size > 22:
            bounds = metrics.boundingRect(content_rect, int(flags), self._title)
            if bounds.width() <= max_title_width:
                break
            font_size -= 1
            title_font = QFont("Segoe UI", font_size)
            title_font.setWeight(QFont.Weight.Bold)
            metrics = QFontMetrics(title_font)

        painter.setFont(title_font)
        painter.setPen(QColor("#2E5E2E") if self._theme_key == "meadow" else theme["title"])

        title_h = metrics.height()
        sub_font_size = min(26, max(22, int(font_size * 0.76)))
        sub_font = QFont("Segoe UI", sub_font_size)
        sub_font.setWeight(QFont.Weight.Medium)
        sub_metrics = QFontMetrics(sub_font)
        subtitle_h = sub_metrics.height()

        line_gap = int(max(title_h, subtitle_h) * 0.5)  # roughly 1.5x line-height
        total_h = title_h + subtitle_h + line_gap
        top_y = content_rect.y() + (content_rect.height() - total_h) // 2

        title_rect = QRect(content_rect.x(), top_y, content_rect.width(), title_h + 4)
        subtitle_rect = QRect(content_rect.x(), top_y + title_h + line_gap, content_rect.width(), subtitle_h + 4)

        painter.drawText(title_rect, int(flags), self._title)
        painter.setFont(sub_font)
        painter.drawText(subtitle_rect, int(flags), self._subtitle)

        # Bottom decorative line.
        painter.setPen(Qt.PenStyle.NoPen)
        if self._theme_key == "meadow":
            painter.setBrush(QColor("#A6D1A6"))
            line_w = min(180, int(card_w * 0.38))
            line_h = 2
            line_x = card_x + (card_w - line_w) // 2
            line_y = card_y + card_h - 24
            painter.drawRect(line_x, line_y, line_w, line_h)
        else:
            painter.setBrush(QColor(theme["accent"].red(), theme["accent"].green(), theme["accent"].blue(), 130))
            painter.drawRoundedRect(card_x + card_w - 190, card_y + card_h - 24, 150, 6, 3, 3)

        painter.end()


class ComparisonChartWidget(QWidget):
    """Clickable delta chart used by manual comparison mode."""

    path_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[Tuple[str, str, int, int]] = []  # (name, path, current_size, previous_size)
        self._title = ""
        self._language = "en"
        self._row_hit_areas: List[Tuple[QRect, str]] = []
        self._selected_path: Optional[str] = None

    def set_language(self, language: str) -> None:
        self._language = language
        self.update()

    def set_data(self, title: str, rows: List[Tuple[str, str, int, int]], selected_path: Optional[str]) -> None:
        self._title = title
        self._rows = rows[:16]
        self._selected_path = selected_path
        self.update()

    def content_height(self) -> int:
        row_height = 18
        gap = 8
        base_y = 56
        return base_y + len(self._rows) * (row_height + gap) + 48

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        for rect, path in self._row_hit_areas:
            if rect.contains(pos):
                self.path_clicked.emit(path)
                return

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._row_hit_areas = []

        if not self._rows:
            painter.fillRect(self.rect(), QColor("#fafcff"))
            painter.setPen(QColor("#44526e"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "暂无对比数据" if self._language == "zh" else "No comparison data.",
            )
            painter.end()
            return

        painter.fillRect(self.rect(), QColor("#f9fcff"))
        margin = 14
        title_font = QFont("Segoe UI", 11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#1f2f4b"))
        painter.drawText(margin, margin, self.width() - margin * 2, 24, Qt.AlignmentFlag.AlignLeft, self._title)

        base_y = 56
        bar_height = 18
        gap = 8
        left_label_w = 190
        right_label_w = 170
        chart_x = margin + left_label_w
        chart_w = max(self.width() - chart_x - right_label_w - margin, 160)
        mid_x = chart_x + chart_w // 2

        max_abs_delta = max(abs(cur - prev) for _, _, cur, prev in self._rows) or 1
        painter.setPen(QPen(QColor("#a9b7cd"), 1))
        painter.drawLine(mid_x, base_y - 8, mid_x, base_y + len(self._rows) * (bar_height + gap))

        font = QFont("Segoe UI", 8)
        painter.setFont(font)

        for i, (name, path, cur, prev) in enumerate(self._rows):
            y = base_y + i * (bar_height + gap)
            delta = cur - prev
            ratio = abs(delta) / max_abs_delta
            draw_w = int((chart_w // 2 - 6) * ratio)

            label = name if len(name) <= 26 else name[:23] + "..."
            painter.setPen(QColor("#2f3d59"))
            painter.drawText(margin, y, left_label_w - 6, bar_height, Qt.AlignmentFlag.AlignVCenter, label)

            if delta >= 0:
                painter.setBrush(QColor("#ff8b8b"))
                bar_rect = QRect(mid_x, y, max(draw_w, 2), bar_height)
            else:
                painter.setBrush(QColor("#6bcf90"))
                bar_rect = QRect(mid_x - max(draw_w, 2), y, max(draw_w, 2), bar_height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bar_rect, 4, 4)

            selected = (path == self._selected_path)
            if selected:
                painter.setPen(QPen(QColor("#2f80ff"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRect(margin - 2, y - 2, self.width() - margin * 2 + 4, bar_height + 4), 4, 4)

            detail = f"{format_size(prev)} -> {format_size(cur)}  ({'+' if delta >= 0 else ''}{format_size(delta)})"
            painter.setPen(QColor("#334155"))
            painter.drawText(
                chart_x + chart_w + 8,
                y,
                right_label_w,
                bar_height,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                detail,
            )

            self._row_hit_areas.append((QRect(margin, y - 1, self.width() - margin * 2, bar_height + 2), path))

        guide_y = base_y + len(self._rows) * (bar_height + gap) + 8
        painter.setPen(QColor("#4d617f"))
        guide = "点击条目定位目录" if self._language == "zh" else "Click a bar to locate the folder"
        painter.drawText(margin, guide_y, self.width() - margin * 2, 20, Qt.AlignmentFlag.AlignLeft, guide)
        painter.end()


class HistoryTrendChartWidget(QWidget):
    """Clickable historical trend lines for level-1/level-2 directories."""

    path_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._row_h = 36
        self._gap = 8
        self._base_y = 56
        self._rows: List[Tuple[str, str, List[int]]] = []  # (name, full_path, series)
        self._x_labels: List[str] = []
        self._title = ""
        self._language = "en"
        self._row_hit_areas: List[Tuple[QRect, str]] = []

    def set_language(self, language: str) -> None:
        self._language = language
        self.update()

    def set_data(self, title: str, rows: List[Tuple[str, str, List[int]]], x_labels: List[str]) -> None:
        self._title = title
        self._rows = list(rows)
        self._x_labels = x_labels
        self.update()

    def content_height(self) -> int:
        return self._base_y + len(self._rows) * (self._row_h + self._gap) + 50

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        for rect, path in self._row_hit_areas:
            if rect.contains(pos):
                self.path_clicked.emit(path)
                return

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._row_hit_areas = []

        painter.fillRect(self.rect(), QColor("#f8fbff"))
        if not self._rows:
            painter.setPen(QColor("#44526e"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "暂无历史变化数据" if self._language == "zh" else "No history trend data.",
            )
            painter.end()
            return

        margin = 14
        title_font = QFont("Segoe UI", 11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#1f2f4b"))
        painter.drawText(margin, margin, self.width() - margin * 2, 24, Qt.AlignmentFlag.AlignLeft, self._title)

        base_y = self._base_y
        row_h = self._row_h
        gap = self._gap
        left_label_w = 210
        right_info_w = 150
        chart_x = margin + left_label_w
        chart_w = max(self.width() - chart_x - right_info_w - margin, 180)

        font = QFont("Segoe UI", 8)
        painter.setFont(font)

        palette = [QColor("#2b6cb0"), QColor("#d9534f"), QColor("#2f855a"), QColor("#805ad5")]

        for i, (name, path, series) in enumerate(self._rows):
            y = base_y + i * (row_h + gap)
            row_rect = QRect(margin, y - 1, self.width() - margin * 2, row_h + 2)
            self._row_hit_areas.append((row_rect, path))

            painter.setPen(QColor("#2f3d59"))
            label = name if len(name) <= 28 else name[:25] + "..."
            painter.drawText(margin, y, left_label_w - 8, row_h, Qt.AlignmentFlag.AlignVCenter, label)

            max_v = max(series) if series else 1
            min_v = min(series) if series else 0
            span = max(max_v - min_v, 1)
            pts = []
            count = max(len(series), 2)
            for idx, value in enumerate(series):
                px = chart_x + int(idx * (chart_w / (count - 1)))
                py = y + row_h - 6 - int((value - min_v) / span * (row_h - 12))
                pts.append((px, py))

            painter.setPen(QPen(QColor("#d7e2f2"), 1))
            painter.drawRect(chart_x, y + 4, chart_w, row_h - 8)

            if len(pts) >= 2:
                pen = QPen(palette[i % len(palette)], 2)
                painter.setPen(pen)
                for p0, p1 in zip(pts[:-1], pts[1:]):
                    painter.drawLine(p0[0], p0[1], p1[0], p1[1])

            if pts:
                painter.setBrush(QBrush(palette[i % len(palette)]))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(pts[-1][0] - 3, pts[-1][1] - 3, 6, 6)

            first = series[0] if series else 0
            last = series[-1] if series else 0
            delta = last - first
            detail = f"{format_size(first)} -> {format_size(last)}"
            sign = "+" if delta >= 0 else ""
            detail2 = f"{sign}{format_size(delta)}"
            painter.setPen(QColor("#334155"))
            painter.drawText(chart_x + chart_w + 8, y + 2, right_info_w, 15, Qt.AlignmentFlag.AlignLeft, detail)
            painter.drawText(chart_x + chart_w + 8, y + 18, right_info_w, 15, Qt.AlignmentFlag.AlignLeft, detail2)

        guide_y = base_y + len(self._rows) * (row_h + gap) + 8
        painter.setPen(QColor("#4d617f"))
        guide = "点击条目查看下一层历史变化" if self._language == "zh" else "Click a row to open next-level history"
        painter.drawText(margin, guide_y, self.width() - margin * 2, 20, Qt.AlignmentFlag.AlignLeft, guide)

        painter.end()


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

    compare_path_requested = pyqtSignal(str)
    history_path_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._language = "en"
        self._compare_current_root_id: Optional[int] = None
        self._compare_baseline_root_id: Optional[int] = None
        self._compare_root_node: Optional[FileNode] = None
        self._compare_node_index: Dict[str, FileNode] = {}
        self._compare_baseline_size_index: Dict[str, int] = {}
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        self._stack = QStackedLayout()
        root_layout.addLayout(self._stack)

        # Cover page
        self._cover = CoverWidget()
        self._stack.addWidget(self._cover)

        # Normal analysis page
        normal_page = QWidget()
        normal_layout = QVBoxLayout(normal_page)
        normal_layout.setContentsMargins(0, 0, 0, 0)

        self._title_label = QLabel("Select a folder to see its contents")
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self._title_label.setFont(font)
        normal_layout.addWidget(self._title_label)

        self._info_label = QLabel("")
        normal_layout.addWidget(self._info_label)

        self._pie = PieChartWidget()
        normal_layout.addWidget(self._pie, stretch=2)

        self._bar = BarChartWidget()
        normal_layout.addWidget(self._bar, stretch=3)
        self._stack.addWidget(normal_page)

        # Comparison page
        self._compare_page = QWidget()
        compare_layout = QVBoxLayout(self._compare_page)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        self._compare_scroll = QScrollArea()
        self._compare_scroll.setWidgetResizable(True)
        self._compare_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._compare_container = QWidget()
        self._compare_container_layout = QVBoxLayout(self._compare_container)
        self._compare_container_layout.setContentsMargins(0, 0, 0, 0)
        self._compare = ComparisonChartWidget()
        self._compare.path_clicked.connect(self.compare_path_requested.emit)
        self._compare_container_layout.addWidget(self._compare)
        self._compare_scroll.setWidget(self._compare_container)
        compare_layout.addWidget(self._compare_scroll)
        self._stack.addWidget(self._compare_page)

        # History trend page
        self._history = HistoryTrendChartWidget()
        self._history.path_clicked.connect(self.history_path_requested.emit)
        self._stack.addWidget(self._history)

        self.setMinimumWidth(300)
        self.show_cover()

    def set_cover_theme(self, theme_key: str) -> None:
        self._cover.set_theme(theme_key)

    def set_cover_image(self, image_path: str) -> bool:
        return self._cover.set_cover_image(image_path)

    def clear_cover_image(self) -> None:
        self._cover.set_cover_image("")

    def cover_image_path(self) -> str:
        return self._cover.cover_image_path()

    def set_language(self, language: str) -> None:
        self._language = language
        self._cover.set_language(language)
        self._compare.set_language(language)
        self._history.set_language(language)
        if not self._title_label.text() or self._title_label.text() in {
            "Select a folder to see its contents",
            "选择文件夹后可查看容量分布",
            "No data",
            "暂无数据",
        }:
            self._title_label.setText(
                "选择文件夹后可查看容量分布" if language == "zh" else "Select a folder to see its contents"
            )

    def show_cover(self) -> None:
        self._stack.setCurrentWidget(self._cover)

    def show_comparison(
        self,
        current_root: Optional[FileNode],
        baseline_root: Optional[FileNode],
        focus_path: Optional[str] = None,
    ) -> None:
        rows: List[Tuple[str, str, int, int]] = []
        title = "Comparison" if self._language == "en" else "容量变化对比"
        selected_path = focus_path

        if current_root is None:
            self._compare.set_data(title, rows, selected_path)
            self._stack.setCurrentWidget(self._compare_page)
            return

        self._ensure_compare_indexes(current_root, baseline_root)

        if focus_path:
            focus_node = self._compare_node_index.get(focus_path)
            if focus_node and focus_node.is_dir:
                rel_depth = self._depth_from_root(current_root.path, focus_node.path)
                if rel_depth <= 0:
                    rows = self._build_level_rows(parent_path=None)
                    title = (
                        "Level 1 folder changes"
                        if self._language == "en"
                        else "一级目录容量变化"
                    )
                else:
                    rows = self._build_level_rows(parent_path=focus_node.path)
                    next_level = rel_depth + 1
                    title = (
                        f"Level {next_level} under {focus_node.name}"
                        if self._language == "en"
                        else f"{focus_node.name} 下第{next_level}级目录变化"
                    )
        if not rows:
            rows = self._build_level_rows(parent_path=None)
            title = "Level 1 folder changes" if self._language == "en" else "一级目录容量变化"

        self._compare.set_data(title, rows, selected_path)
        self._compare.setMinimumHeight(max(self._compare.content_height(), 520))
        self._stack.setCurrentWidget(self._compare_page)

    def show_history_trend(
        self,
        disk_path: str,
        snapshots: List[Tuple[str, FileNode]],
        parent_path: Optional[str],
    ) -> None:
        x_labels = [label.split("|")[-1].strip() for label, _ in snapshots]
        rows = self._build_history_rows(snapshots, parent_path)

        if parent_path:
            title = (
                f"History Trend: {os.path.basename(parent_path) or parent_path}"
                if self._language == "en"
                else f"历史变化：{os.path.basename(parent_path) or parent_path}"
            )
        else:
            title = (
                f"History Trend (Level 1): {disk_path}"
                if self._language == "en"
                else f"一级目录历史变化：{disk_path}"
            )

        self._history.set_data(title, rows, x_labels)
        self._stack.setCurrentWidget(self._history)

    def display(self, node: Optional[FileNode]) -> None:
        self._stack.setCurrentIndex(1)
        if node is None:
            self._title_label.setText("No data" if self._language == "en" else "暂无数据")
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

    @staticmethod
    def _depth_from_root(root_path: str, path: str) -> int:
        rel = os.path.relpath(path, root_path)
        if rel in {".", ""}:
            return 0
        return len([p for p in rel.split(os.sep) if p and p != "."])

    def _build_level_rows(self, parent_path: Optional[str]) -> List[Tuple[str, str, int, int]]:
        rows: List[Tuple[str, str, int, int]] = []
        if parent_path is None:
            if self._compare_root_node is None:
                return rows
            source_parent = self._compare_root_node
        else:
            source_parent = self._compare_node_index.get(parent_path)
            if source_parent is None:
                return rows

        current_dirs = [n for n in source_parent.get_children_sorted("size") if n.is_dir]
        for node in current_dirs:
            previous_size = self._compare_baseline_size_index.get(node.path, 0)
            rows.append((node.name, node.path, node.size, previous_size))

        rows.sort(key=lambda r: abs(r[2] - r[3]), reverse=True)
        return rows

    def _ensure_compare_indexes(
        self,
        current_root: FileNode,
        baseline_root: Optional[FileNode],
    ) -> None:
        current_id = id(current_root)
        if self._compare_current_root_id != current_id:
            self._compare_current_root_id = current_id
            self._compare_root_node = current_root
            self._compare_node_index = self._build_node_index(current_root)

        baseline_id = id(baseline_root) if baseline_root is not None else None
        if self._compare_baseline_root_id != baseline_id:
            self._compare_baseline_root_id = baseline_id
            self._compare_baseline_size_index = (
                self._build_size_index(baseline_root) if baseline_root is not None else {}
            )

    @staticmethod
    def _build_node_index(root: FileNode) -> Dict[str, FileNode]:
        index: Dict[str, FileNode] = {}
        stack: List[FileNode] = [root]
        while stack:
            node = stack.pop()
            index[node.path] = node
            if node.children:
                stack.extend(node.children)
        return index

    @staticmethod
    def _build_size_index(root: FileNode) -> Dict[str, int]:
        index: Dict[str, int] = {}
        stack: List[FileNode] = [root]
        while stack:
            node = stack.pop()
            index[node.path] = int(node.size)
            if node.children:
                stack.extend(node.children)
        return index

    def _build_history_rows(
        self,
        snapshots: List[Tuple[str, FileNode]],
        parent_path: Optional[str],
    ) -> List[Tuple[str, str, List[int]]]:
        if not snapshots:
            return []

        latest_root = snapshots[-1][1]
        base_node = latest_root if not parent_path else latest_root.find(parent_path)
        if base_node is None:
            return []

        target_dirs = [n for n in base_node.get_children_sorted("size") if n.is_dir][:16]
        rows: List[Tuple[str, str, List[int]]] = []
        for node in target_dirs:
            series: List[int] = []
            for _label, root in snapshots:
                old = root.find(node.path)
                series.append(old.size if old is not None else 0)
            rows.append((node.name, node.path, series))

        rows.sort(key=lambda item: abs(item[2][-1] - item[2][0]) if item[2] else 0, reverse=True)
        return rows
