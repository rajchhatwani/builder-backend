"""spec.authorization.field_access is enforced by the generated project (CP-4F1): the rules are plain data
in app/auth/field_access.py, routers hide / refuse by them, and a spec without rules renders exactly as before."""

import json
from pathlib import Path

from app.core.generator import generate
from app.core.spec_models import Spec

TESTS = Path(__file__).resolve().parent.parent
FIXTURES = TESTS / "fixtures" / "specs"
GOLDEN = TESTS / "golden"


def _spec(name: str = "field_access") -> Spec:
    return Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def test_the_rules_are_rendered_as_data_with_the_helpers() -> None:
    files = generate(_spec())
    text = files["app/auth/field_access.py"]
    assert "'salary': (('admin', 'hr',), ('hr',))" in text
    assert "'notes': (('hr',), None)" in text
    assert "def hidden_read(" in text and "def hidden_write(" in text
    assert "effective_roles" in text


def test_routers_hide_refuse_and_the_repository_blocks_queries() -> None:
    files = generate(_spec())
    router = files["app/routers/employees.py"]
    assert router.count("response_model_exclude_unset=True") == 5
    assert "hidden_fields=_fx.hidden_read(" in router
    assert '_fx.payload("Employee", access.user, body, "create")' in router
    assert '_fx.payload("Employee", access.user, body, "replace")' in router
    assert '_fx.payload("Employee", access.user, body, "update")' in router
    assert "_fx.shape(" in router
    assert "HiddenFieldsMixin" in files["app/crud/employees.py"]
    read = files["app/schemas/employees.py"].split("class EmployeeRead")[1]
    assert "salary: int | None = None" in read and "notes: str | None = None" in read
    assert "name: str\n" in read  # an unruled field is unchanged


def test_without_rules_nothing_changes() -> None:
    spec = _spec()
    assert spec.authorization is not None
    spec.authorization.field_access = []
    files = generate(spec)
    assert "app/auth/field_access.py" not in files
    assert not any("field_access" in text or "hidden_fields" in text for text in files.values())


def test_a_spec_without_field_access_matches_its_existing_golden() -> None:
    files = generate(_spec("desk_auth"))
    golden = GOLDEN / "desk_auth"
    expected = {
        p.relative_to(golden).as_posix(): p.read_text(encoding="utf-8")
        for p in golden.rglob("*")
        if p.is_file()
    }
    assert files == expected
