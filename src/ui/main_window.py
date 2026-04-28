"""Main window for DiskExplorer (PyQt6)."""

from __future__ import annotations

import logging
import os
import shutil
import time
from typing import Optional

from PyQt6.QtCore import QSettings, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..cache import CacheSnapshot, HistoryTrendSnapshot, ScanCache
from ..export import ExportHandler
from ..models import DiskDataModel, FileNode
from ..scanner import FileSystemScanner, ScanCancelledError
from .chart_widget import SizeChartWidget
from .history_window import SpaceHistoryWindow
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
        except MemoryError:
            _logger.exception("Out of memory while scanning %s", self._path)
            self.error.emit("内存不足，无法完成扫描。请关闭其它高占用程序后重试。")
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


class SnapshotLoadWorker(QThread):
    """Background worker that loads a cached snapshot file."""

    finished = pyqtSignal(object, object, object)  # (FileNode|None, CacheSnapshot, fallback_path)
    error = pyqtSignal(str, object, object)  # (message, CacheSnapshot, fallback_path)

    def __init__(self, cache: ScanCache, snapshot: CacheSnapshot, fallback_path: Optional[str]) -> None:
        super().__init__()
        self._cache = cache
        self._snapshot = snapshot
        self._fallback_path = fallback_path

    def run(self) -> None:
        try:
            node = self._cache.load_snapshot(self._snapshot.cache_file)
            self.finished.emit(node, self._snapshot, self._fallback_path)
        except MemoryError:
            self.error.emit("内存不足，无法加载缓存。", self._snapshot, self._fallback_path)
        except Exception as exc:  # pragma: no cover - defensive
            self.error.emit(str(exc), self._snapshot, self._fallback_path)


class BaselineSnapshotLoadWorker(QThread):
    """Background worker that loads a baseline cache snapshot."""

    finished = pyqtSignal(object, object)  # (FileNode|None, CacheSnapshot)
    error = pyqtSignal(str, object)  # (message, CacheSnapshot)

    def __init__(self, cache: ScanCache, snapshot: CacheSnapshot) -> None:
        super().__init__()
        self._cache = cache
        self._snapshot = snapshot

    def run(self) -> None:
        try:
            node = self._cache.load_snapshot(self._snapshot.cache_file)
            self.finished.emit(node, self._snapshot)
        except MemoryError:
            self.error.emit("内存不足，无法加载基线缓存。", self._snapshot)
        except Exception as exc:  # pragma: no cover - defensive
            self.error.emit(str(exc), self._snapshot)


class HistoryTrendLoadWorker(QThread):
    """Background worker that loads lightweight history trend snapshots."""

    finished = pyqtSignal(str, object)  # (disk_path, snapshots)
    error = pyqtSignal(str, str)  # (message, disk_path)

    def __init__(self, cache: ScanCache, disk_path: str) -> None:
        super().__init__()
        self._cache = cache
        self._disk_path = disk_path

    def run(self) -> None:
        try:
            snapshots = self._cache.list_history_trends(self._disk_path, max_snapshots=60)
            self.finished.emit(self._disk_path, snapshots)
        except MemoryError:
            self.error.emit("内存不足，无法加载历史变化数据。", self._disk_path)
        except Exception as exc:  # pragma: no cover - defensive
            self.error.emit(str(exc), self._disk_path)


