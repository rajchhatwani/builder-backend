"""MCP get_openapi type map and operation shapes (F-0966)."""

from types import SimpleNamespace as NS

from app.services.mcp_service import _openapi_from_spec


def _spec() -> NS:
    fields = [
        NS(name="big", type="bigint", required=True, enum_values=None),
        NS(name="blob", type="json", required=False, enum_values=None),
        NS(name="day", type="date", required=False, enum_values=None),
        NS(name="at", type="datetime", required=False, enum_values=None),
        NS(name="uid", type="uuid", required=False, enum_values=None),
        NS(name="kind", type="enum", required=False, enum_values=["a", "b"]),
    ]
    ent = NS(
        name="Thing",
        plural_path="things",
        fields=fields,
        options=NS(operations=["list", "create", "get", "replace", "update", "delete", "head"]),
    )
    return NS(entities=[ent], project=NS(name="p"))


def test_type_map_matches_generated_project() -> None:
    out = _openapi_from_spec(_spec())
    props = out["components"]["schemas"]["Thing"]["properties"]  # type: ignore[index]
    assert props["big"] == {"type": "integer"}
    assert props["blob"] == {}
    assert props["day"] == {"type": "string", "format": "date"}
    assert props["at"] == {"type": "string", "format": "date-time"}
    assert props["uid"] == {"type": "string", "format": "uuid"}
    assert props["kind"] == {"type": "string", "enum": ["a", "b"]}


def test_operation_shapes() -> None:
    paths = _openapi_from_spec(_spec())["paths"]
    coll, item = paths["/things"], paths["/things/{id}"]  # type: ignore[index]
    lst = coll["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert lst["type"] == "array"
    assert lst["items"] == {"$ref": "#/components/schemas/Thing"}
    for op in (coll["post"], item["put"], item["patch"]):
        assert "requestBody" in op
    assert "204" in item["delete"]["responses"] and "200" not in item["delete"]["responses"]
    assert "content" not in item["head"]["responses"]["200"]
    assert "content" in item["get"]["responses"]["200"]
