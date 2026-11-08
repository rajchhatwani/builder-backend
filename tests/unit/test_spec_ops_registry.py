"""Pure logic of the spec op registry: payload checks, inverse correctness, op recognition."""

import json
from typing import Any

import pytest

from app.core.spec_models import (
    Spec,
    SpecAuth,
    SpecEntity,
    SpecField,
    SpecPermission,
    SpecProject,
    SpecRelation,
)
from app.exceptions import AppError
from app.services.ops.canon import canonical_bytes, canonical_hash
from app.services.ops.registry import REGISTRY, parse, plan, recognise


def _spec() -> Spec:
    return Spec(
        project=SpecProject(name="Shop", slug="shop"),
        entities=[
            SpecEntity(
                name="Customer",
                table_name="customers",
                plural_path="customers",
                fields=[
                    SpecField(name="email", type="string", required=True, max_length=200),
                    SpecField(name="age", type="integer", min_value=0),
                    SpecField(name="note", type="text"),
                ],
            ),
            SpecEntity(name="Order", table_name="orders", plural_path="orders", fields=[]),
        ],
        relations=[
            SpecRelation(
                kind="one_to_many",
                from_entity="Customer",
                to_entity="Order",
                from_name="orders",
                to_name="customer",
            )
        ],
    )


def _with_auth(spec: Spec) -> Spec:
    out = spec.model_copy(deep=True)
    out.auth = SpecAuth(
        permissions=[
            SpecPermission(entity="Order", operation="list", roles=["admin"]),
            SpecPermission(entity="Customer", operation="list", roles=["admin"]),
        ]
    )
    return out


# One sample payload per registry op (the registry is closed: a new op must be added here).
SAMPLES: dict[str, dict[str, Any]] = {
    "add_entity": {
        "entity": {
            "name": "Invoice",
            "fields": [{"name": "total", "type": "decimal"}, {"name": "paid", "type": "boolean"}],
        }
    },
    "update_entity": {"name": "Customer", "changes": {"plural_path": "clients"}},
    "remove_entity": {"name": "Customer"},
    "add_field": {"entity": "Customer", "field": {"name": "phone", "type": "string"}, "index": 1},
    "update_field": {
        "entity": "Customer",
        "name": "email",
        "changes": {"max_length": 50, "unique": True, "default": None},
    },
    "remove_field": {"entity": "Customer", "name": "age"},
    "add_relation": {
        "relation": {
            "kind": "one_to_one",
            "from_entity": "Order",
            "to_entity": "Customer",
            "from_name": "owner",
            "to_name": "last_order",
        }
    },
    "update_relation": {
        "from_entity": "Customer",
        "from_name": "orders",
        "to_entity": "Order",
        "changes": {"required": True, "to_name": "buyer"},
    },
    "remove_relation": {"from_entity": "Customer", "from_name": "orders", "to_entity": "Order"},
    "set_section": {
        "section": "settings",
        "items": [{"key": "page_size", "type": "int", "default": 20}],
    },
    "replace_spec": {"spec": json.loads(_spec().model_dump_json())},
}


def test_every_registered_op_has_a_sample() -> None:
    assert set(SAMPLES) == set(REGISTRY)


@pytest.mark.parametrize("op_type", sorted(SAMPLES))
@pytest.mark.parametrize("with_auth", [False, True])
def test_apply_then_inverse_restores_canonical_bytes(op_type: str, with_auth: bool) -> None:
    before = _with_auth(_spec()) if with_auth else _spec()
    planned = plan(before, op_type, SAMPLES[op_type])
    assert canonical_bytes(planned.after) != canonical_bytes(before) or op_type == "replace_spec"
    inverse = plan(planned.after, planned.inverse_type, planned.inverse_payload)
    assert canonical_bytes(inverse.after) == canonical_bytes(before)
    # and the inverse of the inverse brings the change back
    again = plan(inverse.after, inverse.inverse_type, inverse.inverse_payload)
    assert canonical_bytes(again.after) == canonical_bytes(planned.after)


