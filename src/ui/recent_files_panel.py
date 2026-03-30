"""Recent Files panel for DiskExplorer (PyQt6)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import FileNode, format_size

# Maximum number of recent file rows shown in the panel.
MAX_RECENT_FILES = 1000


class RecentFilesPanel(QWidget):
    """Panel showing the most-recently modified/created files from a scan.

    Signals:
        locate_requested(str): Emitted when the user wants to locate a file
            in the main tree.  The argument is the file's absolute path.
    """

    locate_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scan_root: Optional[FileNode] = None
        self._current_dir: Optional[FileNode] = None
        # Flat list of all file nodes in the current scan root (cached).
        self._all_files: List[FileNode] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ---- Control bar ----
        ctrl = QWidget()
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(6)

        ctrl_layout.addWidget(QLabel("<b>Recent Files</b>"))
        ctrl_layout.addSpacing(8)

        ctrl_layout.addWidget(QLabel("Time:"))
        self._time_combo = QComboBox()
        self._time_combo.addItems(["Modified Time", "Created Time"])
        self._time_combo.currentIndexChanged.connect(self._refresh)
        ctrl_layout.addWidget(self._time_combo)

        ctrl_layout.addWidget(QLabel("Scope:"))
        self._scope_combo = QComboBox()
        self._scope_combo.addItems(["Entire Scan Root", "Current Directory"])
        self._scope_combo.currentIndexChanged.connect(self._refresh)
        ctrl_layout.addWidget(self._scope_combo)

        ctrl_layout.addWidget(QLabel("Sort:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["By Time (desc)", "By Size (desc)"])
        self._sort_combo.currentIndexChanged.connect(self._refresh)
        ctrl_layout.addWidget(self._sort_combo)

        self._refresh_btn = QPushButton("↺ Refresh")
        self._refresh_btn.setToolTip("Rebuild the list from the current scan data")
        self._refresh_btn.clicked.connect(self._refresh)
        ctrl_layout.addWidget(self._refresh_btn)

        ctrl_layout.addStretch()

        self._count_label = QLabel("0 files")
        ctrl_layout.addWidget(self._count_label)

        layout.addWidget(ctrl)

        # ---- Table ----
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Full Path", "Size", "Time"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)  # we sort manually
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.doubleClicked.connect(self._on_double_clicked)

        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_root(self, node: Optional[FileNode]) -> None:
        """Set the scan root and rebuild the file list."""
        self._scan_root = node
        self._current_dir = node
        self._all_files = []
        if node is not None:
            self._collect_files(node, self._all_files)
        self._refresh()

    def set_current_dir(self, node: Optional[FileNode]) -> None:
        """Update the currently selected directory for scope filtering."""
        self._current_dir = node
        if self._scope_combo.currentIndex() == 1:  # "Current Directory"
            self._refresh()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_files(self, root: FileNode, out: List[FileNode]) -> None:
        """Recursively collect all *file* nodes (non-dirs) into *out*."""
        for node in root.iter_all():
            if not node.is_dir:
                out.append(node)

    def _refresh(self) -> None:
        """Rebuild the table according to current control settings."""
        time_type = self._time_combo.currentIndex()   # 0=modified, 1=created
        scope = self._scope_combo.currentIndex()       # 0=root, 1=current dir
        sort_by = self._sort_combo.currentIndex()      # 0=time, 1=size

        # Choose source
        if scope == 1 and self._current_dir is not None:
            files: List[FileNode] = []
            self._collect_files(self._current_dir, files)
        else:
            files = list(self._all_files)

        # Sort
        if sort_by == 0:
            key = (lambda n: n.create_time) if time_type == 1 else (lambda n: n.mod_time)
            files.sort(key=key, reverse=True)
        else:
            files.sort(key=lambda n: n.size, reverse=True)

        # Limit to max rows
        files = files[:MAX_RECENT_FILES]

        # Populate table (disable sorting first to avoid mid-insert thrash)
        self._table.setRowCount(0)
        self._table.setRowCount(len(files))
        time_fmt = "%Y-%m-%d %H:%M:%S"
        for row, node in enumerate(files):
            ts = node.create_time if time_type == 1 else node.mod_time
            time_str = time.strftime(time_fmt, time.localtime(ts)) if ts else ""

            name_item = QTableWidgetItem(node.name)
            name_item.setData(Qt.ItemDataRole.UserRole, node.path)

            path_item = QTableWidgetItem(node.path)

            size_item = QTableWidgetItem(format_size(node.size))
            size_item.setData(Qt.ItemDataRole.UserRole, node.size)
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            time_item = QTableWidgetItem(time_str)

            for col, item in enumerate((name_item, path_item, size_item, time_item)):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

        self._count_label.setText(f"{len(files):,} file(s)")

    def _path_for_row(self, row: int) -> Optional[str]:
        item = self._table.item(row, 0)
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_double_clicked(self, index) -> None:
        path = self._path_for_row(index.row())
        if path:
            self.locate_requested.emit(path)

    def _show_context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        path = self._path_for_row(row)
        if not path:
            return

        menu = QMenu(self)
        locate_act = menu.addAction("Locate in Tree")
        open_act = menu.addAction("Open in File Explorer")
        copy_act = menu.addAction("Copy Path")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == locate_act:
            self.locate_requested.emit(path)
        elif action == open_act:
            self._open_in_explorer(path)
        elif action == copy_act:
            QApplication.clipboard().setText(path)

    @staticmethod
    def _open_in_explorer(path: str) -> None:
        """Open *path* (or its parent folder) in the system file manager."""
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except OSError:
            pass
