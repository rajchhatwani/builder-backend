import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["app/services/requirements/reader.py"]


def test_reader_has_no_literal_invisible_chars() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *FILES, "--select", "PLE2502,PLE2515"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout[-800:]


def test_ctrl_pattern_still_strips_invisible_and_bidi() -> None:
    from app.services.requirements.reader import _CTRL

    assert isinstance(_CTRL, re.Pattern)
    for ch in ("\x00", "\x1f", "\x7f", "​", "‏", "‪", "‮", "⁦", "⁩"):
        assert _CTRL.search(f"a{ch}b"), hex(ord(ch))
    assert not _CTRL.search("a b\tc\nd")
