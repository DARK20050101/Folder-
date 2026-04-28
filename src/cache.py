"""Scan result caching for DiskExplorer."""

from __future__ import annotations

import json
import os
import pickle
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import FileNode

# Default directory for cache files: ``cache/`` folder next to the program.
# Falls back to the user home directory if the program directory is not writable.
def _get_default_cache_dir() -> Path:
    app_cache = Path(__file__).resolve().parents[1] / "cache"
    try:
        app_cache.mkdir(parents=True, exist_ok=True)
        return app_cache
    except OSError:
        return Path.home() / ".diskexplorer" / "cache"


_DEFAULT_CACHE_DIR = _get_default_cache_dir()
_CACHE_VERSION = 1


@dataclass(frozen=True)
class CacheSnapshot:
    """Metadata of a single cached snapshot."""

    cache_file: Path
    timestamp: float
    disk_path: str
    label: str


@dataclass(frozen=True)
class HistoryTrendSnapshot:
    """Lightweight trend data for one cached snapshot."""

    label: str
    timestamp: float
    disk_path: str
    level1: dict[str, int]
    level2: dict[str, dict[str, int]]


class ScanCache:
    """Persists and retrieves scan results using pickle serialization.

    Cache files are stored as ``<cache_dir>/<escaped_path>__<datetime>.pkl``.
    Each file contains a tuple of ``(version, timestamp, disk_path, FileNode)``
    so that stale or incompatible cache entries can be detected.
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        """The directory where cache files are stored."""
        return self._cache_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, disk_path: str, node: FileNode) -> None:
        """Serialize and save *node* for *disk_path*.

        Args:
            disk_path: The root path that was scanned (used as cache key).
            node: The FileNode tree to persist.
        """
        ts = time.time()
        cache_file = self._new_cache_path(disk_path, ts)
        payload = (_CACHE_VERSION, ts, disk_path, node)
        with open(cache_file, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        self._write_meta(cache_file, ts, disk_path)
        self._write_trend(cache_file, ts, disk_path, node)

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
        latest = self.latest_snapshot(disk_path)
        if latest is None:
            return None
        if max_age_seconds is not None:
            age = time.time() - latest.timestamp
            if age > max_age_seconds:
                return None
        return self.load_snapshot(latest.cache_file)

    def load_latest(self, disk_path: str) -> Optional[FileNode]:
        """Load the newest snapshot for *disk_path* (ignoring age)."""
        return self.load(disk_path)

    def load_snapshot(self, cache_file: Path | str) -> Optional[FileNode]:
        """Load a specific snapshot file."""
        path = Path(cache_file)
        payload = self._read_payload(path)
        if payload is None:
            return None
        _version, _timestamp, _disk_path, node = payload
        if not isinstance(node, FileNode):
            self._try_remove(path)
            return None
        return node

    def list_snapshots(self, disk_path: str) -> list[CacheSnapshot]:
        """Return all snapshots of a disk path, newest first."""
        snapshots: list[CacheSnapshot] = []
        key = self._disk_key(disk_path)
        for cache_file in self._cache_dir.glob(f"{key}__*.pkl"):
            meta = self._read_meta(cache_file)
            if meta is not None:
                ts, stored_disk_path = meta
            else:
                payload = self._read_payload(cache_file)
                if payload is None:
                    continue
                _version, ts, stored_disk_path, _node = payload
            path_for_label = stored_disk_path or disk_path
            label = f"{path_for_label}  |  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}"
            snapshots.append(
                CacheSnapshot(
                    cache_file=cache_file,
                    timestamp=ts,
                    disk_path=path_for_label,
                    label=label,
                )
            )

        # Backward compatibility: legacy single-file cache.
        legacy = self._cache_path(disk_path)
        if legacy.exists():
            payload = self._read_payload(legacy)
            if payload is not None:
                _version, ts, stored_disk_path, _node = payload
                path_for_label = stored_disk_path or disk_path
                label = f"{path_for_label}  |  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}"
                snapshots.append(
                    CacheSnapshot(
                        cache_file=legacy,
                        timestamp=ts,
                        disk_path=path_for_label,
                        label=label,
                    )
                )

        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        return snapshots

    def latest_snapshot(self, disk_path: str) -> Optional[CacheSnapshot]:
        """Return the newest snapshot metadata for a disk path."""
        snapshots = self.list_snapshots(disk_path)
        return snapshots[0] if snapshots else None

    def list_all_snapshots(self) -> list[CacheSnapshot]:
        """Return all snapshots across disks, newest first."""
        snapshots: list[CacheSnapshot] = []
        meta_files = sorted(self._cache_dir.glob("*.meta.json"))
        seen_cache_files: set[Path] = set()

        for meta_file in meta_files:
            try:
                obj = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if obj.get("version") != _CACHE_VERSION:
                continue
            cache_file = meta_file.with_name(meta_file.name[:-10])
            seen_cache_files.add(cache_file)
            ts = float(obj.get("timestamp", 0.0))
            disk_path = str(obj.get("disk_path", "")) or cache_file.stem
            label = f"{disk_path}  |  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}"
            snapshots.append(
                CacheSnapshot(
                    cache_file=cache_file,
                    timestamp=ts,
                    disk_path=disk_path,
                    label=label,
                )
            )

        for cache_file in self._cache_dir.glob("*.pkl"):
            if cache_file in seen_cache_files:
                continue
            payload = self._read_payload(cache_file)
            if payload is None:
                continue
            _version, ts, disk_path, _node = payload
            if not disk_path:
                disk_path = cache_file.stem
            label = f"{disk_path}  |  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}"
            snapshots.append(
                CacheSnapshot(
                    cache_file=cache_file,
                    timestamp=ts,
                    disk_path=disk_path,
                    label=label,
                )
            )
        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        return snapshots

    def list_cached_paths(self) -> list[str]:
        """Return all cached disk paths sorted by latest snapshot time."""
        latest_by_path: dict[str, float] = {}
        for snapshot in self.list_all_snapshots():
            prev = latest_by_path.get(snapshot.disk_path)
            if prev is None or snapshot.timestamp > prev:
                latest_by_path[snapshot.disk_path] = snapshot.timestamp
        return [
            item[0]
            for item in sorted(latest_by_path.items(), key=lambda kv: kv[1], reverse=True)
        ]

    def list_history_trends(self, disk_path: str, max_snapshots: int = 60) -> list[HistoryTrendSnapshot]:
        """Return lightweight trend snapshots ordered by timestamp (oldest first)."""
        snaps = self.list_snapshots(disk_path)[:max_snapshots]
        result: list[HistoryTrendSnapshot] = []
        for snap in sorted(snaps, key=lambda s: s.timestamp):
            trend = self._read_trend(snap.cache_file)
            if trend is None:
                # Fallback for old caches without trend sidecar; skip on low-memory.
                node = self.load_snapshot(snap.cache_file)
                if node is None:
                    continue
                level1, level2 = self._build_trend_maps(node)
            else:
                level1, level2 = trend
            result.append(
                HistoryTrendSnapshot(
                    label=snap.label,
                    timestamp=snap.timestamp,
                    disk_path=disk_path,
                    level1=level1,
                    level2=level2,
                )
            )
        return result

    def invalidate(self, disk_path: str) -> None:
        """Remove all cache snapshots for *disk_path*."""
        key = self._disk_key(disk_path)
        for cache_file in self._cache_dir.glob(f"{key}__*.pkl"):
            self._try_remove(cache_file)
            self._try_remove(self._meta_path(cache_file))
            self._try_remove(self._trend_path(cache_file))
        # Also remove legacy file if present.
        legacy = self._cache_path(disk_path)
        self._try_remove(legacy)
        self._try_remove(self._meta_path(legacy))
        self._try_remove(self._trend_path(legacy))

    def clear_all(self) -> None:
        """Delete all cache files."""
        for cache_file in self._cache_dir.glob("*.pkl"):
            self._try_remove(cache_file)
        for sidecar in self._cache_dir.glob("*.meta.json"):
            self._try_remove(sidecar)
        for sidecar in self._cache_dir.glob("*.trend.json"):
            self._try_remove(sidecar)

    def remove_snapshot(self, snapshot: CacheSnapshot | Path | str) -> bool:
        """Delete one snapshot and its sidecar files."""
        cache_file = snapshot.cache_file if isinstance(snapshot, CacheSnapshot) else Path(snapshot)
        existed = cache_file.exists()
        self._try_remove(cache_file)
        self._try_remove(self._meta_path(cache_file))
        self._try_remove(self._trend_path(cache_file))
        return existed

    def cache_age_seconds(self, disk_path: str) -> Optional[float]:
        """Return the age (in seconds) of the cache entry, or None if absent."""
        latest = self.latest_snapshot(disk_path)
        if latest is None:
            return None
        return time.time() - latest.timestamp

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _disk_key(self, disk_path: str) -> str:
        # Replace path separators and colons so the key is a valid filename.
        safe = (
            disk_path.replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
            .strip("_")
        )
        return safe or "root"

    def _new_cache_path(self, disk_path: str, ts: float) -> Path:
        key = self._disk_key(disk_path)
        dt = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts))
        ms = int((ts - int(ts)) * 1000)
        cache_file = self._cache_dir / f"{key}__{dt}_{ms:03d}.pkl"
        idx = 1
        while cache_file.exists():
            cache_file = self._cache_dir / f"{key}__{dt}_{ms:03d}_{idx:02d}.pkl"
            idx += 1
        return cache_file

    @staticmethod
    def _meta_path(cache_file: Path) -> Path:
        return cache_file.with_suffix(".meta.json")

    @staticmethod
    def _trend_path(cache_file: Path) -> Path:
        return cache_file.with_suffix(".trend.json")

    def _write_meta(self, cache_file: Path, ts: float, disk_path: str) -> None:
        meta = {
            "version": _CACHE_VERSION,
            "timestamp": float(ts),
            "disk_path": str(disk_path),
        }
        try:
            self._meta_path(cache_file).write_text(json.dumps(meta, ensure_ascii=True), encoding="utf-8")
        except OSError:
            pass

    def _read_meta(self, cache_file: Path) -> Optional[tuple[float, str]]:
        meta_file = self._meta_path(cache_file)
        if not meta_file.exists():
            return None
        try:
            obj = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        version = obj.get("version")
        if version != _CACHE_VERSION:
            return None
        ts = float(obj.get("timestamp", 0.0))
        disk_path = str(obj.get("disk_path", ""))
        return ts, disk_path

    def _write_trend(self, cache_file: Path, ts: float, disk_path: str, node: FileNode) -> None:
        try:
            level1, level2 = self._build_trend_maps(node)
            payload = {
                "version": _CACHE_VERSION,
                "timestamp": float(ts),
                "disk_path": str(disk_path),
                "level1": level1,
                "level2": level2,
            }
            self._trend_path(cache_file).write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        except (OSError, MemoryError, RecursionError):
            pass

    def _read_trend(self, cache_file: Path) -> Optional[tuple[dict[str, int], dict[str, dict[str, int]]]]:
        trend_file = self._trend_path(cache_file)
        if not trend_file.exists():
            return None
        try:
            obj = json.loads(trend_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError, MemoryError):
            return None
        if obj.get("version") != _CACHE_VERSION:
            return None

        raw_level1 = obj.get("level1") or {}
        raw_level2 = obj.get("level2") or {}
        level1 = {str(k): int(v) for k, v in raw_level1.items()}
        level2: dict[str, dict[str, int]] = {}
        for parent, child_map in raw_level2.items():
            if not isinstance(child_map, dict):
                continue
            level2[str(parent)] = {str(k): int(v) for k, v in child_map.items()}
        return level1, level2

    def _build_trend_maps(self, root: FileNode) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
        level1: dict[str, int] = {}
        level2: dict[str, dict[str, int]] = {}
        for child in root.children:
            if not child.is_dir:
                continue
            level1[child.path] = int(child.size)
            second: dict[str, int] = {}
            for sub in child.children:
                if sub.is_dir:
                    second[sub.path] = int(sub.size)
            level2[child.path] = second
        return level1, level2

    def _cache_path(self, disk_path: str) -> Path:
        """Legacy single-cache path kept for backward compatibility."""
        return self._cache_dir / f"{self._disk_key(disk_path)}.pkl"


    def _read_payload(self, cache_file: Path) -> Optional[tuple[int, float, str, FileNode]]:
        try:
            with open(cache_file, "rb") as fh:
                payload = pickle.load(fh)
        except MemoryError:
            # Low-memory scenario; keep cache file and fail gracefully.
            return None
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError):
            self._try_remove(cache_file)
            return None

        # New format: (version, timestamp, disk_path, node)
        if isinstance(payload, tuple) and len(payload) == 4:
            version, timestamp, disk_path, node = payload
            if version != _CACHE_VERSION:
                self._try_remove(cache_file)
                return None
            return version, float(timestamp), str(disk_path), node

        # Legacy format: (version, timestamp, node)
        if isinstance(payload, tuple) and len(payload) == 3:
            version, timestamp, node = payload
            if version != _CACHE_VERSION:
                self._try_remove(cache_file)
                return None
            return version, float(timestamp), "", node

        self._try_remove(cache_file)
        return None

    @staticmethod
    def _try_remove(path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            pass
