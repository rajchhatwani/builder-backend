"""Audit B1-002 (F-0918/F-0919/F-0920): every generated constraint/index name fits Postgres' 63 chars."""

import re

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from tests.unit.test_generator import FIXTURES

_NAME = re.compile(r"""['"]((?:uq|ix|fk|pk)_[a-z0-9_]+)['"]""")


def _spec(name: str) -> Spec:
    return Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _names(files: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for path, text in files.items():
        if path.startswith("alembic/") or path.startswith("app/models/"):
            out.update(_NAME.findall(text))
    return out


@pytest.mark.parametrize("length", [39, 50, 62])
def test_policy_tenant_tables_names_fit(length: int) -> None:
    """F-0918: abac/pbac + multi_tenant entity (not covered by the owner-rule length check)."""
    spec = _spec("authz_tenant")
    spec.relations = []
    ent = next(e for e in spec.entities if e.name == "Task")
    ent.table_name = ("t" * length)[:length]
    ent.plural_path = ent.table_name
    assert validate(spec) == []
    names = _names(generate(spec))
    assert any(n.startswith(f"fk_{ent.table_name}"[:50]) or ent.table_name[:40] in n for n in names)
    assert [n for n in names if len(n) > 63] == []


@pytest.mark.parametrize("length", [50, 62])
def test_pk_and_custom_fields_index_names_fit(length: int) -> None:
    """F-0919: pk_<table> and ix_<table>_custom_fields in migration and model."""
    spec = _spec("custom_fields")
    ent = next(e for e in spec.entities if e.custom_fields is not None)
    ent.table_name = ("c" * length)[:length]
    ent.plural_path = ent.table_name
    assert validate(spec) == []
    files = generate(spec)
    assert [n for n in _names(files) if len(n) > 63] == []
    mig = "".join(t for p, t in files.items() if p.startswith("alembic/versions/0001"))
    model = files[f"app/models/{ent.table_name}.py"]
    assert re.search(r"ix_c{40,}_(?:c_)?[0-9a-f]{4}\b|ix_c{40,}_custom_fields", mig)
    assert re.search(r"ix_c{40,}_(?:c_)?[0-9a-f]{4}\b|ix_c{40,}_custom_fields", model)
    assert re.search(r"pk_c{40,}", mig)
