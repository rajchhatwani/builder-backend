"""Audit B1-043: state machines (F-1195 wrong-state 409 hides the state, F-1196 policy-entity transitions list
reflects the update decision, F-1197 happy-path test never needs an always-leaving auto transition)."""

import json
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec
from tests.unit.test_audit_b1_015 import _field_access_spec, _run, _text, _write

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _gen(raw: dict[str, Any]) -> dict[str, Any]:
    return generate(Spec.model_validate(raw))  # type: ignore[return-value]


def test_f1195_invalid_transition_detail_is_generic_when_masked(tmp_path: Path) -> None:
    root = _write(tmp_path, _gen(_field_access_spec()))
    out = _run(
        root,
        """
        import asyncio
        from app.core.errors import AppError
        from app.state_machines import engine
        from app.state_machines.definitions import MACHINES
        ent, m = next(iter(MACHINES.items()))
        t = next(x for x in m["transitions"] if not x["auto"])
        wrong = next(s for s in ["__other__"] if s not in t["from"])
        class Item: pass
        item = Item(); item.id = 1
        setattr(item, m["field"], wrong)
        class R:
            async def execute(self): pass
        class Res:
            def scalar_one_or_none(self): return item
        class Sess:
            async def execute(self, stmt): return Res()
        class Model:
            id = 1
        import sqlalchemy as sa
        class Repo:
            session = Sess(); model = Model
            async def get(self, i, **k): return item
        engine.sa = type("S", (), {"select": lambda *a: type("Q", (), {"where": lambda s, *a: s, "with_for_update": lambda s: s, "execution_options": lambda s, **k: s})()})
        async def go(mask):
            try:
                await engine.apply(Repo(), ent, 1, t["name"], roles=set(t["roles"]), actor_id=None, mask_guard=mask)
            except AppError as e:
                return e.detail if hasattr(e, "detail") else str(e)
        masked = asyncio.run(go(True)); plain = asyncio.run(go(False))
        print(wrong not in masked, wrong in plain)
    """,
    )
    assert out == "True True"


def test_f1196_policy_entity_transitions_list_checks_update_decision() -> None:
    raw = json.loads((FIXTURES / "flow_abac.json").read_text(encoding="utf-8"))
    router = _text(_gen(raw)["app/state_machines/router.py"])
    start = router.index("async def list_")
    body = router[start : router.index("@router.post", start)]
    assert "_can_move_tickets" in body
    assert "no_update=" in body


def test_f1197_happy_path_skips_when_initial_has_unguarded_auto() -> None:
    raw = json.loads((FIXTURES / "flow_abac.json").read_text(encoding="utf-8"))
    from app.core.generator.features.state_machines import module as sm

    machine = {
        "initial": "draft",
        "transitions": [
            {"name": "auto_go", "auto": True, "from": ["draft"], "to": "sent", "roles": [], "guard": None},
            {"name": "send", "auto": False, "from": ["draft"], "to": "sent", "roles": [], "guard": None},
        ],
    }
    class E:
        access = None
    class P:
        spec = Spec.model_validate(raw)
    assert sm._happy_path(E(), machine, P()) is None
    machine["transitions"][0]["guard"] = {"op": "x"}  # a guarded auto move may not fire: the manual move stays
    assert sm._happy_path(E(), machine, P()) is not None
