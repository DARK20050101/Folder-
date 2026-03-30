"""Application-level logging configuration for DiskExplorer.

Logs are written to ``<project_root>/logs/app.log`` so that they stay
inside the project directory and never leak to ``%APPDATA%`` or any
other user-profile location.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

# Resolved once at import time so that all callers share the same root.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")

_configured = False


def setup_logging(level: int = logging.DEBUG) -> None:
    """Configure the root logger to write to ``./logs/app.log``.

    Safe to call multiple times – only the first call has any effect.
    """
    global _configured
    if _configured:
        return
    _configured = True

    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Rotating file handler: 5 MB per file, keep 3 backups.
    fh = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Also keep a minimal console handler so that developers running from a
    # terminal see warnings and above without needing to tail the log file.
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    root.addHandler(ch)
