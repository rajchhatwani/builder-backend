"""G8 refuses files under cache folders (`g8.cache_dir_file`); a test run leaves them. Kept outside the
tools package, whose modules may not import shutil."""

import os
import shutil
from pathlib import Path

CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"})


def clean_caches(root: Path) -> int:
    """Remove cache folders from the worktree (G8 flags them as `g8.cache_dir_file`). Links are never
    followed; returns the number of folders removed."""
    removed = 0
    for dirpath, dirnames, _files in os.walk(root, followlinks=False):
        keep = []
        for d in dirnames:
            full = Path(dirpath, d)
            if d == ".git":
                continue
            if d in CACHE_DIRS and not full.is_symlink():
                shutil.rmtree(full, ignore_errors=True)
                removed += 1
            else:
                keep.append(d)
        dirnames[:] = keep
    return removed
