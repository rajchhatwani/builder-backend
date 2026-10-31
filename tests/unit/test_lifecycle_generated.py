"""B1-4: the generated repository runs create/update/delete in the documented lifecycle order,
with a fake session (no database): the generated project is imported in a subprocess."""

import subprocess
import sys
from pathlib import Path

from app.core.generator import generate
from tests.unit.test_generator import load_spec, write_tree

SCRIPT = r'''
import asyncio, uuid
from types import SimpleNamespace
from app.crud.notes import NoteRepository
from app.crud import lifecycle
from app.core.errors import AppError

class Result:
    def __init__(self, item): self.item = item
    def scalars(self): return self
    def first(self): return self.item

class Session:
    def __init__(self, log, item=None, fail_flush=False): self.log, self.item = log, item
    def add(self, obj):
        obj.id = uuid.uuid4(); self.item = obj; self.log.append("session.add")
    async def flush(self): self.log.append("session.flush")
    async def commit(self): self.log.append("session.commit")
    async def rollback(self): self.log.append("session.rollback")
    async def delete(self, obj): self.log.append("session.delete")
    async def execute(self, stmt): return Result(self.item)

def make(log, hooks):
    class Repo(NoteRepository):
        pass
    Repo.hooks = hooks
    return Repo(Session(log, item=SimpleNamespace(id=uuid.uuid4(), title="x")))

def hook(log, name, boom=False):
    async def h(ctx):
        log.append(name)
        if boom: raise ValueError("boom")
    return h

async def main():
    # 1. order on create
    log = []
    hooks = {s: (hook(log, s),) for s in lifecycle.STAGES}
    repo = make(log, hooks)
    ctx_trace = []
    orig = lifecycle.run_stage
    await repo.create({"title": "a"})
    assert log == ["before_save", "session.add", "session.flush", "after_save", "session.commit", "after_commit"], log
    # 2. trace covers the whole chain in the documented order
    from app.crud.lifecycle import HookContext
    seen = []
    orig_ctx = repo._ctx
    def spy(op, values):
        c = orig_ctx(op, values); seen.append(c); return c
    repo._ctx = spy
    await repo.create({"title": "b"})
    assert tuple(seen[0].trace) == lifecycle.ORDER, seen[0].trace
    assert lifecycle.ORDER == ("before_save", "guards", "validate", "write", "after_save", "commit", "after_commit")
    # 3. after_save failure rolls back and nothing commits
    log = []
    repo = make(log, {"after_save": (hook(log, "after_save", boom=True),)})
    try:
        await repo.create({"title": "a"}); raise SystemExit("expected failure")
    except AppError as exc:
        assert exc.code == "hook_failed", exc.code
    assert "session.rollback" in log and "session.commit" not in log, log
    # 4. after_commit failure never fails the request
    log = []
    repo = make(log, {"after_commit": (hook(log, "after_commit", boom=True),)})
    await repo.create({"title": "a"})
    assert log[-2:] == ["session.commit", "after_commit"], log
    # 5. before_save can change values; update and delete also run the chain
    log = []
    async def tweak(ctx): ctx.values["title"] = "changed"
    repo = make(log, {"before_save": (tweak, hook(log, "before_save")), "after_commit": (hook(log, "after_commit"),)})
    item = await repo.update(uuid.uuid4(), {"title": "orig"})
    assert item.title == "changed"
    await repo.delete(uuid.uuid4())
    assert log.count("after_commit") == 2 and log.count("before_save") == 2, log
    # 6. a hook that hangs is cut off
    async def slow(ctx): await asyncio.sleep(5)
    lifecycle.HOOK_TIMEOUT_SECONDS = 0.05
    repo = make([], {"before_save": (slow,)})
    try:
        await repo.create({"title": "a"}); raise SystemExit("expected timeout")
    except AppError as exc:
        assert exc.code == "hook_failed"
    print("LIFECYCLE OK")

asyncio.run(main())
'''


def test_generated_repository_runs_the_lifecycle_in_order(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    write_tree(root, generate(load_spec("minimal")))
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "", "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/x_test"},
    )
    assert "LIFECYCLE OK" in result.stdout, result.stdout + result.stderr
