"""Shared test fixtures for Touchgrind Skate 2 save editor test suites.

Provides a self-contained synthetic save directory so tests do not rely
on committed physical device backups.
"""

from __future__ import annotations

import atexit
from pathlib import Path
import shutil
import tempfile

from editor.demo_save import create_synthetic_save

_SYNTHETIC_DIR: Path | None = None


def get_synthetic_ref_dir() -> Path:
    """Return a path to a cached synthetic reference save directory."""
    global _SYNTHETIC_DIR
    if _SYNTHETIC_DIR is None or not _SYNTHETIC_DIR.exists():
        temp_root = Path(tempfile.mkdtemp(prefix="tgskate2_test_ref_"))
        create_synthetic_save(temp_root)
        _SYNTHETIC_DIR = temp_root
        atexit.register(cleanup_synthetic_ref_dir)
    return _SYNTHETIC_DIR


def cleanup_synthetic_ref_dir() -> None:
    """Clean up the synthetic reference save directory."""
    global _SYNTHETIC_DIR
    if _SYNTHETIC_DIR is not None and _SYNTHETIC_DIR.exists():
        shutil.rmtree(_SYNTHETIC_DIR, ignore_errors=True)
        _SYNTHETIC_DIR = None
