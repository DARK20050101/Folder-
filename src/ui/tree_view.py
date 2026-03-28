"""Custom tree view widget for DiskExplorer (PyQt6)."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMenu,
    QTreeView,
)

from ..models import FileNode, format_size


class FileNodeModel(QAbstractItemModel):
    """Qt item model backed by the FileNode tree."""

    COL_NAME = 0
    COL_SIZE = 1
    COL_SIZE_BAR = 2
    COL_FILES = 3
    COL_MOD_TIME = 4
    COLUMNS = ["Name", "Size", "Usage %", "Files", "Modified"]

    def __init__(self, root: Optional[FileNode] = None, parent=None) -> None:
        super().__init__(parent)
        self._root = root
        self._parent_map: dict = {}  # child_id -> parent FileNode
        if root:
            self._build_parent_map(root, None)

    def set_root(self, root: Optional[FileNode]) -> None:
        self.beginResetModel()
        self._root = root
        self._parent_map = {}
        if root:
            self._build_parent_map(root, None)
        self.endResetModel()

    def _build_parent_map(self, node: FileNode, parent: Optional[FileNode]) -> None:
        self._parent_map[id(node)] = parent
        for child in node.children:
            self._build_parent_map(child, node)

    # ------------------------------------------------------------------
    # QAbstractItemModel interface
    # ------------------------------------------------------------------

    def index(self, row: int, col: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, col, parent):
            return QModelIndex()
        if not parent.isValid():
            parent_node = self._root
        else:
            parent_node = parent.internalPointer()
        if parent_node is None:
            return QModelIndex()
        children = parent_node.get_children_sorted("size")
        if row < len(children):
            return self.createIndex(row, col, children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node: FileNode = index.internalPointer()
        parent_node = self._parent_map.get(id(node))
        if parent_node is None or parent_node is self._root:
            return QModelIndex()
        grandparent = self._parent_map.get(id(parent_node))
        if grandparent is None:
            return QModelIndex()
        siblings = grandparent.get_children_sorted("size")
        try:
            row = siblings.index(parent_node)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, parent_node)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return 1 if self._root else 0
        node: FileNode = parent.internalPointer()
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if not parent.isValid():
            return self._root is not None
        node: FileNode = parent.internalPointer()
        return node.is_dir and bool(node.children)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: FileNode = index.internalPointer()
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_NAME:
                return node.name
            if col == self.COL_SIZE:
                return node.formatted_size
            if col == self.COL_SIZE_BAR:
                parent_node = self._parent_map.get(id(node))
                if parent_node and parent_node.size > 0:
                    pct = node.size / parent_node.size * 100
                    return f"{pct:.1f}%"
                return "100%"
            if col == self.COL_FILES:
                return str(node.file_count) if node.is_dir else ""
            if col == self.COL_MOD_TIME:
                import time as _time
                return _time.strftime("%Y-%m-%d %H:%M",
                                      _time.localtime(node.mod_time)) if node.mod_time else ""

        if role == Qt.ItemDataRole.ForegroundRole:
            if node.error:
                return QColor(180, 0, 0)
            if node.is_dir:
                return QColor(30, 60, 160)

        if role == Qt.ItemDataRole.UserRole:
            return node

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None


class FileSystemTreeView(QTreeView):
    """Displays a FileNode tree with sortable columns and context menu."""

    node_selected = pyqtSignal(object)  # emits FileNode

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._node_model = FileNodeModel()
        self.setModel(self._node_model)
        self._setup_view()

    def _setup_view(self) -> None:
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    def set_root(self, node: FileNode) -> None:
        self._node_model.set_root(node)
        self.expandToDepth(0)

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if current.isValid():
            node = current.data(Qt.ItemDataRole.UserRole)
            if node:
                self.node_selected.emit(node)

    def _show_context_menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        node: FileNode = index.data(Qt.ItemDataRole.UserRole)
        if node is None:
            return

        menu = QMenu(self)
        open_act = menu.addAction("Open in File Manager")
        copy_act = menu.addAction("Copy Path")
        action = menu.exec(self.viewport().mapToGlobal(pos))

        if action == open_act:
            self._open_in_file_manager(node.path)
        elif action == copy_act:
            QApplication.clipboard().setText(node.path)

    @staticmethod
    def _open_in_file_manager(path: str) -> None:
        import subprocess
        import sys
        if sys.platform == "win32":
            subprocess.Popen(["explorer", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