def test_simple_ops_get_a_typed_inverse_and_cascades_get_a_snapshot() -> None:
    add = plan(_spec(), "add_field", SAMPLES["add_field"])
    assert add.inverse_type == "remove_field"
    # removing Customer also drops its relation: a typed add_entity cannot bring that back
    cascade = plan(_spec(), "remove_entity", SAMPLES["remove_entity"])
    assert cascade.inverse_type == "replace_spec"
    leaf = plan(_spec(), "remove_entity", {"name": "Order"})
    assert leaf.inverse_type == "replace_spec"  # relation to Order cascades too
    lone = _spec()
    lone.relations = []
    assert plan(lone, "remove_entity", {"name": "Order"}).inverse_type == "add_entity"


def test_unknown_op_type_is_a_422() -> None:
    with pytest.raises(AppError) as err:
        parse("drop_database", {})
    assert err.value.status_code == 422 and err.value.code == "unknown_op_type"


def test_invalid_payload_is_a_422_that_never_echoes_the_value() -> None:
    secret = "s3cr3t-value-123"
    with pytest.raises(AppError) as err:
        parse("add_field", {"entity": "X", "field": {"name": secret, "type": "string"}})
    assert err.value.status_code == 422
    assert secret not in json.dumps(err.value.details) + err.value.message
    for bad in (
        {"name": "customer", "changes": {}},  # lowercase entity name via update
        {"name": "Customer", "changes": {"nope": 1}},
    ):
        with pytest.raises(AppError):
            parse("update_entity", bad)
    with pytest.raises(AppError):
        parse("add_field", {"entity": "X", "field": {"name": "a", "type": "string"}, "extra": 1})


@pytest.mark.parametrize(
    ("op_type", "payload", "code"),
    [
        ("add_entity", {"entity": {"name": "Customer"}}, "conflict"),
        ("remove_entity", {"name": "Nope"}, "not_found"),
        (
            "add_field",
            {"entity": "Customer", "field": {"name": "email", "type": "string"}},
            "conflict",
        ),
        ("remove_field", {"entity": "Customer", "name": "zzz"}, "not_found"),
        ("remove_relation", {"from_entity": "A", "from_name": "b", "to_entity": "C"}, "not_found"),
    ],
)
def test_ops_that_cannot_apply_are_refused_with_a_clear_status(
    op_type: str, payload: dict[str, Any], code: str
) -> None:
    with pytest.raises(AppError) as err:
        plan(_spec(), op_type, payload)
    assert err.value.code == code


def test_canonical_form_ignores_permission_order_only() -> None:
    a = _with_auth(_spec())
    b = a.model_copy(deep=True)
    assert b.auth is not None
    b.auth.permissions.reverse()
    assert canonical_bytes(a) == canonical_bytes(b)
    assert canonical_hash(a) == canonical_hash(b)
    c = a.model_copy(deep=True)
    c.entities[0].fields.reverse()  # field order is meaningful
    assert canonical_bytes(a) != canonical_bytes(c)


def test_recognise_names_a_single_typed_change_and_falls_back_otherwise() -> None:
    before = _spec()
    for op_type in ("add_entity", "update_entity", "add_field", "update_field", "remove_field"):
        after = plan(before, op_type, SAMPLES[op_type]).after
        assert recognise(before, after).op_type == op_type
    rel = plan(before, "add_relation", SAMPLES["add_relation"]).after
    assert recognise(before, rel).op_type == "add_relation"
    # two changes at once, or a rename, are not one typed op
    two = plan(rel, "add_field", SAMPLES["add_field"]).after
    assert recognise(before, two).op_type == "replace_spec"
    renamed = plan(
        before, "update_entity", {"name": "Order", "changes": {"name": "Purchase"}}
    ).after
    seen = recognise(before, renamed)
    assert canonical_bytes(
        plan(before, seen.op_type, json.loads(seen.payload.model_dump_json())).after
    ) == canonical_bytes(renamed)