class MainWindow(QMainWindow):
    """DiskExplorer main application window."""

    _I18N = {
        "en": {
            "title": "DiskExplorer - Disk Space Analyzer",
            "path": "Path:",
            "scan_selected": "Scan Selected Path",
            "cancel": "Cancel",
            "compare": "Compare with Cache",
            "compare_off": "Exit Compare",
            "rescan": "Re-scan",
            "history_back": "Back",
            "select_compare_cache": "Select Compare Cache...",
            "select_disk_cache": "Select This Disk History Cache...",
            "disk_cache_title": "Choose Disk Cache Snapshot",
            "disk_cache_prompt": "Choose one historical cache snapshot:",
            "disk_no_cache": "No historical cache found for {disk}. A re-scan will start.",
            "ready": "Ready. Select a disk or folder to scan.",
            "scan_in_progress": "Scan in progress",
            "scan_in_progress_msg": "A scan is already running. Cancel it first.",
            "use_cache_title": "Use cached data?",
            "cache_exists": "A cached scan from {mins:.0f} minute(s) ago exists.\nUse cached data? (No = re-scan)",
            "scanning": "Scanning: {path}",
            "scanning_status": "Scanning {path}...",
            "loading_cache": "Loading cache: {path}",
            "loading_cache_status": "Loading cached snapshot...",
            "loading_baseline": "Loading baseline cache: {label}",
            "loading_baseline_status": "Loading baseline snapshot...",
            "scanned": "Scanned {count:,} items... {path}",
            "done": "Done. {size} in {files:,} files. Scanned {count:,} items in {elapsed:.1f}s ({throughput:,.0f} items/s).",
            "error": "Error: {message}",
            "scan_error": "Scan Error",
            "cache_loaded_direct": "Loaded cached result: {label}",
            "save_cache_title": "Save Cache Before Exit?",
            "save_cache_prompt": "The current scan result has not been saved yet.\nSave it before exiting?",
            "compare_up": "Back to Parent Comparison",
            "switch_history_cache": "Switch History Cache...",
            "baseline_none": "Baseline cache: none",
            "baseline_label": "Baseline cache: {label}",
            "current_none": "Current snapshot: unsaved/new scan",
            "current_label": "Current snapshot: {label}",
            "compare_cache_title": "Select Baseline Cache",
            "compare_cache_prompt": "Choose one cache snapshot to compare against:",
            "compare_cache_selected": "Compare baseline set: {label}",
            "history_space": "Space History",
            "history_space_title": "Space History",
            "history_disk_title": "Choose Disk",
            "history_disk_prompt": "Choose a disk to generate history trend:",
            "history_no_cache": "No historical cache for {disk}.",
            "history_loading": "Loading history trend: {disk}",
            "history_loading_status": "Loading history trend data...",
            "history_cache_menu": "All History Caches",
            "quick_load_history_cache": "Quick Load",
            "quick_delete_history_cache": "Quick Delete",
            "delete_current_cache": "Delete Current Cache",
            "no_history_cache": "No historical cache",
            "cache_delete_confirm_title": "Delete Historical Cache",
            "cache_delete_confirm": "Delete this historical cache?\n\n{label}",
            "delete_current_cache_confirm": "Delete the current cache snapshot?\n\n{label}",
            "cache_deleted": "Deleted cache: {label}",
            "cache_delete_failed": "Could not delete cache (already removed or inaccessible).",
            "cancelling": "Cancelling...",
            "could_not_locate": "Could not locate: {path}",
            "select_folder": "Select Folder to Scan",
            "cache_cleared_title": "Cache Cleared",
            "cache_cleared": "All cached scan data has been removed.",
            "select_cache_dir": "Select Cache Directory",
            "cache_updated_title": "Cache Directory Updated",
            "cache_updated": "Cache directory set to:\n{dir}\n\nPreviously cached scans from the old directory are no longer used.",
            "nothing_export": "Nothing to export",
            "scan_first": "Please scan a folder first.",
            "about_title": "About DiskExplorer",
            "compare_no_root": "Please scan a folder first before comparing.",
            "compare_no_baseline": "No previous cache exists for this path. Scan once, then re-scan and compare.",
            "file_menu": "&File",
            "view_menu": "&View",
            "help_menu": "&Help",
            "lang_menu": "Language",
            "theme_menu": "Theme",
            "theme_meadow": "Pixel Meadow",
            "theme_dungeon": "Pixel Dungeon",
            "cover_image": "Select Cover Image...",
            "cover_reset": "Reset Cover to Default",
            "cover_filter": "Image Files (*.png *.jpg *.jpeg *.bmp *.webp)",
            "cover_title": "Choose Cover Image",
            "cover_invalid": "Could not load this image file.",
            "cover_missing": "Saved cover image was not found. Reverted to default cover.",
            "scan_folder": "&Scan Folder...",
            "export_csv": "Export as &CSV...",
            "export_html": "Export as &HTML...",
            "export_json": "Export as &JSON...",
            "quit": "&Quit",
            "refresh": "&Refresh / Re-scan",
            "clear_cache": "Clear &Cache",
            "set_cache_dir": "Set Cache &Directory...",
            "manual_compare": "Manual &Compare with Cache",
            "about": "&About",
            "status_compare_on": "Comparison mode enabled (current vs previous cache).",
            "status_compare_off": "Comparison mode disabled.",
            "delete_item_title": "Delete Item",
            "delete_item_confirm": "Are you sure you want to delete this item?\n\n{path}",
            "delete_success": "Deleted: {path}",
            "delete_failed": "Delete failed: {message}",
        },
        "zh": {
            "title": "DiskExplorer - 磁盘空间分析器",
            "path": "路径:",
            "scan_selected": "扫描所选路径",
            "cancel": "取消",
            "compare": "与缓存对比",
            "compare_off": "退出对比",
            "rescan": "重新扫描",
            "history_back": "返回",
            "select_compare_cache": "选择对比缓存...",
            "select_disk_cache": "选择该盘历史缓存...",
            "disk_cache_title": "选择该盘历史缓存",
            "disk_cache_prompt": "请选择一个历史缓存快照：",
            "disk_no_cache": "{disk} 暂无历史缓存，将开始重新扫描。",
            "ready": "准备就绪，请先选择磁盘或文件夹进行扫描。",
            "scan_in_progress": "扫描进行中",
            "scan_in_progress_msg": "已有扫描任务在运行，请先取消后再试。",
            "use_cache_title": "使用缓存数据？",
            "cache_exists": "检测到约 {mins:.0f} 分钟前的缓存结果。\n是否使用缓存？（选否将重新扫描）",
            "scanning": "扫描中: {path}",
            "scanning_status": "正在扫描 {path}...",
            "loading_cache": "加载缓存中: {path}",
            "loading_cache_status": "正在加载历史缓存快照...",
            "loading_baseline": "加载对比基线: {label}",
            "loading_baseline_status": "正在加载对比基线快照...",
            "scanned": "已扫描 {count:,} 项... {path}",
            "done": "完成。总大小 {size}，共 {files:,} 个文件。扫描 {count:,} 项，耗时 {elapsed:.1f}s（{throughput:,.0f} 项/s）。",
            "error": "错误: {message}",
            "scan_error": "扫描错误",
            "cache_loaded_direct": "已加载缓存结果：{label}",
            "save_cache_title": "退出前保存缓存？",
            "save_cache_prompt": "当前扫描结果尚未保存。\n是否在退出前保存？",
            "compare_up": "返回上一级对比",
            "switch_history_cache": "切换历史缓存...",
            "baseline_none": "历史缓存：未选择",
            "baseline_label": "历史缓存：{label}",
            "current_none": "当前快照：未保存/新扫描",
            "current_label": "当前快照：{label}",
            "compare_cache_title": "选择对比基线缓存",
            "compare_cache_prompt": "请选择一个缓存快照作为对比基线：",
            "compare_cache_selected": "已设置对比基线：{label}",
            "history_space": "空间历史变化",
            "history_space_title": "空间历史变化",
            "history_disk_title": "选择磁盘",
            "history_disk_prompt": "请选择一个磁盘生成历史变化图：",
            "history_no_cache": "{disk} 暂无历史缓存。",
            "history_loading": "加载历史变化中: {disk}",
            "history_loading_status": "正在加载历史变化数据...",
            "history_cache_menu": "全部历史缓存",
            "quick_load_history_cache": "快速读取",
            "quick_delete_history_cache": "快速删除",
            "delete_current_cache": "删除当前缓存",
            "no_history_cache": "暂无历史缓存",
            "cache_delete_confirm_title": "删除历史缓存",
            "cache_delete_confirm": "确定删除该历史缓存吗？\n\n{label}",
            "delete_current_cache_confirm": "确定删除当前缓存快照吗？\n\n{label}",
            "cache_deleted": "已删除缓存：{label}",
            "cache_delete_failed": "删除失败（缓存可能已不存在或不可访问）。",
            "cancelling": "正在取消...",
            "could_not_locate": "无法定位: {path}",
            "select_folder": "选择要扫描的文件夹",
            "cache_cleared_title": "缓存已清空",
            "cache_cleared": "所有缓存扫描数据已删除。",
            "select_cache_dir": "选择缓存目录",
            "cache_updated_title": "缓存目录已更新",
            "cache_updated": "缓存目录已设置为:\n{dir}\n\n旧目录中的缓存将不再使用。",
            "nothing_export": "没有可导出的数据",
            "scan_first": "请先扫描一个文件夹。",
            "about_title": "关于 DiskExplorer",
            "compare_no_root": "请先扫描一个目录，再执行对比。",
            "compare_no_baseline": "该路径暂无历史缓存。请先扫描一次，再次扫描后再点击对比。",
            "file_menu": "文件(&F)",
            "view_menu": "视图(&V)",
            "help_menu": "帮助(&H)",
            "lang_menu": "语言",
            "theme_menu": "主题",
            "theme_meadow": "像素田园",
            "theme_dungeon": "像素地牢",
            "cover_image": "选择封面图片...",
            "cover_reset": "恢复默认封面",
            "cover_filter": "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)",
            "cover_title": "选择封面图片",
            "cover_invalid": "无法加载该图片文件。",
            "cover_missing": "已保存的封面图片不存在，已恢复为默认封面。",
            "scan_folder": "扫描文件夹(&S)...",
            "export_csv": "导出为 CSV(&C)...",
            "export_html": "导出为 HTML(&H)...",
            "export_json": "导出为 JSON(&J)...",
            "quit": "退出(&Q)",
            "refresh": "刷新 / 重新扫描",
            "clear_cache": "清空缓存(&C)",
            "set_cache_dir": "设置缓存目录(&D)...",
            "manual_compare": "手动缓存对比(&M)",
            "about": "关于(&A)",
            "status_compare_on": "已开启对比模式（当前扫描 vs 历史缓存）。",
            "status_compare_off": "已退出对比模式。",
            "delete_item_title": "删除项目",
            "delete_item_confirm": "确定要删除该项目吗？\n\n{path}",
            "delete_success": "已删除：{path}",
            "delete_failed": "删除失败：{message}",
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self._language = "zh"
        self._theme = "meadow"
        self._settings = QSettings()
        self._scanner = FileSystemScanner(max_workers=4)
        self._model = DiskDataModel()
        self._cache = ScanCache()
        self._exporter = ExportHandler()
        self._scan_worker: Optional[ScanWorker] = None
        self._snapshot_load_worker: Optional[SnapshotLoadWorker] = None
        self._baseline_load_worker: Optional[BaselineSnapshotLoadWorker] = None
        self._history_load_worker: Optional[HistoryTrendLoadWorker] = None
        self._current_root: Optional[FileNode] = None
        self._pending_selected_node: Optional[FileNode] = None
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(180)
        self._selection_timer.timeout.connect(self._apply_selected_node)
        self._comparison_mode = False
        self._history_mode = False
        self._history_focus_path: Optional[str] = None
        self._compare_focus_path: Optional[str] = None
        self._pending_compare_activation = False
        self._baseline_root: Optional[FileNode] = None
        self._baseline_snapshot: Optional[CacheSnapshot] = None
        self._current_snapshot: Optional[CacheSnapshot] = None
        self._history_window: Optional[SpaceHistoryWindow] = None
        self._save_scan_immediately = False
        self._pending_cache_root: Optional[FileNode] = None
        self._history_snapshot_index: list[CacheSnapshot] = []
        self._history_snapshot_index_dirty = True
        # Timing populated by ScanWorker.scan_stats signal
        self._last_scan_elapsed: float = 0.0
        self._last_scan_count: int = 0

        self._setup_ui()
        self._setup_menu()
        self._populate_disk_bar()
        self._set_theme(self._theme)
        self._set_language(self._language)
        self._restore_cover_image_from_settings()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle(self._t("title"))
        self.resize(1200, 800)

        # --- Central widget ---
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # --- Toolbar row (disk buttons + scan/cancel) ---
        self._disk_toolbar = QToolBar("")
        self._disk_toolbar.setMovable(False)
        self.addToolBar(self._disk_toolbar)

        # --- Address bar ---
        addr_bar = QWidget()
        addr_layout = QHBoxLayout(addr_bar)
        addr_layout.setContentsMargins(4, 2, 4, 2)
        self._addr_label = QLabel(self._t("path"))
        self._scan_btn = QPushButton(self._t("scan_selected"))
        self._scan_btn.clicked.connect(self._on_scan_custom)
        self._rescan_btn = QPushButton(self._t("rescan"))
        self._rescan_btn.clicked.connect(self._on_rescan_current)
        self._cancel_btn = QPushButton(self._t("cancel"))
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._compare_btn = QPushButton(self._t("compare"))
        self._compare_btn.clicked.connect(self._on_manual_compare)
        addr_layout.addWidget(self._addr_label)
        addr_layout.addStretch()
        self._compare_up_btn = QPushButton(self._t("compare_up"))
        self._compare_up_btn.setVisible(False)
        self._compare_up_btn.setEnabled(False)
        self._compare_up_btn.clicked.connect(self._on_compare_up)
        addr_layout.addWidget(self._compare_up_btn)
        addr_layout.addWidget(self._compare_btn)
        addr_layout.addWidget(self._rescan_btn)
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
        self._tree_view.rescan_requested.connect(self._on_rescan_requested)
        self._tree_view.delete_requested.connect(self._on_delete_requested)
        self._chart_widget = SizeChartWidget()
        self._chart_widget.compare_path_requested.connect(self._on_compare_chart_clicked)
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
        self._current_label_widget = QLabel(self._t("current_none"))
        self._current_label_widget.setToolTip(self._t("current_none"))
        self._status_bar.addPermanentWidget(self._current_label_widget)
        self._baseline_label_widget = QLabel(self._t("baseline_none"))
        self._baseline_label_widget.setToolTip(self._t("baseline_none"))
        self._status_bar.addPermanentWidget(self._baseline_label_widget)
        self._status_bar.showMessage(self._t("ready"))
        self._chart_widget.show_cover()

    def _setup_menu(self) -> None:
        menu = self.menuBar()

        # File menu
        self._file_menu = menu.addMenu(self._t("file_menu"))
        self._scan_act = QAction(self._t("scan_folder"), self)
        self._scan_act.setShortcut("Ctrl+O")
        self._scan_act.triggered.connect(self._on_scan_custom)
        self._file_menu.addAction(self._scan_act)

        self._file_menu.addSeparator()
        self._export_csv_act = QAction(self._t("export_csv"), self)
        self._export_csv_act.triggered.connect(lambda: self._export("csv"))
        self._file_menu.addAction(self._export_csv_act)
        self._export_html_act = QAction(self._t("export_html"), self)
        self._export_html_act.triggered.connect(lambda: self._export("html"))
        self._file_menu.addAction(self._export_html_act)
        self._export_json_act = QAction(self._t("export_json"), self)
        self._export_json_act.triggered.connect(lambda: self._export("json"))
        self._file_menu.addAction(self._export_json_act)

        self._file_menu.addSeparator()
        self._quit_act = QAction(self._t("quit"), self)
        self._quit_act.setShortcut("Ctrl+Q")
        self._quit_act.triggered.connect(self.close)
        self._file_menu.addAction(self._quit_act)

        # View menu
        self._view_menu = menu.addMenu(self._t("view_menu"))
        self._refresh_act = QAction(self._t("refresh"), self)
        self._refresh_act.setShortcut("F5")
        self._refresh_act.triggered.connect(self._on_refresh)
        self._view_menu.addAction(self._refresh_act)
        self._clear_cache_act = QAction(self._t("clear_cache"), self)
        self._clear_cache_act.triggered.connect(self._on_clear_cache)
        self._view_menu.addAction(self._clear_cache_act)
        self._set_cache_dir_act = QAction(self._t("set_cache_dir"), self)
        self._set_cache_dir_act.triggered.connect(self._on_set_cache_dir)
        self._view_menu.addAction(self._set_cache_dir_act)
        self._delete_current_cache_act = QAction(self._t("delete_current_cache"), self)
        self._delete_current_cache_act.triggered.connect(self._on_delete_current_cache)
        self._view_menu.addAction(self._delete_current_cache_act)

        self._view_menu.addSeparator()
        self._history_space_act = QAction(self._t("history_space"), self)
        self._history_space_act.triggered.connect(self._on_history_space)
        self._view_menu.addAction(self._history_space_act)
        self._select_compare_cache_act = QAction(self._t("select_compare_cache"), self)
        self._select_compare_cache_act.triggered.connect(self._on_select_compare_cache)
        self._view_menu.addAction(self._select_compare_cache_act)

        self._view_menu.addSeparator()
        self._history_cache_menu = self._view_menu.addMenu(self._t("history_cache_menu"))
        self._quick_load_history_menu = self._history_cache_menu.addMenu(self._t("quick_load_history_cache"))
        self._quick_delete_history_menu = self._history_cache_menu.addMenu(self._t("quick_delete_history_cache"))
        self._history_cache_menu.aboutToShow.connect(self._refresh_history_cache_menus)

        # Help menu
        self._help_menu = menu.addMenu(self._t("help_menu"))
        self._about_act = QAction(self._t("about"), self)
        self._about_act.triggered.connect(self._on_about)
        self._help_menu.addAction(self._about_act)
        self._help_menu.addSeparator()
        self._switch_history_cache_act = QAction(self._t("switch_history_cache"), self)
        self._switch_history_cache_act.triggered.connect(self._on_select_compare_cache)
        self._help_menu.addAction(self._switch_history_cache_act)

        self._lang_menu = menu.addMenu(self._t("lang_menu"))
        self._lang_zh_act = QAction("中文", self)
        self._lang_zh_act.triggered.connect(lambda: self._set_language("zh"))
        self._lang_en_act = QAction("English", self)
        self._lang_en_act.triggered.connect(lambda: self._set_language("en"))
        self._lang_menu.addAction(self._lang_zh_act)
        self._lang_menu.addAction(self._lang_en_act)

        self._theme_menu = menu.addMenu(self._t("theme_menu"))
        self._theme_meadow_act = QAction(self._t("theme_meadow"), self)
        self._theme_meadow_act.triggered.connect(lambda: self._set_theme("meadow"))
        self._theme_dungeon_act = QAction(self._t("theme_dungeon"), self)
        self._theme_dungeon_act.triggered.connect(lambda: self._set_theme("dungeon"))
        self._theme_menu.addAction(self._theme_meadow_act)
        self._theme_menu.addAction(self._theme_dungeon_act)
        self._theme_menu.addSeparator()
        self._cover_image_act = QAction(self._t("cover_image"), self)
        self._cover_image_act.triggered.connect(self._on_select_cover_image)
        self._cover_reset_act = QAction(self._t("cover_reset"), self)
        self._cover_reset_act.triggered.connect(self._on_reset_cover_image)
        self._theme_menu.addAction(self._cover_image_act)
        self._theme_menu.addAction(self._cover_reset_act)

    def _populate_disk_bar(self) -> None:
        """Add one button per detected disk/mount point."""
        disks = FileSystemScanner.list_disks()
        for disk in disks:
            btn = QPushButton(disk)
            btn.setFixedWidth(80)
            btn.clicked.connect(lambda checked, d=disk: self._on_disk_left_clicked(d))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, b=btn, d=disk: self._on_disk_context_menu(d, b, pos)
            )
            self._disk_toolbar.addWidget(btn)

    def _t(self, key: str, **kwargs) -> str:
        text = self._I18N.get(self._language, self._I18N["en"]).get(key, key)
        return text.format(**kwargs) if kwargs else text

    def _set_language(self, language: str) -> None:
        self._language = "zh" if language == "zh" else "en"
        self.setWindowTitle(self._t("title"))
        if self._current_root is None:
            self._addr_label.setText(self._t("path"))
        else:
            self._addr_label.setText(
                f"{self._t('path')} {self._current_root.path}  [{self._current_root.formatted_size}]"
            )
        self._scan_btn.setText(self._t("scan_selected"))
        self._rescan_btn.setText(self._t("rescan"))
        self._cancel_btn.setText(self._t("cancel"))
        self._compare_up_btn.setText(self._t("compare_up"))
        self._compare_btn.setText(self._t("compare_off") if self._comparison_mode else self._t("compare"))

        self._file_menu.setTitle(self._t("file_menu"))
        self._scan_act.setText(self._t("scan_folder"))
        self._export_csv_act.setText(self._t("export_csv"))
        self._export_html_act.setText(self._t("export_html"))
        self._export_json_act.setText(self._t("export_json"))
        self._quit_act.setText(self._t("quit"))

        self._view_menu.setTitle(self._t("view_menu"))
        self._refresh_act.setText(self._t("refresh"))
        self._clear_cache_act.setText(self._t("clear_cache"))
        self._set_cache_dir_act.setText(self._t("set_cache_dir"))
        self._delete_current_cache_act.setText(self._t("delete_current_cache"))
        self._history_space_act.setText(self._t("history_space"))
        self._select_compare_cache_act.setText(self._t("select_compare_cache"))
        self._history_cache_menu.setTitle(self._t("history_cache_menu"))
        self._quick_load_history_menu.setTitle(self._t("quick_load_history_cache"))
        self._quick_delete_history_menu.setTitle(self._t("quick_delete_history_cache"))
        self._switch_history_cache_act.setText(self._t("switch_history_cache"))

        self._help_menu.setTitle(self._t("help_menu"))
        self._about_act.setText(self._t("about"))
        self._lang_menu.setTitle(self._t("lang_menu"))
        self._theme_menu.setTitle(self._t("theme_menu"))
        self._theme_meadow_act.setText(self._t("theme_meadow"))
        self._theme_dungeon_act.setText(self._t("theme_dungeon"))
        self._cover_image_act.setText(self._t("cover_image"))
        self._cover_reset_act.setText(self._t("cover_reset"))

        self._tree_view.set_language(self._language)
        self._chart_widget.set_language(self._language)
        self._recent_panel.set_language(self._language)
        if self._history_window is not None:
            self._history_window.set_language(self._language)
        self._refresh_history_cache_menus()
        self._refresh_view_actions_state()
        self._refresh_current_snapshot_indicator()
        self._refresh_baseline_indicator()
        self._refresh_compare_controls()
        if self._comparison_mode:
            self._chart_widget.show_comparison(self._current_root, self._baseline_root, self._compare_focus_path)

    def _set_theme(self, theme: str) -> None:
        self._theme = "dungeon" if theme == "dungeon" else "meadow"
        self._chart_widget.set_cover_theme(self._theme)
        self._tree_view.set_theme(self._theme)
        if self._history_window is not None:
            self._history_window.set_theme(self._theme)

        if self._theme == "dungeon":
            self.setStyleSheet(
                "QMainWindow, QWidget {"
                "background-color: #1f2238;"
                "color: #dde6ff;"
                "}"
                "QPushButton {"
                "background-color: #2f3661;"
                "border: 2px solid #7f8cff;"
                "padding: 4px 10px;"
                "font-weight: 600;"
                "}"
                "QPushButton:hover { background-color: #3d4678; }"
                "QMenuBar, QMenu { background-color: #252941; color: #dde6ff; }"
                "QHeaderView::section { background-color: #2f3661; color: #dde6ff; }"
            )
        else:
            self.setStyleSheet(
                "QMainWindow, QWidget {"
                "background-color: #f3f9ff;"
                "color: #1f3450;"
                "}"
                "QPushButton {"
                "background-color: #f6f1d5;"
                "border: 2px solid #629f4f;"
                "padding: 4px 10px;"
                "font-weight: 600;"
                "}"
                "QPushButton:hover { background-color: #ecf7cb; }"
                "QMenuBar, QMenu { background-color: #e6f2ff; color: #1f3450; }"
                "QHeaderView::section { background-color: #d7ebff; color: #1f3450; }"
            )

    def _restore_cover_image_from_settings(self) -> None:
        image_path = str(self._settings.value("ui/cover_image", "") or "")
        if not image_path:
            return
        if not os.path.exists(image_path):
            self._chart_widget.clear_cover_image()
            self._settings.remove("ui/cover_image")
            self._status_bar.showMessage(self._t("cover_missing"))
            return
        if not self._chart_widget.set_cover_image(image_path):
            self._chart_widget.clear_cover_image()
            self._settings.remove("ui/cover_image")
            self._status_bar.showMessage(self._t("cover_invalid"))

    def _on_select_cover_image(self) -> None:
        image_path, _ = QFileDialog.getOpenFileName(
            self,
            self._t("cover_title"),
            "",
            self._t("cover_filter"),
        )
        if not image_path:
            return
        if not self._chart_widget.set_cover_image(image_path):
            QMessageBox.warning(self, self._t("cover_title"), self._t("cover_invalid"))
            return
        self._settings.setValue("ui/cover_image", image_path)
        self._chart_widget.show_cover()

    def _on_reset_cover_image(self) -> None:
        self._chart_widget.clear_cover_image()
        self._settings.remove("ui/cover_image")
        self._chart_widget.show_cover()

    # ------------------------------------------------------------------
    # Scan lifecycle
    # ------------------------------------------------------------------

    def _start_scan(self, path: str, force_rescan: bool = False, save_after_scan: bool = False) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return
        if self._snapshot_load_worker and self._snapshot_load_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return
        if self._baseline_load_worker and self._baseline_load_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return

        self._save_scan_immediately = save_after_scan

        # Reset comparison mode when loading a new root.
        self._comparison_mode = False
        self._compare_focus_path = None
        self._compare_btn.setText(self._t("compare"))

        if not force_rescan:
            latest = self._cache.latest_snapshot(path)
            if latest is not None:
                self._start_snapshot_load(latest, fallback_path=path)
                return

        # Default baseline for compare: previous latest cache before this scan.
        latest_before_scan = self._cache.latest_snapshot(path)
        if latest_before_scan is not None:
            self._baseline_root = self._cache.load_snapshot(latest_before_scan.cache_file)
            self._baseline_snapshot = latest_before_scan
        else:
            self._baseline_root = None
            self._baseline_snapshot = None
        self._refresh_baseline_indicator()
        self._refresh_compare_controls()
        self._current_snapshot = None
        self._refresh_current_snapshot_indicator()

        self._addr_label.setText(self._t("scanning", path=path))
        self._progress_bar.setVisible(True)
        self._scan_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._status_bar.showMessage(self._t("scanning_status", path=path))

        self._scan_worker = ScanWorker(self._scanner, path)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.scan_stats.connect(self._on_scan_stats)
        self._scan_worker.start()

    def _on_scan_progress(self, count: int, path: str) -> None:
        self._status_bar.showMessage(self._t("scanned", count=count, path=path[:80]))

    def _on_scan_stats(self, elapsed: float, count: int) -> None:
        """Store performance stats emitted by the worker before finished."""
        self._last_scan_elapsed = elapsed
        self._last_scan_count = count

    def _on_scan_finished(self, node: FileNode) -> None:
        if self._save_scan_immediately:
            self._cache.save(node.path, node)
            self._current_snapshot = self._cache.latest_snapshot(node.path)
            self._pending_cache_root = None
            self._mark_history_cache_dirty()
        else:
            self._pending_cache_root = node
            self._current_snapshot = None
        self._refresh_current_snapshot_indicator()
        self._model.set_root(node.path, node)
        self._display_result(node)
        self._reset_scan_controls()
        self._refresh_view_actions_state()
        elapsed = self._last_scan_elapsed
        count = self._last_scan_count
        throughput = count / elapsed if elapsed > 0 else 0
        self._status_bar.showMessage(
            self._t(
                "done",
                size=node.formatted_size,
                files=node.file_count,
                count=count,
                elapsed=elapsed,
                throughput=throughput,
            )
        )
        _logger.info(
            "UI scan finished: path=%s  size=%s  files=%d  "
            "items=%d  elapsed=%.2fs  throughput=%.0f items/s",
            node.path, node.formatted_size, node.file_count,
            count, elapsed, throughput,
        )

    def _on_disk_left_clicked(self, disk_path: str) -> None:
        latest = self._cache.latest_snapshot(disk_path)
        if latest is None:
            self._status_bar.showMessage(self._t("disk_no_cache", disk=disk_path))
            self._start_scan(disk_path, force_rescan=True, save_after_scan=True)
            return
        self._start_snapshot_load(latest, fallback_path=disk_path)

    def _on_disk_context_menu(self, disk_path: str, button: QPushButton, pos) -> None:
        menu = QMenu(self)
        choose_act = menu.addAction(self._t("select_disk_cache"))
        rescan_act = menu.addAction(self._t("rescan"))
        action = menu.exec(button.mapToGlobal(pos))
        if action == choose_act:
            self._on_choose_disk_cache(disk_path)
        elif action == rescan_act:
            self._start_scan(disk_path, force_rescan=True, save_after_scan=True)

    def _on_choose_disk_cache(self, disk_path: str) -> None:
        snapshots = self._cache.list_snapshots(disk_path)
        if not snapshots:
            QMessageBox.information(self, self._t("history_space_title"), self._t("disk_no_cache", disk=disk_path))
            return
        chosen = self._select_snapshot_dialog(
            snapshots,
            self._t("disk_cache_title"),
            self._t("disk_cache_prompt"),
        )
        if chosen is None:
            return
        self._start_snapshot_load(chosen, fallback_path=disk_path)

    def _select_snapshot_dialog(
        self,
        snapshots: list[CacheSnapshot],
        title: str,
        prompt: str,
    ) -> Optional[CacheSnapshot]:
        labels = [snap.label for snap in snapshots]
        selected, ok = QInputDialog.getItem(self, title, prompt, labels, 0, False)
        if not ok or not selected:
            return None
        return next((snap for snap in snapshots if snap.label == selected), None)

    def _load_snapshot_as_current(self, snapshot: CacheSnapshot, fallback_path: Optional[str] = None) -> None:
        node = self._cache.load_snapshot(snapshot.cache_file)
        if node is None:
            QMessageBox.warning(
                self,
                self._t("scan_error"),
                "缓存加载失败（可能是内存不足或缓存损坏），已改为重新扫描。",
            )
            if fallback_path:
                self._start_scan(fallback_path, force_rescan=True, save_after_scan=True)
            return
        self._apply_snapshot_as_current(snapshot, node)

    def _apply_snapshot_as_current(self, snapshot: CacheSnapshot, node: FileNode) -> None:
        self._comparison_mode = False
        self._history_mode = False
        self._compare_focus_path = None
        self._history_focus_path = None
        self._compare_btn.setText(self._t("compare"))
        self._pending_cache_root = None
        self._current_snapshot = snapshot
        self._refresh_current_snapshot_indicator()
        self._refresh_compare_controls()
        self._refresh_view_actions_state()
        self._display_result(node)
        self._status_bar.showMessage(self._t("cache_loaded_direct", label=snapshot.label))

    def _start_snapshot_load(self, snapshot: CacheSnapshot, fallback_path: Optional[str]) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return
        if self._snapshot_load_worker and self._snapshot_load_worker.isRunning():
            return
        if self._baseline_load_worker and self._baseline_load_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return

        self._addr_label.setText(self._t("loading_cache", path=snapshot.disk_path))
        self._progress_bar.setVisible(True)
        self._scan_btn.setEnabled(False)
        self._rescan_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._status_bar.showMessage(self._t("loading_cache_status"))

        self._snapshot_load_worker = SnapshotLoadWorker(self._cache, snapshot, fallback_path)
        self._snapshot_load_worker.finished.connect(self._on_snapshot_loaded)
        self._snapshot_load_worker.error.connect(self._on_snapshot_load_error)
        self._snapshot_load_worker.start()

    def _on_snapshot_loaded(self, node: Optional[FileNode], snapshot: CacheSnapshot, fallback_path: Optional[str]) -> None:
        self._snapshot_load_worker = None
        self._progress_bar.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._rescan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

        if node is None:
            QMessageBox.warning(
                self,
                self._t("scan_error"),
                "缓存加载失败（可能是内存不足或缓存损坏），已改为重新扫描。",
            )
            if fallback_path:
                self._start_scan(fallback_path, force_rescan=True, save_after_scan=True)
            return

        self._apply_snapshot_as_current(snapshot, node)

    def _on_snapshot_load_error(self, message: str, snapshot: CacheSnapshot, fallback_path: Optional[str]) -> None:
        self._snapshot_load_worker = None
        self._progress_bar.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._rescan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        QMessageBox.warning(self, self._t("scan_error"), message)
        if fallback_path:
            self._start_scan(fallback_path, force_rescan=True, save_after_scan=True)

    def _on_scan_error(self, message: str) -> None:
        self._reset_scan_controls()
        self._status_bar.showMessage(self._t("error", message=message))
        QMessageBox.warning(self, self._t("scan_error"), message)

    def _on_cancel(self) -> None:
        self._scanner.cancel()
        self._status_bar.showMessage(self._t("cancelling"))

    def _reset_scan_controls(self) -> None:
        self._progress_bar.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _display_result(self, node: FileNode) -> None:
        self._current_root = node
        snapshot_text = ""
        if self._current_snapshot is not None:
            snapshot_text = f"  ({self._t('current_label', label=self._current_snapshot.label)})"
        self._addr_label.setText(f"{self._t('path')} {node.path}  [{node.formatted_size}]{snapshot_text}")
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
        if self._history_mode:
            pass
        elif self._comparison_mode:
            self._compare_focus_path = node.path
            self._chart_widget.show_comparison(self._current_root, self._baseline_root, node.path)
        else:
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
            self._status_bar.showMessage(self._t("could_not_locate", path=path))

    def _on_compare_chart_clicked(self, path: str) -> None:
        if self._tree_view.navigate_to_path(path):
            self._compare_focus_path = path
            self._chart_widget.show_comparison(self._current_root, self._baseline_root, path)
            self._refresh_compare_controls()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_scan_custom(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self._t("select_folder"))
        if path:
            self._start_scan(path)

    def _on_rescan_current(self) -> None:
        if self._current_root is None:
            return
        self._start_scan(self._current_root.path, force_rescan=True, save_after_scan=True)

    def _on_manual_compare(self) -> None:
        if self._comparison_mode:
            self._comparison_mode = False
            self._compare_btn.setText(self._t("compare"))
            if self._pending_selected_node is not None:
                self._chart_widget.display(self._pending_selected_node)
            elif self._current_root is not None:
                self._chart_widget.display(self._current_root)
            self._status_bar.showMessage(self._t("status_compare_off"))
            self._refresh_compare_controls()
            return

        if self._current_root is None:
            QMessageBox.information(self, self._t("scan_in_progress"), self._t("compare_no_root"))
            return
        if self._baseline_root is None:
            if not self._choose_compare_cache(activate_compare=True):
                return
            return

        self._comparison_mode = True
        self._compare_focus_path = self._current_root.path
        self._compare_btn.setText(self._t("compare_off"))
        self._chart_widget.show_comparison(self._current_root, self._baseline_root, self._compare_focus_path)
        self._status_bar.showMessage(self._t("status_compare_on"))
        self._refresh_compare_controls()

    def _on_refresh(self) -> None:
        if self._current_root:
            self._start_scan(self._current_root.path, force_rescan=True, save_after_scan=True)

    def _on_select_compare_cache(self) -> None:
        self._choose_compare_cache(activate_compare=False)

    def _choose_compare_cache(self, activate_compare: bool) -> bool:
        if self._current_root is None:
            QMessageBox.information(self, self._t("scan_in_progress"), self._t("compare_no_root"))
            return False

        snapshots = self._cache.list_snapshots(self._current_root.path)
        if not snapshots:
            QMessageBox.information(self, self._t("use_cache_title"), self._t("compare_no_baseline"))
            return False

        labels = [snap.label for snap in snapshots]
        selected, ok = QInputDialog.getItem(
            self,
            self._t("compare_cache_title"),
            self._t("compare_cache_prompt"),
            labels,
            0,
            False,
        )
        if not ok or not selected:
            return False

        chosen = next((snap for snap in snapshots if snap.label == selected), None)
        if chosen is None:
            return False
        self._pending_compare_activation = activate_compare
        self._start_baseline_load(chosen)
        return True

    def _start_baseline_load(self, snapshot: CacheSnapshot) -> None:
        if self._baseline_load_worker and self._baseline_load_worker.isRunning():
            return
        if self._scan_worker and self._scan_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return
        if self._snapshot_load_worker and self._snapshot_load_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return
        self._addr_label.setText(self._t("loading_baseline", label=snapshot.label))
        self._progress_bar.setVisible(True)
        self._scan_btn.setEnabled(False)
        self._rescan_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._status_bar.showMessage(self._t("loading_baseline_status"))

        self._baseline_load_worker = BaselineSnapshotLoadWorker(self._cache, snapshot)
        self._baseline_load_worker.finished.connect(self._on_baseline_loaded)
        self._baseline_load_worker.error.connect(self._on_baseline_load_error)
        self._baseline_load_worker.start()

    def _on_baseline_loaded(self, node: Optional[FileNode], snapshot: CacheSnapshot) -> None:
        self._baseline_load_worker = None
        self._progress_bar.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._rescan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

        if node is None:
            QMessageBox.warning(self, self._t("scan_error"), self._t("compare_no_baseline"))
            self._pending_compare_activation = False
            return

        self._baseline_root = node
        self._baseline_snapshot = snapshot
        self._refresh_baseline_indicator()
        self._status_bar.showMessage(self._t("compare_cache_selected", label=snapshot.label))

        if self._comparison_mode or self._pending_compare_activation:
            self._comparison_mode = True
            if self._current_root is not None:
                if not self._compare_focus_path:
                    self._compare_focus_path = self._current_root.path
                self._compare_btn.setText(self._t("compare_off"))
                self._chart_widget.show_comparison(self._current_root, self._baseline_root, self._compare_focus_path)
                self._status_bar.showMessage(self._t("status_compare_on"))

        self._pending_compare_activation = False
        self._refresh_compare_controls()

    def _on_baseline_load_error(self, message: str, snapshot: CacheSnapshot) -> None:
        self._baseline_load_worker = None
        self._progress_bar.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._rescan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._pending_compare_activation = False
        QMessageBox.warning(self, self._t("scan_error"), message)

    def _on_compare_up(self) -> None:
        if not self._comparison_mode or self._current_root is None or self._baseline_root is None:
            return
        next_path = self._compare_parent_path(self._compare_focus_path or self._current_root.path)
        self._compare_focus_path = next_path
        self._chart_widget.show_comparison(self._current_root, self._baseline_root, next_path)
        self._tree_view.navigate_to_path(next_path)
        self._refresh_compare_controls()

    def _on_rescan_requested(self, path: str) -> None:
        self._start_scan(path, force_rescan=True, save_after_scan=True)

    def _on_delete_requested(self, path: str, is_dir: bool) -> None:
        choice = QMessageBox.question(
            self,
            self._t("delete_item_title"),
            self._t("delete_item_confirm", path=path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return

        try:
            if is_dir:
                shutil.rmtree(path)
            else:
                os.remove(path)
        except Exception as exc:
            QMessageBox.warning(self, self._t("delete_item_title"), self._t("delete_failed", message=str(exc)))
            return

        self._status_bar.showMessage(self._t("delete_success", path=path))
        if self._current_root is not None:
            self._start_scan(self._current_root.path, force_rescan=True, save_after_scan=True)

    def _on_history_space(self) -> None:
        disks = self._cache.list_cached_paths() or FileSystemScanner.list_disks()
        selected, ok = QInputDialog.getItem(
            self,
            self._t("history_disk_title"),
            self._t("history_disk_prompt"),
            disks,
            0,
            False,
        )
        if not ok or not selected:
            return
        self._start_history_load(selected)

    def _load_history_snapshots(self, disk_path: str) -> list[HistoryTrendSnapshot]:
        return self._cache.list_history_trends(disk_path, max_snapshots=60)

    def _start_history_load(self, disk_path: str) -> None:
        if self._history_load_worker and self._history_load_worker.isRunning():
            QMessageBox.warning(self, self._t("history_space_title"), self._t("history_loading_status"))
            return
        if self._scan_worker and self._scan_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return
        if self._snapshot_load_worker and self._snapshot_load_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return
        if self._baseline_load_worker and self._baseline_load_worker.isRunning():
            QMessageBox.warning(self, self._t("scan_in_progress"), self._t("scan_in_progress_msg"))
            return

        self._addr_label.setText(self._t("history_loading", disk=disk_path))
        self._progress_bar.setVisible(True)
        self._scan_btn.setEnabled(False)
        self._rescan_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._status_bar.showMessage(self._t("history_loading_status"))

        self._history_load_worker = HistoryTrendLoadWorker(self._cache, disk_path)
        self._history_load_worker.finished.connect(self._on_history_loaded)
        self._history_load_worker.error.connect(self._on_history_load_error)
        self._history_load_worker.start()

    def _on_history_loaded(self, disk_path: str, snapshots: object) -> None:
        self._history_load_worker = None
        self._progress_bar.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._rescan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

        loaded = list(snapshots)
        if not loaded:
            QMessageBox.information(self, self._t("history_space_title"), self._t("history_no_cache", disk=disk_path))
            return

        if self._history_window is None:
            self._history_window = SpaceHistoryWindow(self)
            self._history_window.set_language(self._language)
            self._history_window.set_theme(self._theme)
        self._history_window.open_history(disk_path, loaded)

    def _on_history_load_error(self, message: str, disk_path: str) -> None:
        self._history_load_worker = None
        self._progress_bar.setVisible(False)
        self._scan_btn.setEnabled(True)
        self._rescan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        QMessageBox.warning(self, self._t("history_space_title"), message)

    def _refresh_history_cache_menus(self) -> None:
        if self._history_snapshot_index_dirty:
            self._history_snapshot_index = self._cache.list_all_snapshots()
            self._history_snapshot_index_dirty = False

        self._quick_load_history_menu.clear()
        self._quick_delete_history_menu.clear()

        snapshots = self._history_snapshot_index
        if not snapshots:
            empty_load = QAction(self._t("no_history_cache"), self)
            empty_load.setEnabled(False)
            self._quick_load_history_menu.addAction(empty_load)

            empty_delete = QAction(self._t("no_history_cache"), self)
            empty_delete.setEnabled(False)
            self._quick_delete_history_menu.addAction(empty_delete)
            return

        for snapshot in snapshots:
            load_act = QAction(snapshot.label, self)
            load_act.triggered.connect(lambda checked=False, s=snapshot: self._on_quick_load_snapshot(s))
            self._quick_load_history_menu.addAction(load_act)

            delete_act = QAction(snapshot.label, self)
            delete_act.triggered.connect(lambda checked=False, s=snapshot: self._on_quick_delete_snapshot(s))
            self._quick_delete_history_menu.addAction(delete_act)

    def _on_quick_load_snapshot(self, snapshot: CacheSnapshot) -> None:
        self._start_snapshot_load(snapshot, fallback_path=snapshot.disk_path)

    def _on_quick_delete_snapshot(self, snapshot: CacheSnapshot) -> None:
        choice = QMessageBox.question(
            self,
            self._t("cache_delete_confirm_title"),
            self._t("cache_delete_confirm", label=snapshot.label),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return

        removed = self._cache.remove_snapshot(snapshot)
        if not removed:
            QMessageBox.warning(self, self._t("cache_delete_confirm_title"), self._t("cache_delete_failed"))
            self._mark_history_cache_dirty()
            self._refresh_history_cache_menus()
            return

        if self._current_snapshot is not None and self._current_snapshot.cache_file == snapshot.cache_file:
            self._current_snapshot = None
            self._refresh_current_snapshot_indicator()

        baseline_removed = (
            self._baseline_snapshot is not None and self._baseline_snapshot.cache_file == snapshot.cache_file
        )
        if baseline_removed:
            self._baseline_snapshot = None
            self._baseline_root = None
            if self._comparison_mode:
                self._comparison_mode = False
                self._compare_focus_path = None
                self._compare_btn.setText(self._t("compare"))
                if self._pending_selected_node is not None:
                    self._chart_widget.display(self._pending_selected_node)
                elif self._current_root is not None:
                    self._chart_widget.display(self._current_root)
            self._refresh_baseline_indicator()
            self._refresh_compare_controls()

        self._status_bar.showMessage(self._t("cache_deleted", label=snapshot.label))
        self._mark_history_cache_dirty()
        self._refresh_history_cache_menus()

    def _on_delete_current_cache(self) -> None:
        if self._current_snapshot is None:
            QMessageBox.information(self, self._t("cache_delete_confirm_title"), self._t("no_history_cache"))
            return

        snapshot = self._current_snapshot
        choice = QMessageBox.question(
            self,
            self._t("cache_delete_confirm_title"),
            self._t("delete_current_cache_confirm", label=snapshot.label),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return

        removed = self._cache.remove_snapshot(snapshot)
        if not removed:
            QMessageBox.warning(self, self._t("cache_delete_confirm_title"), self._t("cache_delete_failed"))
            self._mark_history_cache_dirty()
            self._refresh_history_cache_menus()
            return

        if self._baseline_snapshot is not None and self._baseline_snapshot.cache_file == snapshot.cache_file:
            self._baseline_snapshot = None
            self._baseline_root = None
            if self._comparison_mode:
                self._comparison_mode = False
                self._compare_focus_path = None
                self._compare_btn.setText(self._t("compare"))
                if self._pending_selected_node is not None:
                    self._chart_widget.display(self._pending_selected_node)
                elif self._current_root is not None:
                    self._chart_widget.display(self._current_root)

        self._current_snapshot = None
        self._pending_cache_root = None
        self._refresh_current_snapshot_indicator()
        self._refresh_baseline_indicator()
        self._refresh_compare_controls()
        self._refresh_view_actions_state()
        self._mark_history_cache_dirty()
        self._refresh_history_cache_menus()
        self._status_bar.showMessage(self._t("cache_deleted", label=snapshot.label))

    def _mark_history_cache_dirty(self) -> None:
        self._history_snapshot_index_dirty = True

    def _refresh_view_actions_state(self) -> None:
        self._delete_current_cache_act.setEnabled(self._current_snapshot is not None)

    def _refresh_baseline_indicator(self) -> None:
        if self._baseline_snapshot is None:
            text = self._t("baseline_none")
        else:
            text = self._t("baseline_label", label=self._baseline_snapshot.label)
        self._baseline_label_widget.setText(text)
        self._baseline_label_widget.setToolTip(text)

    def _refresh_current_snapshot_indicator(self) -> None:
        if self._current_snapshot is None:
            text = self._t("current_none")
        else:
            text = self._t("current_label", label=self._current_snapshot.label)
        self._current_label_widget.setText(text)
        self._current_label_widget.setToolTip(text)

    def _refresh_compare_controls(self) -> None:
        can_go_up = self._can_go_compare_up()
        self._compare_up_btn.setVisible(self._comparison_mode)
        self._compare_up_btn.setEnabled(can_go_up)

    def _can_go_compare_up(self) -> bool:
        if not self._comparison_mode or self._current_root is None:
            return False
        if not self._compare_focus_path:
            return False
        return self._compare_focus_path != self._current_root.path

    def _compare_parent_path(self, path: str) -> str:
        if self._current_root is None:
            return path
        root_path = self._current_root.path
        normalized = os.path.normpath(path)
        root_normalized = os.path.normpath(root_path)
        if normalized == root_normalized:
            return root_path
        parent = os.path.dirname(normalized)
        if not parent or parent == normalized:
            return root_path
        if os.path.normpath(parent) == root_normalized:
            return root_path
        return parent

    def _on_clear_cache(self) -> None:
        self._cache.clear_all()
        self._mark_history_cache_dirty()
        self._baseline_root = None
        self._baseline_snapshot = None
        self._current_snapshot = None
        self._comparison_mode = False
        self._compare_focus_path = None
        self._compare_btn.setText(self._t("compare"))
        self._refresh_current_snapshot_indicator()
        self._refresh_baseline_indicator()
        self._refresh_compare_controls()
        self._refresh_view_actions_state()
        if self._history_window is not None:
            self._history_window.close()
        QMessageBox.information(self, self._t("cache_cleared_title"), self._t("cache_cleared"))

    def _on_set_cache_dir(self) -> None:
        new_dir = QFileDialog.getExistingDirectory(
            self,
            self._t("select_cache_dir"),
            str(self._cache.cache_dir),
        )
        if new_dir:
            self._cache = ScanCache(cache_dir=new_dir)
            self._mark_history_cache_dirty()
            self._baseline_root = None
            self._baseline_snapshot = None
            self._current_snapshot = None
            self._comparison_mode = False
            self._compare_focus_path = None
            self._compare_btn.setText(self._t("compare"))
            self._refresh_current_snapshot_indicator()
            self._refresh_baseline_indicator()
            self._refresh_compare_controls()
            self._refresh_view_actions_state()
            if self._history_window is not None:
                self._history_window.close()
            QMessageBox.information(
                self,
                self._t("cache_updated_title"),
                self._t("cache_updated", dir=new_dir),
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            event.accept()
            return

        if self._pending_cache_root is None:
            event.accept()
            return

        choice = QMessageBox.question(
            self,
            self._t("save_cache_title"),
            self._t("save_cache_prompt"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return

        if choice == QMessageBox.StandardButton.Yes:
            try:
                self._cache.save(self._pending_cache_root.path, self._pending_cache_root)
                self._current_snapshot = self._cache.latest_snapshot(self._pending_cache_root.path)
                self._pending_cache_root = None
                self._mark_history_cache_dirty()
                self._refresh_current_snapshot_indicator()
            except Exception as exc:
                QMessageBox.critical(self, self._t("scan_error"), str(exc))
                event.ignore()
                return

        event.accept()

    def _export(self, fmt: str) -> None:
        if not self._current_root:
            QMessageBox.information(self, self._t("nothing_export"), self._t("scan_first"))
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
            self._t("about_title"),
            "<h3>DiskExplorer v1.0</h3>"
            "<p>A lightweight disk space analysis tool.</p>"
            "<p>Visualise your disk usage in a hierarchical tree view "
            "with charts and export capabilities.</p>",
        )
