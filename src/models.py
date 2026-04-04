"""Data models for DiskExplorer."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional


def format_size(size_bytes: int) -> str:
    """Return a human-readable string for the given byte count."""
    if size_bytes <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


@dataclass
class FileNode:
    """Represents a file or directory in the file system tree."""

    name: str
    path: str
    size: int
    is_dir: bool
    mod_time: float
    create_time: float
    file_count: int = 0
    children: List["FileNode"] = field(default_factory=list)
    error: Optional[str] = None
    _sorted_children_cache: Dict[tuple[str, bool], List["FileNode"]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @property
    def formatted_size(self) -> str:
        """Return the size formatted as a human-readable string."""
        return format_size(self.size)

    @property
    def extension(self) -> str:
        """Return the file extension (empty string for directories)."""
        if self.is_dir:
            return ""
        _, ext = os.path.splitext(self.name)
        return ext.lower()

    def add_child(self, child: "FileNode") -> None:
        """Add a child node and update size and file counts."""
        self.children.append(child)
        # Child order changed; invalidate cached sort projections.
        self._sorted_children_cache.clear()

    def get_children_sorted(self, key: str = "size", reverse: bool = True) -> List["FileNode"]:
        """Return children sorted by the given key."""
        valid_keys = {"size", "name", "mod_time", "create_time", "file_count"}
        if key not in valid_keys:
            key = "size"
        cache_key = (key, reverse)
        cached = self._sorted_children_cache.get(cache_key)
        if cached is not None:
            return cached
        sorted_children = sorted(self.children, key=lambda n: getattr(n, key), reverse=reverse)
        self._sorted_children_cache[cache_key] = sorted_children
        return sorted_children

    def iter_all(self) -> Iterator["FileNode"]:
        """Depth-first iteration over this node and all descendants."""
        yield self
        for child in self.children:
            yield from child.iter_all()

    def find(self, path: str) -> Optional["FileNode"]:
        """Find a node by its absolute path."""
        for node in self.iter_all():
            if node.path == path:
                return node
        return None

    def type_distribution(self) -> Dict[str, int]:
        """Return a mapping of extension -> total size for all descendants."""
        dist: Dict[str, int] = {}
        for node in self.iter_all():
            if not node.is_dir:
                ext = node.extension or "(no ext)"
                dist[ext] = dist.get(ext, 0) + node.size
        return dist

    def __repr__(self) -> str:
        kind = "Dir" if self.is_dir else "File"
        return f"<FileNode {kind} '{self.name}' {self.formatted_size}>"


class DiskDataModel:
    """Manages all scanned disk data in memory."""

    def __init__(self) -> None:
        self._roots: Dict[str, FileNode] = {}

    def set_root(self, disk_path: str, node: FileNode) -> None:
        """Store a scanned root node for a disk/path."""
        self._roots[disk_path] = node

    def get_root(self, disk_path: str) -> Optional[FileNode]:
        """Retrieve the root node for a disk/path."""
        return self._roots.get(disk_path)

    def remove(self, disk_path: str) -> None:
        """Remove a stored scan result."""
        self._roots.pop(disk_path, None)

    def all_disks(self) -> List[str]:
        """Return all disk paths that have been scanned."""
        return list(self._roots.keys())

    def clear(self) -> None:
        """Clear all stored data."""
        self._roots.clear()

    def __len__(self) -> int:
        return len(self._roots)
