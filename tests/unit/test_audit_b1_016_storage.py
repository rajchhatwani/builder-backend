"""Audit B1-016: regressions in the generated storage module (sniff, locking, backend errors)."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    spec = Spec.model_validate_json((FIXTURES / "storage_s3.json").read_text(encoding="utf-8"))
    return generate(spec)


def run_sniff(files: dict[str, str], tmp_path: Path, code: str) -> str:
    pkg = tmp_path / "app" / "storage"
    pkg.mkdir(parents=True)
    (pkg / "sniff.py").write_text(files["app/storage/sniff.py"], encoding="utf-8")
    script = tmp_path / "run.py"
    script.write_text(
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('sniff', sys.argv[1])\n"
        "sniff = importlib.util.module_from_spec(spec); sys.modules['sniff'] = sniff\n"
        "spec.loader.exec_module(sniff)\n" + textwrap.dedent(code),
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, "-I", str(script), str(pkg / "sniff.py")],
        capture_output=True, text=True, timeout=20, check=True,
    )
    return out.stdout.strip()


def test_html_detection_is_linear_on_many_comments(files: dict[str, str], tmp_path: Path) -> None:
    """F-0435: nested lazy comment matching was exponential (24 comments took ~2s)."""
    out = run_sniff(files, tmp_path, """
        import time
        t = time.perf_counter()
        sniff.detect(b'<!---->' * 40 + b'x')
        print(round(time.perf_counter() - t, 3))
        print(sniff.detect(b'<!-- a --> <!-- b -->\\n<html>').mime)
    """)
    elapsed, mime = out.splitlines()
    assert float(elapsed) < 1.0
    assert mime == "text/html"


@pytest.mark.parametrize(
    ("head", "mime"),
    [
        (b"ID3,name\n1,a\n", "text/plain"),
        (b"MZ is a text file\n", "text/plain"),
        (b"BZh, hello there\n", "text/plain"),
        (b"#!/bin/sh\necho hi\n", "text/x-shellscript"),
        (b"MZ\x90\x00" + b"\x00" * 60, "application/vnd.microsoft.portable-executable"),
        (b"ID3\x03\x00\x00" + b"\x00" * 30, "audio/mpeg"),
        (b"just text mentioning <svg width> later", "text/plain"),
        (b'<?xml version="1.0"?>\n<svg xmlns="x">', "image/svg+xml"),
        (b"<svg xmlns='x'></svg>", "image/svg+xml"),
    ],
)
def test_ambiguous_magics_need_structure(
    files: dict[str, str], tmp_path: Path, head: bytes, mime: str
) -> None:
    """F-0444: text starting with ID3/MZ/BZh was typed binary; '<svg' anywhere made it SVG."""
    out = run_sniff(files, tmp_path, f"print(sniff.detect({head!r}).mime)")
    assert out == mime


def write_stub_tree(files: dict[str, str], tmp_path: Path, modules: tuple[str, ...]) -> None:
    pkg = tmp_path / "app" / "storage"
    pkg.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "config.py").write_text("class StorageSettings: ...\n")
    for name in modules:
        (pkg / f"{name}.py").write_text(files[f"app/storage/{name}.py"], encoding="utf-8")


def test_a_mid_body_read_error_becomes_backend_unavailable(
    files: dict[str, str], tmp_path: Path
) -> None:
    """F-0441: only get_object was wrapped; a reset while reading the body escaped raw."""
    write_stub_tree(files, tmp_path, ("backend",))
    script = tmp_path / "run.py"
    script.write_text(
        textwrap.dedent("""
        import asyncio, sys
        sys.path.insert(0, sys.argv[1])
        from app.storage import backend

        class Body:
            def iter_chunks(self, n):
                yield b"first"
                raise OSError("connection reset")
            def close(self): pass

        class Client:
            def get_object(self, **kw): return {"Body": Body()}

        async def main():
            b = object.__new__(backend.S3Backend)
            b._client, b._bucket = Client(), "bkt"
            got = []
            try:
                async for chunk in b.stream("k"):
                    got.append(chunk)
            except backend.BackendUnavailable:
                print("unavailable", got)
            except Exception as exc:
                print("raw", type(exc).__name__)

        asyncio.run(main())
        """),
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, "-I", str(script), str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert "unavailable [b'first']" in out.stdout, out.stderr[-400:]


def test_the_service_locks_and_restores_rows_correctly(files: dict[str, str]) -> None:
    """F-0438/F-0439/F-0440 need a database to run; this pins the code shape that fixes them."""
    svc = files["app/storage/service.py"]
    erase = svc[svc.index("async def _erase") : svc.index("# --- review")]
    assert "populate_existing=True" in erase  # F-0438: the lock must refresh the loaded row
    assert 'previous == "deleting"' in erase  # F-0440: never restore into 'deleting'
    assert "_restore_status" in erase  # F-0440: restore also when is_referenced raises
    relock = svc[svc.index("async def _relock") : svc.index("async def release")]
    assert "populate_existing=True" in relock and "with_for_update()" in relock
    assert svc.count("await _relock(session, row)") >= 3  # F-0439: release, rescan, quarantine


def test_denied_uploads_are_refused_before_the_body_is_read(files: dict[str, str]) -> None:
    """F-0443 / F-0436: role and rate checks and the connection release precede request.form()."""
    router = files["app/storage/router.py"]
    assert router.index("service.precheck_upload") < router.index("request.form(")
    svc = files["app/storage/service.py"]
    pre = svc[svc.index("async def precheck_upload") : svc.index("async def _check_rate")]
    assert "await session.commit()" in pre
    upload = svc[svc.index("async def upload(") : svc.index("# --- list, read")]
    assert upload.index("await session.commit()") < upload.index("clamav.scan(")
    assert "_DEDUPED_EVENTS" in svc  # denied / rate-limited rows are written once a minute


def test_the_size_limit_sits_inside_cors(files: dict[str, str]) -> None:
    """F-0442: the last added middleware is outermost, so the limit must be added before CORS."""
    main = files["app/main.py"]
    assert main.index("UploadSizeLimitMiddleware,") < main.index("CORSMiddleware,")
