"""Main window for DiskExplorer (PyQt6)."""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
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
from .recent_files_panel import RecentFilesPanel
from .tree_view import FileSystemTreeView

_logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    """Background thread that runs the file system scan."""

    progress = pyqtSignal(int, str)    # (count, current_path) – throttled
    finished = pyqtSignal(object)      # FileNode on success
    error = pyqtSignal(str)            # error message
    scan_stats = pyqtSignal(float, int)  # (elapsed_seconds, item_count)

    # Minimum interval between progress signal emissions (seconds).
    _PROGRESS_THROTTLE = 0.25

    def __init__(self, scanner: FileSystemScanner, path: str) -> None:
        super().__init__()
        self._scanner = scanner
        self._path = path
        self._last_emit = 0.0
        self._scan_start = 0.0

    def run(self) -> None:
        self._scan_start = time.monotonic()
        try:
            node = self._scanner.scan_directory_threaded(
                self._path,
                progress_callback=self._on_progress,
            )
            elapsed = time.monotonic() - self._scan_start
            self.scan_stats.emit(elapsed, self._scanner._scanned_count)
            self.finished.emit(node)
        except ScanCancelledError:
            self.error.emit("Scan cancelled.")
        except Exception as exc:
            _logger.exception("Unexpected scan error for %s", self._path)
            self.error.emit(str(exc))

    def _on_progress(self, count: int, path: str) -> None:
        # Secondary throttle at the signal-emission layer so that rapid
        # callbacks from the scanner thread don't flood the Qt event queue.
        now = time.monotonic()
        if now - self._last_emit >= self._PROGRESS_THROTTLE:
            self._last_emit = now
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
        self._pending_selected_node: Optional[FileNode] = None
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(180)
        self._selection_timer.timeout.connect(self._apply_selected_node)
        # Timing populated by ScanWorker.scan_stats signal
        self._last_scan_elapsed: float = 0.0
        self._last_scan_count: int = 0

        self._setup_ui()
        self._setup_menu()
        self._populate_disk_bar()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("DiskExplorer – Disk Space Analyzer")
        self.resize(1200, 800)

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

        # --- Top splitter: tree (left) + chart (right) ---
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._tree_view = FileSystemTreeView()
        self._tree_view.node_selected.connect(self._on_node_selected)
        self._chart_widget = SizeChartWidget()
        top_splitter.addWidget(self._tree_view)
        top_splitter.addWidget(self._chart_widget)
        top_splitter.setSizes([700, 500])

        # --- Recent Files panel ---
        self._recent_panel = RecentFilesPanel()
        self._recent_panel.locate_requested.connect(self._on_locate_requested)

        # --- Vertical splitter: top (tree+chart) + bottom (recent files) ---
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(top_splitter)
        v_splitter.addWidget(self._recent_panel)
        v_splitter.setSizes([500, 200])
        main_layout.addWidget(v_splitter)

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
        set_cache_dir_act = QAction("Set Cache &Directory…", self)
        set_cache_dir_act.triggered.connect(self._on_set_cache_dir)
        view_menu.addAction(set_cache_dir_act)

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
        self._scan_worker.scan_stats.connect(self._on_scan_stats)
        self._scan_worker.start()

    def _on_scan_progress(self, count: int, path: str) -> None:
        self._status_bar.showMessage(f"Scanned {count:,} items… {path[:80]}")

    def _on_scan_stats(self, elapsed: float, count: int) -> None:
        """Store performance stats emitted by the worker before finished."""
        self._last_scan_elapsed = elapsed
        self._last_scan_count = count

    def _on_scan_finished(self, node: FileNode) -> None:
        self._cache.save(node.path, node)
        self._model.set_root(node.path, node)
        self._display_result(node)
        self._reset_scan_controls()
        elapsed = self._last_scan_elapsed
        count = self._last_scan_count
        throughput = count / elapsed if elapsed > 0 else 0
        self._status_bar.showMessage(
            f"Done. {node.formatted_size} in {node.file_count:,} files. "
            f"Scanned {count:,} items in {elapsed:.1f}s "
            f"({throughput:,.0f} items/s)."
        )
        _logger.info(
            "UI scan finished: path=%s  size=%s  files=%d  "
            "items=%d  elapsed=%.2fs  throughput=%.0f items/s",
            node.path, node.formatted_size, node.file_count,
            count, elapsed, throughput,
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
        self._recent_panel.set_root(node)

    def _on_node_selected(self, node: FileNode) -> None:
        self._pending_selected_node = node
        self._selection_timer.start()

    def _apply_selected_node(self) -> None:
        node = self._pending_selected_node
        if node is None:
            return
        self._chart_widget.display(node)
        self._status_bar.showMessage(
            f"{node.path}  {node.formatted_size}"
            + (f"  ({node.file_count} files)" if node.is_dir else "")
        )
        # Update Recent Files panel scope when a directory is selected
        if node.is_dir:
            self._recent_panel.set_current_dir(node)

    def _on_locate_requested(self, path: str) -> None:
        """Locate a file path in the tree view (called from Recent Files panel)."""
        if not self._tree_view.navigate_to_path(path):
            self._status_bar.showMessage(f"Could not locate: {path}")

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

    def _on_set_cache_dir(self) -> None:
        new_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Cache Directory",
            str(self._cache.cache_dir),
        )
        if new_dir:
            self._cache = ScanCache(cache_dir=new_dir)
            QMessageBox.information(
                self,
                "Cache Directory Updated",
                f"Cache directory set to:\n{new_dir}\n\n"
                "Previously cached scans from the old directory are no longer used.",
            )

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
