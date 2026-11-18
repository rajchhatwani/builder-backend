"""B1-060: CSV import draws numbered fields, a scoped update re-reads without the scope, references skip
soft-deleted targets, history is readable for soft-deleted records (generated text checks)."""

import json
from pathlib import Path

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _files(name: str) -> dict[str, str]:
    return generate(Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))))


def test_import_draws_numbers_when_writing_not_in_dry_run() -> None:
    files = _files("numbering")
    entity = files["app/crud/orders.py"]
    assert "async def draw_numbers(" in entity
    assert "self.draw_numbers(data)" in entity
    service = files["app/imports/service.py"]
    dry_split = service.split("if not dry_run and pending:")[0]
    assert 'None if dry_run else getattr(repo, "draw_numbers", None)' in dry_split  # a dry run draws nothing
    assert "begin_nested()" in service  # a rejected row rolls its draw back (gapless)


def test_update_rereads_the_written_row_without_the_access_scope() -> None:
    base = _files("authz_abac")["app/crud/_base.py"]
    get = base.split("async def get(")[1].split("async def exists")[0]
    assert "_row_alive" in get
    assert "def _row_alive" in base


def test_references_and_many_to_many_skip_soft_deleted_targets() -> None:
    base = _files("authz_abac")["app/crud/_base.py"]
    assert "def _target_alive" in base
    refs = base.split("async def _check_references")[1].split("async def _pop_related")[0]
    assert "*self._target_alive(target)" in refs
    assert "*self._target_alive(target)" in base.split("async def _pop_related")[1]


def test_history_route_reads_soft_deleted_records() -> None:
    files = _files("history_notes")
    router = files["app/change_history/router.py"]
    assert "include_deleted=True" in router
    assert "include_deleted" in files["app/crud/_base.py"]
