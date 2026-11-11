"""HEAD and DELETE of an entity that has permissions carry the entity's access dependency (SENTINEL CP-4F1 LOW-6)."""

from app.core.generator import generate
from app.core.spec_models import Spec
from tests.unit.test_generator import FIXTURES


def _files(name: str) -> dict[str, str]:
    return generate(Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def test_head_follows_get_and_delete_follows_update() -> None:
    src = _files("field_access")["app/routers/employees.py"]
    assert '"head": _access.access_dependency(roles=("staff",))' in src
    assert '"delete": _access.access_dependency(roles=("staff",))' in src
    assert 'Depends(_ACCESS["head"])' in src and 'Depends(_ACCESS["delete"])' in src
    assert "EmployeeRepository(session, **access.repo_kwargs).exists(item_id)" in src
    assert "EmployeeRepository(session, **access.repo_kwargs).delete(item_id)" in src


def test_tenant_guard_scopes_head_and_delete_to_the_tenant() -> None:
    src = _files("tenant_guard")["app/routers/employees.py"]
    assert '"head": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True)' in src
    assert '"delete": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True)' in src
