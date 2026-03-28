"""Scan result caching for DiskExplorer."""

from __future__ import annotations

import os
import pickle
import time
from pathlib import Path
from typing import Optional

from .models import FileNode

# Default directory for cache files (relative to user home)
_DEFAULT_CACHE_DIR = Path.home() / ".diskexplorer" / "cache"
_CACHE_VERSION = 1


class ScanCache:
    """Persists and retrieves scan results using pickle serialization.

    Cache files are stored as ``<cache_dir>/<escaped_path>.pkl``.
    Each file contains a tuple of ``(version, timestamp, FileNode)``
    so that stale or incompatible cache entries can be detected.
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, disk_path: str, node: FileNode) -> None:
        """Serialize and save *node* for *disk_path*.

        Args:
            disk_path: The root path that was scanned (used as cache key).
            node: The FileNode tree to persist.
        """
        cache_file = self._cache_path(disk_path)
        payload = (_CACHE_VERSION, time.time(), node)
        with open(cache_file, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)

    def load(self, disk_path: str, max_age_seconds: Optional[float] = None) -> Optional[FileNode]:
        """Load a cached FileNode for *disk_path*.

        Args:
            disk_path: The root path that was originally scanned.
            max_age_seconds: If given, cached entries older than this many
                             seconds are considered stale and ``None`` is
                             returned.

        Returns:
            The cached FileNode, or ``None`` if there is no valid cache entry.
        """
        cache_file = self._cache_path(disk_path)
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "rb") as fh:
                payload = pickle.load(fh)
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError):
            # Corrupt or incompatible cache file – discard it
            self._try_remove(cache_file)
            return None

        if not (isinstance(payload, tuple) and len(payload) == 3):
            self._try_remove(cache_file)
            return None

        version, timestamp, node = payload

        if version != _CACHE_VERSION:
            self._try_remove(cache_file)
            return None

        if max_age_seconds is not None:
            age = time.time() - timestamp
            if age > max_age_seconds:
                return None

        if not isinstance(node, FileNode):
            self._try_remove(cache_file)
            return None

        return node

    def invalidate(self, disk_path: str) -> None:
        """Remove the cache entry for *disk_path*."""
        self._try_remove(self._cache_path(disk_path))

    def clear_all(self) -> None:
        """Delete all cache files."""
        for cache_file in self._cache_dir.glob("*.pkl"):
            self._try_remove(cache_file)

    def cache_age_seconds(self, disk_path: str) -> Optional[float]:
        """Return the age (in seconds) of the cache entry, or None if absent."""
        cache_file = self._cache_path(disk_path)
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "rb") as fh:
                payload = pickle.load(fh)
            _version, timestamp, _node = payload
            return time.time() - timestamp
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_path(self, disk_path: str) -> Path:
        """Map a disk path to its cache file path."""
        # Replace path separators and colons so the key is a valid filename
        safe = disk_path.replace(os.sep, "_").replace(":", "_").strip("_")
        if not safe:
            safe = "root"
        return self._cache_dir / f"{safe}.pkl"

    @staticmethod
    def _try_remove(path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            pass
