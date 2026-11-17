"""Audit B1-013: generated providers (breaker, retries) and opensearch search, run for real in a subprocess
against the generated `app/` tree (F-0454, F-0455, F-0457)."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _tree(tmp_path: Path, name: str) -> Path:
    spec = Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    for path, content in generate(spec).items():
        if path.startswith("app/"):
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content if isinstance(content, str) else content.decode(), encoding="utf-8")
    return tmp_path


def _run(root: Path, code: str, env: dict[str, str]) -> str:
    script = "import sys\nsys.path.insert(0, %r)\n" % str(root) + textwrap.dedent(code)
    done = subprocess.run(
        [sys.executable, "-I", "-c", script], cwd=root, env={"PATH": "/usr/bin", **env},
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert done.returncode == 0, done.stderr[-1500:]
    return done.stdout.strip()


def test_a_cancelled_probe_does_not_wedge_the_breaker(tmp_path: Path) -> None:
    root = _tree(tmp_path, "providers_notify")
    out = _run(root, """
        from app.providers.breaker import CircuitBreaker
        now = [0.0]
        b = CircuitBreaker(2, 10, lambda: now[0])
        b.failure(); b.failure()
        now[0] = 11
        first = b.allow()          # the probe goes out and is then cancelled: nobody reports back
        now[0] = 1000
        print(first, b.allow())
        b2 = CircuitBreaker(2, 10, lambda: now[0])
        b2.failure(); b2.failure(); now[0] += 11
        assert b2.allow()
        b2.abandon()
        print(b2.allow())
    """, {"APP_ENV": "test"})
    assert out.splitlines() == ["True True", "True"]


def test_a_cancelled_call_releases_the_probe_slot(tmp_path: Path) -> None:
    root = _tree(tmp_path, "providers_notify")
    out = _run(root, """
        import asyncio, uuid
        from app.providers import client
        from app.providers.breaker import breaker_for, reset_all
        from app.providers import definitions
        from app.providers.schemas import REQUESTS

        class Hang:
            name = "emulator"; kind = "email"
            async def call(self, request, credentials):
                await asyncio.sleep(60)

        async def fake_resolve(session, tenant_id, kind, prefer=None):
            return Hang(), None
        client.resolve = fake_resolve
        tenant = uuid.uuid4()
        b = breaker_for(str(tenant), "email", "emulator", definitions.BREAKER_FAILURES, definitions.BREAKER_RESET_SECONDS)
        b._state = "open"; b._opened_at = -10**6
        req = REQUESTS["email"].model_construct()

        async def main():
            task = asyncio.create_task(client.call_provider(None, tenant, "email", req))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            print(b.allow())
        asyncio.run(main())
    """, {"APP_ENV": "test"})
    assert out == "True"


def test_a_payments_call_with_an_unknown_outcome_is_not_repeated(tmp_path: Path) -> None:
    root = _tree(tmp_path, "providers_notify")
    out = _run(root, """
        import asyncio, uuid
        from app.providers import client, definitions
        from app.providers.errors import ProviderTimeout
        from app.providers.schemas import REQUESTS
        definitions.MAX_ATTEMPTS = 3
        calls = {"payments": 0, "email": 0}

        class Flaky:
            name = "emulator"
            def __init__(self, kind): self.kind = kind
            async def call(self, request, credentials):
                calls[self.kind] += 1
                raise ProviderTimeout("lost")

        async def fake_resolve(session, tenant_id, kind, prefer=None):
            return Flaky(kind), None
        client.resolve = fake_resolve
        async def nosleep(_): pass
        client.sleep = nosleep

        async def main():
            for kind in ("payments", "email"):
                try:
                    await client.call_provider(None, uuid.uuid4(), kind, REQUESTS[kind].model_construct())
                except ProviderTimeout:
                    pass
            print(calls["payments"], calls["email"])
        asyncio.run(main())
    """, {"APP_ENV": "test"})
    assert out.splitlines()[-1] == "1 3"


def test_the_adapter_contract_states_that_calls_may_repeat() -> None:
    files = generate(Spec.model_validate(json.loads((FIXTURES / "providers_notify.json").read_text(encoding="utf-8"))))
    assert "may be repeated" in files["app/providers/base.py"]


@pytest.mark.parametrize("docs", [201])
def test_a_scoped_caller_still_gets_a_page_when_the_global_top_hits_are_not_theirs(
    tmp_path: Path, docs: int
) -> None:
    root = _tree(tmp_path, "search")
    out = _run(root, f"""
        import asyncio, uuid
        import sqlalchemy as sa
        from app.search import adapters, service

        table = sa.table("tickets", sa.column("id"))
        table.__name__ = "table"
        mine = uuid.uuid4()
        others = [uuid.uuid4() for _ in range({docs})]

        class Repo:
            searchable = ("title",)
            model = table
            class session:
                @staticmethod
                async def execute(stmt):
                    ids = [v for p in stmt.compile().params.values() if isinstance(p, list) for v in p]
                    class R:
                        def scalars(self):
                            class S:
                                def all(s):
                                    return [type("Row", (), {{"id": i}}) for i in ids if i == mine]
                            return S()
                    return R()
            def _alive(self): return []
            def _col(self, name): return sa.column(name)
            def _loaders(self): return []

        async def main():
            fake = adapters.fake_engine()
            for i in others:   # tenant A: many strong matches
                await fake.index("table", str(i), {{"title": "invoice invoice invoice"}})
            await fake.index("table", str(mine), {{"title": "invoice"}})  # tenant B: ranked last
            rows, total = await service.find(Repo(), "invoice", 20)
            print(len(rows), total)
        asyncio.run(main())
    """, {"APP_ENV": "test", "SEARCH_BACKEND": "opensearch-fake"})
    assert out == "1 1"
