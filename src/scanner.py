"""File system scanner for DiskExplorer."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

import psutil

from .models import FileNode

_logger = logging.getLogger(__name__)


class ScanCancelledError(Exception):
    """Raised when a scan is cancelled by the user."""


class FileSystemScanner:
    """Scans a directory tree and builds a FileNode hierarchy.

    Supports progress callbacks and cancellation.
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._max_workers = max_workers
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._scanned_count = 0
        # Timestamp of the last progress callback emission.  Reset each scan.
        # Intentionally not lock-protected — occasional duplicate emissions
        # from parallel threads are harmless for throttling purposes.
        self._last_progress_time: float = 0.0

    # Minimum interval (seconds) between progress_callback invocations.
    # This prevents flooding the Qt event queue on large scans (400 k+ files).
    _PROGRESS_INTERVAL = 0.10  # 100 ms


    @staticmethod
    def list_disks() -> List[str]:
        """Return mount points / drive letters of all available disks."""
        disks: List[str] = []
        for part in psutil.disk_partitions(all=False):
            # Skip inaccessible partitions on Windows (e.g. empty optical drives)
            if not part.mountpoint:
                continue
            disks.append(part.mountpoint)
        return disks

    @staticmethod
    def disk_usage(path: str) -> Optional[psutil._common.sdiskusage]:
        """Return disk usage statistics for *path*, or None on error."""
        try:
            return psutil.disk_usage(path)
        except PermissionError:
            return None

    def cancel(self) -> None:
        """Signal that an ongoing scan should be cancelled."""
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        """Reset the cancel flag so a new scan can be started."""
        self._cancel_event.clear()

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan_directory(
        self,
        path: str,
        depth: int = 0,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        max_depth: Optional[int] = None,
    ) -> FileNode:
        """Recursively scan *path* and return a FileNode tree.

        Args:
            path: Directory to scan.
            depth: Current recursion depth (used internally).
            progress_callback: Called with (count, current_path) as scanning
                               proceeds. May be called from worker threads.
                               Calls are time-throttled to at most once per
                               ``_PROGRESS_INTERVAL`` seconds to avoid
                               excessive UI updates on large scans.
            max_depth: Maximum recursion depth. None means unlimited.

        Returns:
            A FileNode representing *path* with all descendants populated.

        Raises:
            ScanCancelledError: If :meth:`cancel` was called during scanning.
        """
        self.reset_cancel()
        self._scanned_count = 0
        self._last_progress_time = 0.0
        return self._scan_node(path, depth, progress_callback, max_depth)

    def scan_directory_threaded(
        self,
        path: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        max_depth: Optional[int] = None,
    ) -> FileNode:
        """Like :meth:`scan_directory` but uses a thread pool for top-level
        sub-directories to speed up scanning on large paths.
        """
        self.reset_cancel()
        self._scanned_count = 0
        self._last_progress_time = 0.0
        start_time = time.monotonic()

        stat = self._safe_stat(path)
        if stat is None:
            _logger.warning("Cannot access directory: %s", path)
            return self._error_node(path, "Cannot access directory")

        root = FileNode(
            name=os.path.basename(path) or path,
            path=path,
            size=0,
            is_dir=True,
            mod_time=stat.st_mtime,
            create_time=stat.st_ctime,
        )

        try:
            entries = list(os.scandir(path))
        except PermissionError as exc:
            _logger.warning("Permission denied listing %s: %s", path, exc)
            root.error = str(exc)
            return root
        except OSError as exc:
            _logger.warning("OS error listing %s: %s", path, exc)
            root.error = str(exc)
            return root

        # Separate direct children into files and sub-directories
        file_entries = [e for e in entries if not e.is_dir(follow_symlinks=False)]
        dir_entries = [e for e in entries if e.is_dir(follow_symlinks=False)]

        # Process files directly
        for entry in file_entries:
            if self._cancel_event.is_set():
                raise ScanCancelledError("Scan cancelled")
            child = self._node_from_entry(entry)
            root.add_child(child)
            root.size += child.size
            root.file_count += 1
            with self._lock:
                self._scanned_count += 1
            if progress_callback:
                _now = time.monotonic()
                if _now - self._last_progress_time >= self._PROGRESS_INTERVAL:
                    self._last_progress_time = _now
                    progress_callback(self._scanned_count, entry.path)

        # Process sub-dirs in parallel
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_entry = {
                executor.submit(
                    self._scan_node,
                    entry.path,
                    1,
                    progress_callback,
                    max_depth,
                ): entry
                for entry in dir_entries
            }
            for future in as_completed(future_to_entry):
                if self._cancel_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise ScanCancelledError("Scan cancelled")
                try:
                    child = future.result()
                except ScanCancelledError:
                    raise
                except Exception as exc:
                    entry = future_to_entry[future]
                    _logger.warning("Error scanning %s: %s", entry.path, exc)
                    child = self._error_node(entry.path, str(exc))
                root.add_child(child)
                root.size += child.size
                root.file_count += child.file_count

        elapsed = time.monotonic() - start_time
        count = self._scanned_count
        throughput = count / elapsed if elapsed > 0 else 0
        _logger.info(
            "Scan complete: path=%s  items=%d  elapsed=%.2fs  throughput=%.0f items/s",
            path, count, elapsed, throughput,
        )
        return root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_node(
        self,
        path: str,
        depth: int,
        progress_callback: Optional[Callable[[int, str], None]],
        max_depth: Optional[int],
    ) -> FileNode:
        if self._cancel_event.is_set():
            raise ScanCancelledError("Scan cancelled")

        stat = self._safe_stat(path)
        if stat is None:
            _logger.debug("Cannot stat: %s", path)
            return self._error_node(path, "Cannot access")

        node = FileNode(
            name=os.path.basename(path) or path,
            path=path,
            size=0,
            is_dir=True,
            mod_time=stat.st_mtime,
            create_time=stat.st_ctime,
        )

        if max_depth is not None and depth >= max_depth:
            # Estimate size without going deeper
            node.size = self._fast_size(path)
            return node

        try:
            entries = list(os.scandir(path))
        except PermissionError as exc:
            _logger.debug("Permission denied: %s – %s", path, exc)
            node.error = str(exc)
            return node
        except OSError as exc:
            _logger.debug("OS error scanning %s: %s", path, exc)
            node.error = str(exc)
            return node

        for entry in entries:
            if self._cancel_event.is_set():
                raise ScanCancelledError("Scan cancelled")

            try:
                if entry.is_dir(follow_symlinks=False):
                    child = self._scan_node(entry.path, depth + 1, progress_callback, max_depth)
                else:
                    child = self._node_from_entry(entry)
                    node.file_count += 1
            except ScanCancelledError:
                raise
            except Exception as exc:
                _logger.debug("Skipping entry %s: %s", entry.path, exc)
                child = self._error_node(entry.path, str(exc))

            node.add_child(child)
            node.size += child.size
            node.file_count += child.file_count

            with self._lock:
                self._scanned_count += 1
            # Throttle: emit at most once per _PROGRESS_INTERVAL to avoid
            # flooding the UI event queue on large scans (400 k+ files).
            if progress_callback:
                _now = time.monotonic()
                if _now - self._last_progress_time >= self._PROGRESS_INTERVAL:
                    self._last_progress_time = _now
                    progress_callback(self._scanned_count, entry.path)

        return node

    def _node_from_entry(self, entry: os.DirEntry) -> FileNode:
        """Create a FileNode for a single DirEntry."""
        try:
            stat = entry.stat(follow_symlinks=False)
            size = stat.st_size
            mod_time = stat.st_mtime
            create_time = stat.st_ctime
        except OSError:
            size = 0
            mod_time = 0.0
            create_time = 0.0

        return FileNode(
            name=entry.name,
            path=entry.path,
            size=size,
            is_dir=entry.is_dir(follow_symlinks=False),
            mod_time=mod_time,
            create_time=create_time,
        )

    @staticmethod
    def _safe_stat(path: str) -> Optional[os.stat_result]:
        try:
            return os.stat(path)
        except OSError:
            return None

    @staticmethod
    def _error_node(path: str, message: str) -> FileNode:
        return FileNode(
            name=os.path.basename(path) or path,
            path=path,
            size=0,
            is_dir=True,
            mod_time=0.0,
            create_time=0.0,
            error=message,
        )

    @staticmethod
    def _fast_size(path: str) -> int:
        """Quickly sum file sizes at the top level of *path* (non-recursive)."""
        total = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def get_folder_size(self, path: str) -> int:
        """Calculate the total size of all files under *path* recursively."""
        total = 0
        try:
            for dirpath, _dirnames, filenames in os.walk(path):
                for filename in filenames:
                    fp = os.path.join(dirpath, filename)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        except OSError:
            pass
        return total
