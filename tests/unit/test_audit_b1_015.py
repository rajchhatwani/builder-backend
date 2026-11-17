"""Audit B1-015: generated state machines (F-0479 hidden state field, F-0480 transitions list honours update
access, F-0481 apply() on a vanished row, F-0482 generated test imports, F-0483 generated happy-path tests)."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _gen(raw: dict[str, Any]) -> dict[str, Any]:
    return generate(Spec.model_validate(raw))  # type: ignore[return-value]


def _text(value: Any) -> str:
    return value if isinstance(value, str) else value.decode()


def _field_access_spec() -> dict[str, Any]:
    raw = _load("field_access")
    raw["authorization"]["field_access"].append(
        {"entity": "Employee", "field": "status", "read_roles": ["hr"]}
    )
    return raw


def _write(tmp_path: Path, files: dict[str, Any]) -> Path:
    for path, content in files.items():
        if path.startswith("app/"):
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_text(content), encoding="utf-8")
    return tmp_path


def _run(root: Path, code: str) -> str:
    script = "import sys\nsys.path.insert(0, %r)\n" % str(root) + textwrap.dedent(code)
    done = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=root,
        env={"PATH": "/usr/bin", "APP_ENV": "test"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-1500:]
    return done.stdout.strip()


def test_f0479_hidden_state_field_closes_history_and_transitions() -> None:
    router = _text(_gen(_field_access_spec())["app/state_machines/router.py"])
    assert router.count('"status" in _fx.hidden_read("Employee", access.user)') == 2


def test_f0480_transitions_list_reports_update_refusal() -> None:
    raw = _load("demo_invoice")
    files = _gen(raw)
    router = _text(files["app/state_machines/router.py"])
    start = router.index("async def list_")
    assert "no_update=" in router[start : router.index("@router.post", start)]
    out_root = None  # engine behaviour is checked below
    assert out_root is None
    engine = _text(files["app/state_machines/engine.py"])
    assert "no_update" in engine


def test_f0480_engine_available_marks_roleless_moves(tmp_path: Path) -> None:
    root = _write(tmp_path, _gen(_load("field_access")))
    out = _run(
        root,
        """
        from app.state_machines import engine
        from app.state_machines.definitions import MACHINES
        ent, m = next(iter(MACHINES.items()))
        class Item: pass
        item = Item()
        setattr(item, m["field"], m["initial"])
        import sqlalchemy as sa
        engine.row_values = lambda i: {}
        engine.guard_holds = lambda *a, **k: True
        roleless = [t["name"] for t in m["transitions"] if not t["auto"] and m["initial"] in t["from"] and not t["roles"]]
        rows = engine.available(ent, item, set(), no_update=True)
        print(sorted(r["name"] for r in rows if r["refused_because"] == "role" and r["name"] in roleless) == sorted(roleless), bool(roleless))
        rows = engine.available(ent, item, set(), no_update=False)
        print(all(r["refused_because"] != "role" or r["name"] not in roleless for r in rows))
    """,
    )
    assert out.splitlines() == ["True True", "True"]


def test_f0481_apply_on_a_vanished_row_is_404_and_lock_checks_alive(tmp_path: Path) -> None:
    raw = _load("demo_invoice")
    for e in raw["entities"]:
        if e["name"] == "Invoice":
            e["options"]["soft_delete"] = True
    root = _write(tmp_path, _gen(raw))
    out = _run(
        root,
        """
        import asyncio, uuid
        from app.core.errors import NotFoundError
        from app.state_machines import engine
        from app.state_machines.definitions import MACHINES
        from app.models.invoices import Invoice

        seen = []
        class Result:
            def scalar_one_or_none(self): return None
            def scalar_one(self): raise RuntimeError("NoResultFound")
        class Session:
            async def execute(self, stmt):
                seen.append(str(stmt)); return Result()
        class Repo:
            model = Invoice
            session = Session()
            async def get(self, item_id, **kw): return object()
        m = MACHINES["Invoice"]
        name = next(t["name"] for t in m["transitions"] if not t["auto"] and not t["roles"] or not t["auto"])
        roles = {r for t in m["transitions"] for r in t["roles"]}
        async def main():
            try:
                await engine.apply(Repo(), "Invoice", uuid.uuid4(), name, roles=roles, actor_id=None)
            except NotFoundError:
                print("404")
        asyncio.run(main())
        print("deleted_at IS NULL" in seen[0])
    """,
    )
    assert out.splitlines() == ["404", "True"]


def test_f0482_no_unused_pytest_import_without_access_rules() -> None:
    raw = _load("demo_invoice")
    raw["auth"] = None
    for key in ("authorization", "settings", "sequences", "lists", "history", "hooks", "seed"):
        raw.pop(key, None)
    for sm in raw["state_machines"]:
        sm["transitions"] = [
            {k: v for k, v in t.items() if k != "roles"}
            for t in sm["transitions"]
            if not t.get("auto") and not t.get("when")
        ]
    files = _gen(raw)
    text = _text(files["tests/test_state_machines.py"])
    assert "import pytest" not in text


def test_f0482_pytest_still_imported_when_used() -> None:
    text = _text(_gen(_load("demo_invoice"))["tests/test_state_machines.py"])
    assert "import pytest" in text and "pytest.fixture" in text


def test_f0483_generated_tests_exercise_a_move_409_and_history() -> None:
    text = _text(_gen(_load("events_orders"))["tests/test_state_machines.py"])
    assert "_moves_and_logs" in text
    assert "invalid_transition" in text
