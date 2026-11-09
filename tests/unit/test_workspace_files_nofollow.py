"""S2-013: file open is relative to pinned directory fds with O_NOFOLLOW (no check-then-open gap)."""

import hashlib
import os
from pathlib import Path

import pytest

from app.exceptions import AppError
from app.services import workspace_files as wf


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


@pytest.fixture
def wt(tmp_path: Path) -> Path:
    (tmp_path / "app" / "custom").mkdir(parents=True)
    (tmp_path / "app" / "custom" / "a.py").write_text("v1\n")
    (tmp_path / "outside.txt").write_text("secret\n")
    return tmp_path


def test_read_and_write_roundtrip_keeps_mode(wt: Path) -> None:
    f = wt / "app/custom/a.py"
    f.chmod(0o640)
    assert wf._read_sync(wt, "app/custom/a.py") == ("v1\n", _sha("v1\n"))
    new = wf._write_sync(wt, "app/custom/a.py", "v2\n", _sha("v1\n"))
    assert new == _sha("v2\n") and f.read_text() == "v2\n"
    assert f.stat().st_mode & 0o777 == 0o640
    assert [p.name for p in f.parent.iterdir()] == ["a.py"]  # no temp file left behind


def test_symlinked_file_is_refused(wt: Path) -> None:
    (wt / "app/custom/link.py").symlink_to(wt / "outside.txt")
    for fn in (lambda: wf._read_sync(wt, "app/custom/link.py"),
               lambda: wf._write_sync(wt, "app/custom/link.py", "x", _sha("secret\n"))):  # fmt: skip
        with pytest.raises(AppError) as exc:
            fn()
        assert exc.value.code == "bad_path"
    assert (wt / "outside.txt").read_text() == "secret\n"


def test_symlinked_directory_swap_is_refused(wt: Path) -> None:
    real = wt / "app" / "custom"
    moved = wt / "app" / "custom_real"
    real.rename(moved)
    (wt / "app" / "custom").symlink_to(wt)  # directory swapped for a link out of the tree
    with pytest.raises(AppError) as exc:
        wf._read_sync(wt, "app/custom/outside.txt")
    assert exc.value.code == "bad_path"
    with pytest.raises(AppError):
        wf._write_sync(wt, "app/custom/outside.txt", "pwned", _sha("secret\n"))
    assert (wt / "outside.txt").read_text() == "secret\n"


def test_swap_after_open_cannot_redirect_the_write(wt: Path) -> None:
    """The parent directory is pinned by fd: swapping the path afterwards does not move the write."""
    dirfd, name = wf._open_parent(wt, "app/custom/a.py")
    try:
        (wt / "app" / "custom").rename(wt / "app" / "custom_real")
        (wt / "app" / "custom").symlink_to(wt)
        fd = wf._open_file(dirfd, name)  # still the original directory
        assert wf._read_fd(fd)[0] == "v1\n"
    finally:
        os.close(dirfd)


def test_missing_and_bad_paths(wt: Path) -> None:
    with pytest.raises(AppError) as exc:
        wf._read_sync(wt, "app/custom/none.py")
    assert exc.value.code == "file_not_found"
    with pytest.raises(AppError) as exc:
        wf._read_sync(wt, "app/nodir/x.py")
    assert exc.value.code == "file_not_found"
    for bad in ("../x", "a/../b", "/abs", ".git/config", "a//b", ""):
        with pytest.raises(AppError) as exc:
            wf._read_sync(wt, bad)
        assert exc.value.code == "bad_path"


def test_stale_hash_is_refused(wt: Path) -> None:
    with pytest.raises(AppError) as exc:
        wf._write_sync(wt, "app/custom/a.py", "x", "0" * 64)
    assert exc.value.code == "file_changed"
    assert wf._BUSY_STATES == ("planning", "running", "awaiting_approval", "gating", "applying")
