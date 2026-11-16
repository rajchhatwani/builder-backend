"""Audit B1-017: unlisted list/replace follow get/update; long identifiers; sample/bounds sanity."""

import re

from app.core.generator import generate
from app.core.generator.context import _constraints, _sample
from app.core.spec_models import Spec
from app.core.validation import validate
from tests.unit.test_generator import FIXTURES


def _spec(name: str = "field_access") -> Spec:
    return Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_unlisted_list_and_replace_are_not_a_side_door() -> None:
    spec = _spec()
    spec.auth.permissions = [p for p in spec.auth.permissions if p.operation in ("get", "update")]
    src = generate(spec)["app/routers/employees.py"]
    for op in ("list", "replace", "head", "delete", "get", "update"):
        assert re.search(rf'"{op}": _access\.access_dependency\(roles=\("staff",\)', src), op


def _field(**kw):
    from app.core.spec_models import SpecField

    return SpecField(name="q", **kw)


def test_sample_stays_inside_the_constraints() -> None:
    f = _field(type="decimal", max_value=-5)
    for _ in range(50):
        v = float(eval(_sample(f).replace("str(", "(", 1), {"_random": __import__("random")}))  # noqa: S307
        assert v <= -5
    f = _field(type="decimal", min_value=0.001, max_value=0.004)
    assert "round(" not in _sample(f) or float(
        eval(_sample(f).replace("str(", "(", 1), {"_random": __import__("random")})  # noqa: S307
    ) >= 0.001
    f = _field(type="integer", min_value=2147483000)
    for _ in range(50):
        assert eval(_sample(f), {"_random": __import__("random")}) <= 2147483647  # noqa: S307


def test_unsatisfiable_numeric_bounds_are_rejected() -> None:
    for kw in (
        {"type": "integer", "min_value": 1.5, "max_value": 1.7},
        {"type": "integer", "min_value": 3e9},
        {"type": "decimal", "min_value": 1e15},
    ):
        spec = _spec("library")
        spec.entities[0].fields.append(_field(**kw))
        assert any(i.code == "out_of_range" or i.code == "invalid_range" for i in validate(spec)), kw
    assert _constraints(_field(type="integer", min_value=1, max_value=5))


def test_generated_constraint_names_fit_postgres() -> None:
    from app.core.spec_models import SpecEntity, SpecField

    spec = _spec("library")
    spec.entities.append(
        SpecEntity(
            name="CustomerOrganizationMembershipRecord",
            table_name="customer_organization_membership_records",
            plural_path="customer_organization_membership_records",
            fields=[SpecField(name="external_reference_identifier_code", type="string", unique=True, max_length=20)],
        )
    )
    assert validate(spec) == []
    files = generate(spec)
    for text in files.values():
        for n in re.findall(r"name=['\"]((?:uq|ix|fk|pk)_[a-z0-9_]+)['\"]", text):
            assert len(n) <= 63, n
