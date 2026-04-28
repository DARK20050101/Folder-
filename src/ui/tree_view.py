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
    _COLUMNS_BY_LANG = {
        "en": ["Name", "Size", "Usage %", "Files", "Modified"],
        "zh": ["名称", "大小", "占比", "文件数", "修改时间"],
    }

    def __init__(self, root: Optional[FileNode] = None, parent=None) -> None:
        super().__init__(parent)
        self._root = root
        self._language = "en"
        self._parent_map: dict = {}  # child_id -> parent FileNode
        if root:
            self._build_parent_map(root, None)

    def set_language(self, language: str) -> None:
        self._language = "zh" if language == "zh" else "en"
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def set_root(self, root: Optional[FileNode]) -> None:
        self.beginResetModel()
        self._root = root
        self._parent_map = {}
        if root:
            self._build_parent_map(root, None)
        self.endResetModel()

    @property
    def root(self) -> Optional[FileNode]:
        """Return the current root FileNode (read-only)."""
        return self._root

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
            if self._root is None:
                return 0
            # Show root's children directly at the top level so that all
            # top-level directories (Windows, Users, Program Files, …) are
            # visible without having to expand a single root item.
            return len(self._root.children)
        node: FileNode = parent.internalPointer()
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._COLUMNS_BY_LANG["en"])

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if not parent.isValid():
            return bool(self._root and self._root.children)
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
                return QColor(0, 0, 0)

        if role == Qt.ItemDataRole.UserRole:
            return node

        return None

    def index_for_node(self, target: FileNode) -> QModelIndex:
        """Return the QModelIndex for *target*, or an invalid index if not found."""
        if self._root is None or target is self._root:
            return QModelIndex()
        # Build path from target up to (but not including) root
        path_to_root: list = []
        current: Optional[FileNode] = target
        while current is not None and current is not self._root:
            path_to_root.append(current)
            current = self._parent_map.get(id(current))
        if current is not self._root:
            return QModelIndex()  # target not in this tree
        # path_to_root is [target, …, direct-child-of-root]; reverse it
        path_to_root.reverse()
        idx = QModelIndex()
        for node in path_to_root:
            parent_node = self._parent_map.get(id(node))
            if parent_node is self._root or parent_node is None:
                siblings = self._root.get_children_sorted("size")
            else:
                siblings = parent_node.get_children_sorted("size")
            try:
                row = siblings.index(node)
            except ValueError:
                return QModelIndex()
            idx = self.createIndex(row, 0, node)
        return idx

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            columns = self._COLUMNS_BY_LANG[self._language]
            if 0 <= section < len(columns):
                return columns[section]
        return None


class FileSystemTreeView(QTreeView):
    """Displays a FileNode tree with sortable columns and context menu."""

    node_selected = pyqtSignal(object)  # emits FileNode
    rescan_requested = pyqtSignal(str)  # emits path
    delete_requested = pyqtSignal(str, bool)  # emits (path, is_dir)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._node_model = FileNodeModel()
        self._language = "en"
        self._theme = "meadow"
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
        self._apply_selection_style()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    def set_language(self, language: str) -> None:
        self._language = "zh" if language == "zh" else "en"
        self._node_model.set_language(self._language)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self._apply_selection_style()

    def _apply_selection_style(self) -> None:
        bg = "#2d7ef7" if self._theme == "meadow" else "#4f5fff"
        self.setStyleSheet(
            "QTreeView::item:selected {"
            f"background-color: {bg};"
            "color: #ffffff;"
            "}"
        )

    def set_root(self, node: FileNode) -> None:
        self._node_model.set_root(node)
        self.expandToDepth(0)

    def navigate_to_path(self, path: str) -> bool:
        """Expand and select the node with *path*. Returns True on success."""
        if self._node_model.root is None:
            return False
        target = self._node_model.root.find(path)
        if target is None:
            return False
        idx = self._node_model.index_for_node(target)
        if not idx.isValid():
            return False
        self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.selectionModel().setCurrentIndex(
            idx, self.selectionModel().SelectionFlag.ClearAndSelect | self.selectionModel().SelectionFlag.Rows
        )
        return True

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
        rescan_act = None
        if node.is_dir:
            rescan_act = menu.addAction("重新扫描" if self._language == "zh" else "Re-scan")
        delete_act = menu.addAction("删除" if self._language == "zh" else "Delete")
        open_act = menu.addAction("在文件管理器打开" if self._language == "zh" else "Open in File Manager")
        copy_act = menu.addAction("复制路径" if self._language == "zh" else "Copy Path")
        action = menu.exec(self.viewport().mapToGlobal(pos))

        if action == rescan_act and node.is_dir:
            self.rescan_requested.emit(node.path)
        elif action == delete_act:
            self.delete_requested.emit(node.path, node.is_dir)
        elif action == open_act:
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
