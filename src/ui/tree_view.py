"""Custom tree view widget for DiskExplorer (PyQt6)."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMenu,
    QMessageBox,
    QTreeView,
)

from ..models import FileNode, format_size

_logger = logging.getLogger(__name__)


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
        return len(self.COLUMNS)

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
                return QColor(30, 60, 160)

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
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def remove_node(self, node: FileNode) -> bool:
        """Remove *node* from the model without re-scanning.

        Updates the in-memory tree, the parent map, and notifies Qt so that
        the view refreshes immediately.  Returns True on success.
        """
        parent_node = self._parent_map.get(id(node))
        if parent_node is None:
            # Node is root or not tracked – cannot remove
            return False

        # Determine the row index in the sorted children list.
        siblings = parent_node.get_children_sorted("size")
        try:
            row = siblings.index(node)
        except ValueError:
            return False

        # Build the parent QModelIndex.
        if parent_node is self._root:
            parent_idx = QModelIndex()
        else:
            grandparent = self._parent_map.get(id(parent_node))
            if grandparent is None:
                parent_idx = QModelIndex()
            else:
                gp_siblings = grandparent.get_children_sorted("size")
                try:
                    gp_row = gp_siblings.index(parent_node)
                except ValueError:
                    return False
                parent_idx = self.createIndex(gp_row, 0, parent_node)

        self.beginRemoveRows(parent_idx, row, row)

        # Mutate the children list.
        parent_node.children.remove(node)

        # Clean up the parent map for the removed subtree.
        for n in node.iter_all():
            self._parent_map.pop(id(n), None)

        self.endRemoveRows()

        # Propagate size / file-count changes up the ancestor chain.
        self._update_ancestor_stats(parent_node, node)

        return True

    def _update_ancestor_stats(self, start: FileNode, removed: FileNode) -> None:
        """Walk from *start* up to (but not including) root and subtract the
        size/file_count contributed by the removed subtree."""
        size_delta = removed.size
        count_delta = removed.file_count if removed.is_dir else 1

        current: Optional[FileNode] = start
        while current is not None and current is not self._root:
            current.size -= size_delta
            current.file_count -= count_delta
            # Notify the view that this row's display data has changed.
            node_idx = self.index_for_node(current)
            if node_idx.isValid():
                sibling_last = self.createIndex(
                    node_idx.row(), len(self.COLUMNS) - 1, current
                )
                self.dataChanged.emit(node_idx, sibling_last)
            current = self._parent_map.get(id(current))

        # Also update root if it is not the hidden sentinel.
        if self._root is not None:
            self._root.size -= size_delta
            self._root.file_count -= count_delta


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
        open_act = menu.addAction("Open in File Manager")
        copy_act = menu.addAction("Copy Path")
        menu.addSeparator()
        trash_act = menu.addAction("Move to Recycle Bin")
        delete_act = menu.addAction("Delete Permanently")
        action = menu.exec(self.viewport().mapToGlobal(pos))

        if action == open_act:
            self._open_in_file_manager(node.path)
        elif action == copy_act:
            QApplication.clipboard().setText(node.path)
        elif action == trash_act:
            self._delete_node(node, permanent=False)
        elif action == delete_act:
            self._delete_node(node, permanent=True)

    def _delete_node(self, node: FileNode, *, permanent: bool) -> None:
        """Delete *node* from disk and remove it from the tree model."""
        import os
        import shutil

        verb = "permanently delete" if permanent else "move to the Recycle Bin"
        kind = "folder" if node.is_dir else "file"
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to {verb} the {kind}?\n\n{node.path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if permanent:
                if node.is_dir:
                    shutil.rmtree(node.path)
                else:
                    os.remove(node.path)
            else:
                try:
                    import send2trash
                    send2trash.send2trash(node.path)
                except ImportError:
                    _logger.warning(
                        "send2trash is not installed; falling back to permanent delete"
                    )
                    QMessageBox.warning(
                        self,
                        "Recycle Bin Unavailable",
                        "The 'send2trash' package is not installed.\n"
                        "Please run:  pip install send2trash\n\n"
                        "The file was NOT deleted.",
                    )
                    return
        except OSError:
            _logger.exception("Failed to delete %r", node.path)
            QMessageBox.critical(
                self,
                "Delete Failed",
                f"Could not delete:\n{node.path}\n\nSee logs/app.log for details.",
            )
            return

        # Update the in-memory model without re-scanning.
        if not self._node_model.remove_node(node):
            _logger.warning("remove_node returned False for %r", node.path)

    @staticmethod
    def _open_in_file_manager(path: str) -> None:
        import os
        import subprocess
        import sys
        try:
            if sys.platform == "win32":
                if os.path.isfile(path):
                    # Open the parent folder and select the file.
                    subprocess.Popen(["explorer", f"/select,{path}"])
                else:
                    subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin":
                if os.path.isfile(path):
                    subprocess.Popen(["open", "-R", path])
                else:
                    subprocess.Popen(["open", path])
            else:
                target = os.path.dirname(path) if os.path.isfile(path) else path
                subprocess.Popen(["xdg-open", target])
        except OSError:
            _logger.exception("open_in_file_manager failed for %r", path)
