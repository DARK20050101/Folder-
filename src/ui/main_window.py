"""Main window for DiskExplorer (PyQt6)."""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..cache import ScanCache
from ..export import ExportHandler
from ..models import DiskDataModel, FileNode
from ..scanner import FileSystemScanner, ScanCancelledError
from .chart_widget import SizeChartWidget
from .tree_view import FileSystemTreeView


class ScanWorker(QThread):
    """Background thread that runs the file system scan."""

    progress = pyqtSignal(int, str)   # (count, current_path)
    finished = pyqtSignal(object)     # FileNode on success
    error = pyqtSignal(str)           # error message

    def __init__(self, scanner: FileSystemScanner, path: str) -> None:
        super().__init__()
        self._scanner = scanner
        self._path = path

    def run(self) -> None:
        try:
            node = self._scanner.scan_directory_threaded(
                self._path,
                progress_callback=self._on_progress,
            )
            self.finished.emit(node)
        except ScanCancelledError:
            self.error.emit("Scan cancelled.")
        except Exception as exc:
            self.error.emit(str(exc))

    def _on_progress(self, count: int, path: str) -> None:
        self.progress.emit(count, path)


class MainWindow(QMainWindow):
    """DiskExplorer main application window."""

    def __init__(self) -> None:
        super().__init__()
        self._scanner = FileSystemScanner(max_workers=4)
        self._model = DiskDataModel()
        self._cache = ScanCache()
        self._exporter = ExportHandler()
        self._scan_worker: Optional[ScanWorker] = None
        self._current_root: Optional[FileNode] = None

        self._setup_ui()
        self._setup_menu()
        self._populate_disk_bar()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("DiskExplorer – Disk Space Analyzer")
        self.resize(1200, 700)

        # --- Central widget ---
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # --- Toolbar row (disk buttons + scan/cancel) ---
        self._disk_toolbar = QToolBar("Disks")
        self._disk_toolbar.setMovable(False)
        self.addToolBar(self._disk_toolbar)

        # --- Address bar ---
        addr_bar = QWidget()
        addr_layout = QHBoxLayout(addr_bar)
        addr_layout.setContentsMargins(4, 2, 4, 2)
        self._addr_label = QLabel("Path:")
        self._scan_btn = QPushButton("Scan Selected Path")
        self._scan_btn.clicked.connect(self._on_scan_custom)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        addr_layout.addWidget(self._addr_label)
        addr_layout.addStretch()
        addr_layout.addWidget(self._scan_btn)
        addr_layout.addWidget(self._cancel_btn)
        main_layout.addWidget(addr_bar)

        # --- Progress bar ---
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._progress_bar.setVisible(False)
        main_layout.addWidget(self._progress_bar)

        # --- Splitter: tree (left) + chart (right) ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._tree_view = FileSystemTreeView()
        self._tree_view.node_selected.connect(self._on_node_selected)
        self._chart_widget = SizeChartWidget()
        splitter.addWidget(self._tree_view)
        splitter.addWidget(self._chart_widget)
        splitter.setSizes([700, 500])
        main_layout.addWidget(splitter)

        # --- Status bar ---
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready. Select a disk or folder to scan.")

    def _setup_menu(self) -> None:
        menu = self.menuBar()

        # File menu
        file_menu = menu.addMenu("&File")
        scan_act = QAction("&Scan Folder…", self)
        scan_act.setShortcut("Ctrl+O")
        scan_act.triggered.connect(self._on_scan_custom)
        file_menu.addAction(scan_act)

        file_menu.addSeparator()
        export_csv_act = QAction("Export as &CSV…", self)
        export_csv_act.triggered.connect(lambda: self._export("csv"))
        file_menu.addAction(export_csv_act)
        export_html_act = QAction("Export as &HTML…", self)
        export_html_act.triggered.connect(lambda: self._export("html"))
        file_menu.addAction(export_html_act)
        export_json_act = QAction("Export as &JSON…", self)
        export_json_act.triggered.connect(lambda: self._export("json"))
        file_menu.addAction(export_json_act)

        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # View menu
        view_menu = menu.addMenu("&View")
        refresh_act = QAction("&Refresh / Re-scan", self)
        refresh_act.setShortcut("F5")
        refresh_act.triggered.connect(self._on_refresh)
        view_menu.addAction(refresh_act)
        clear_cache_act = QAction("Clear &Cache", self)
        clear_cache_act.triggered.connect(self._on_clear_cache)
        view_menu.addAction(clear_cache_act)

        # Help menu
        help_menu = menu.addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

    def _populate_disk_bar(self) -> None:
        """Add one button per detected disk/mount point."""
        disks = FileSystemScanner.list_disks()
        for disk in disks:
            btn = QPushButton(disk)
            btn.setFixedWidth(80)
            btn.clicked.connect(lambda checked, d=disk: self._start_scan(d))
            self._disk_toolbar.addWidget(btn)

    # ------------------------------------------------------------------
    # Scan lifecycle
    # ------------------------------------------------------------------

    def _start_scan(self, path: str) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            QMessageBox.warning(self, "Scan in progress",
                                "A scan is already running. Cancel it first.")
            return

        # Check cache
        cached = self._cache.load(path, max_age_seconds=3600)
        if cached is not None:
            age = self._cache.cache_age_seconds(path) or 0
            reply = QMessageBox.question(
                self,
                "Use cached data?",
                f"A cached scan from {age / 60:.0f} minute(s) ago exists.\n"
                "Use cached data? (No = re-scan)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._display_result(cached)
                return

        self._addr_label.setText(f"Scanning: {path}")
        self._progress_bar.setVisible(True)
        self._scan_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._status_bar.showMessage(f"Scanning {path}…")

        self._scan_worker = ScanWorker(self._scanner, path)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    def _on_scan_progress(self, count: int, path: str) -> None:
        self._status_bar.showMessage(f"Scanned {count} items… {path[:80]}")

    def _on_scan_finished(self, node: FileNode) -> None:
        self._cache.save(node.path, node)
        self._model.set_root(node.path, node)
        self._display_result(node)
        self._reset_scan_controls()
        self._status_bar.showMessage(
            f"Done. {node.formatted_size} in {node.file_count} files."
        )

    def _on_scan_error(self, message: str) -> None:
        self._reset_scan_controls()
        self._status_bar.showMessage(f"Error: {message}")
        QMessageBox.warning(self, "Scan Error", message)

    def _on_cancel(self) -> None:
        self._scanner.cancel()
        self._status_bar.showMessage("Cancelling…")

    def _reset_scan_controls(self) -> None:
        self._progress_bar.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _display_result(self, node: FileNode) -> None:
        self._current_root = node
        self._addr_label.setText(f"Path: {node.path}  [{node.formatted_size}]")
        self._tree_view.set_root(node)
        self._chart_widget.display(node)

    def _on_node_selected(self, node: FileNode) -> None:
        self._chart_widget.display(node)
        self._status_bar.showMessage(
            f"{node.path}  {node.formatted_size}"
            + (f"  ({node.file_count} files)" if node.is_dir else "")
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_scan_custom(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Folder to Scan")
        if path:
            self._start_scan(path)

    def _on_refresh(self) -> None:
        if self._current_root:
            self._cache.invalidate(self._current_root.path)
            self._start_scan(self._current_root.path)

    def _on_clear_cache(self) -> None:
        self._cache.clear_all()
        QMessageBox.information(self, "Cache Cleared", "All cached scan data has been removed.")

    def _export(self, fmt: str) -> None:
        if not self._current_root:
            QMessageBox.information(self, "Nothing to export",
                                    "Please scan a folder first.")
            return
        ext_map = {"csv": "CSV Files (*.csv)", "html": "HTML Files (*.html)",
                   "json": "JSON Files (*.json)"}
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export as {fmt.upper()}", f"report.{fmt}", ext_map.get(fmt, "")
        )
        if not path:
            return
        try:
            if fmt == "csv":
                self._exporter.export_csv(self._current_root, path)
            elif fmt == "html":
                self._exporter.export_html(self._current_root, path)
            elif fmt == "json":
                self._exporter.export_json(self._current_root, path)
            self._status_bar.showMessage(f"Exported to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About DiskExplorer",
            "<h3>DiskExplorer v1.0</h3>"
            "<p>A lightweight disk space analysis tool.</p>"
            "<p>Visualise your disk usage in a hierarchical tree view "
            "with charts and export capabilities.</p>",
        )
