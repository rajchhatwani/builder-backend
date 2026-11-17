"""Audit B1-017: generated download stream detects an object longer than recorded (F-0445)."""

import asyncio
import hashlib
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _load_verified() -> tuple[Any, list[tuple[Any, ...]], type[Exception]]:
    spec = Spec.model_validate_json((FIXTURES / "storage_s3.json").read_text(encoding="utf-8"))
    src = generate(spec)["app/storage/service.py"]
    m = re.search(r"^async def _verified\(.*?(?=^_background)", src, re.S | re.M)
    assert m
    recorded: list[tuple[Any, ...]] = []

    class AppErr(Exception):
        pass

    async def rec(*a: Any) -> None:
        recorded.append(a)

    def detach(coro: Any) -> None:
        asyncio.get_running_loop().create_task(coro)

    ns: dict[str, Any] = {
        "hashlib": hashlib, "AsyncIterator": Any, "StorFile": Any,
        "logger": SimpleNamespace(error=lambda *a, **k: None),
        "_detach": detach, "_record_mismatch": rec, "AppError": lambda *a: AppErr(*a),
    }
    exec("from __future__ import annotations\n" + m.group(0), ns)  # noqa: S102
    return ns["_verified"], recorded, AppErr


async def _gen(chunks: list[bytes]) -> Any:
    for c in chunks:
        yield c


def test_longer_object_is_recorded_before_the_stream_is_cut() -> None:
    verified, recorded, err = _load_verified()
    good = b"abcd"
    row = SimpleNamespace(id=uuid.uuid4(), sha256=hashlib.sha256(good).hexdigest(), size_bytes=4)

    async def run() -> list[bytes]:
        out: list[bytes] = []
        with pytest.raises(err):
            async for c in verified(b"ab", _gen([b"cd", b"EXTRA"]), row):
                out.append(c)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return out

    out = asyncio.run(run())
    assert b"".join(out) == b"abcd"
    assert len(recorded) == 1 and recorded[0][3] == 9
