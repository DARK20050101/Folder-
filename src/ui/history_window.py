"""Separate window for disk history trend analysis."""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..cache import HistoryTrendSnapshot
from .chart_widget import HistoryTrendChartWidget


class SpaceHistoryWindow(QDialog):
    """Dedicated, scrollable window for level-1/level-2 history trend charts."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._language = "zh"
        self._theme = "meadow"

        self._disk_path: Optional[str] = None
        self._snapshots: list[HistoryTrendSnapshot] = []
        self._focus_parent_path: Optional[str] = None
        self._rows_cache: dict[str, list[tuple[str, str, list[int]]]] = {}

        self.setWindowTitle("空间历史变化")
        self.resize(980, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self._title_label = QLabel("空间历史变化")
        self._title_label.setStyleSheet("font-weight: 700; font-size: 16px;")
        self._meta_label = QLabel("")
        self._back_btn = QPushButton("返回")
        self._back_btn.clicked.connect(self._on_back)
        self._exit_btn = QPushButton("退出对比")
        self._exit_btn.clicked.connect(self.close)
        top.addWidget(self._title_label)
        top.addStretch()
        top.addWidget(self._meta_label)
        top.addSpacing(12)
        top.addWidget(self._back_btn)
        top.addWidget(self._exit_btn)
        root.addLayout(top)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._chart = HistoryTrendChartWidget()
        self._chart.path_clicked.connect(self._on_chart_path_clicked)
        self._scroll_layout.addWidget(self._chart)
        self._scroll.setWidget(self._scroll_content)
        root.addWidget(self._scroll)

        self._set_back_enabled(False)

    def set_language(self, language: str) -> None:
        self._language = "zh" if language == "zh" else "en"
        self._chart.set_language(self._language)
        self._title_label.setText("空间历史变化" if self._language == "zh" else "Space History")
        self._exit_btn.setText("退出对比" if self._language == "zh" else "Exit")
        self._back_btn.setText("返回" if self._language == "zh" else "Back")

    def set_theme(self, theme: str) -> None:
        self._theme = "dungeon" if theme == "dungeon" else "meadow"
        if self._theme == "dungeon":
            self.setStyleSheet(
                "QDialog, QWidget { background-color: #1f2238; color: #dde6ff; }"
                "QPushButton { background-color: #2f3661; border: 2px solid #7f8cff; padding: 4px 10px; font-weight: 600; }"
                "QPushButton:hover { background-color: #3d4678; }"
            )
        else:
            self.setStyleSheet(
                "QDialog, QWidget { background-color: #f3f9ff; color: #1f3450; }"
                "QPushButton { background-color: #f6f1d5; border: 2px solid #629f4f; padding: 4px 10px; font-weight: 600; }"
                "QPushButton:hover { background-color: #ecf7cb; }"
            )

    def open_history(self, disk_path: str, snapshots: list[HistoryTrendSnapshot]) -> None:
        self._disk_path = disk_path
        self._snapshots = snapshots
        self._focus_parent_path = None
        self._rows_cache.clear()
        self._render()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_back(self) -> None:
        self._focus_parent_path = None
        self._render()

    def _on_chart_path_clicked(self, path: str) -> None:
        if self._focus_parent_path is None:
            self._focus_parent_path = path
            self._render()

    def _set_back_enabled(self, enabled: bool) -> None:
        self._back_btn.setEnabled(enabled)

    def _render(self) -> None:
        if not self._disk_path or not self._snapshots:
            return

        if self._focus_parent_path:
            title = (
                f"历史变化：{os.path.basename(self._focus_parent_path) or self._focus_parent_path}"
                if self._language == "zh"
                else f"History Trend: {os.path.basename(self._focus_parent_path) or self._focus_parent_path}"
            )
        else:
            title = (
                f"一级目录历史变化：{self._disk_path}"
                if self._language == "zh"
                else f"History Trend (Level 1): {self._disk_path}"
            )

        x_labels = [s.label.split("|")[-1].strip() for s in self._snapshots]
        rows = self._rows_for_parent(self._focus_parent_path)
        self._chart.set_data(title, rows, x_labels)
        self._chart.setMinimumHeight(max(self._chart.content_height(), 520))
        self._set_back_enabled(self._focus_parent_path is not None)

        meta = (
            f"快照数: {len(self._snapshots)}"
            if self._language == "zh"
            else f"Snapshots: {len(self._snapshots)}"
        )
        self._meta_label.setText(meta)

    def _rows_for_parent(self, parent_path: Optional[str]) -> list[tuple[str, str, list[int]]]:
        key = parent_path or "__ROOT__"
        cached = self._rows_cache.get(key)
        if cached is not None:
            return cached

        latest = self._snapshots[-1]
        if parent_path is None:
            target_map = latest.level1
            snapshot_maps = [s.level1 for s in self._snapshots]
        else:
            target_map = latest.level2.get(parent_path, {})
            snapshot_maps = [s.level2.get(parent_path, {}) for s in self._snapshots]

        targets = sorted(target_map.items(), key=lambda kv: kv[1], reverse=True)[:28]

        rows: list[tuple[str, str, list[int]]] = []
        for path, _size in targets:
            name = os.path.basename(path) or path
            series = [int(m.get(path, 0)) for m in snapshot_maps]
            rows.append((name, path, series))

        rows.sort(key=lambda r: abs(r[2][-1] - r[2][0]) if r[2] else 0, reverse=True)
        self._rows_cache[key] = rows
        return rows
