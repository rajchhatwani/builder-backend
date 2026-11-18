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
        NS(name="price", type="decimal", required=False, enum_values=None),
        NS(name="ratio", type="float", required=False, enum_values=None),
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
    props = out["components"]["schemas"]["ThingCreate"]["properties"]  # type: ignore[index]
    assert props["big"] == {"type": "integer"}
    assert props["blob"] == {}
    assert props["day"] == {"type": "string", "format": "date"}
    assert props["at"] == {"type": "string", "format": "date-time"}
    assert props["uid"] == {"type": "string", "format": "uuid"}
    assert props["kind"] == {"type": "string", "enum": ["a", "b"]}
    # pydantic v2 serialises Decimal as a JSON string; float stays a number (F-1024)
    assert props["price"]["type"] == "string" and props["price"]["format"] == "decimal"
    assert props["ratio"] == {"type": "number"}


def test_create_update_read_schemas_match_generated_models() -> None:
    """F-1023: Create requires the required fields, Update is partial, Read adds id + stamps."""
    schemas = _openapi_from_spec(_spec())["components"]["schemas"]  # type: ignore[index]
    assert schemas["ThingCreate"]["required"] == ["big"]
    assert "required" not in schemas["ThingUpdate"] or schemas["ThingUpdate"]["required"] == []
    read = schemas["ThingRead"]
    for name in ("id", "created_at", "updated_at"):
        assert name in read["properties"] and name in read["required"]
    paths = _openapi_from_spec(_spec())["paths"]
    coll, item = paths["/things"], paths["/things/{id}"]  # type: ignore[index]

    def body_ref(op: dict) -> str:  # type: ignore[type-arg]
        return op["requestBody"]["content"]["application/json"]["schema"]["$ref"]

    assert body_ref(coll["post"]).endswith("/ThingCreate")
    assert body_ref(item["put"]).endswith("/ThingCreate")
    assert body_ref(item["patch"]).endswith("/ThingUpdate")
    ok = item["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/ThingRead"}


def test_operation_shapes() -> None:
    paths = _openapi_from_spec(_spec())["paths"]
    coll, item = paths["/things"], paths["/things/{id}"]  # type: ignore[index]
    lst = coll["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    # the generated list route returns the Page envelope (F-1022)
    assert lst["type"] == "object"
    assert lst["properties"]["items"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/ThingRead"},
    }
    for k in ("total", "limit", "offset"):
        assert lst["properties"][k] == {"type": "integer"}
    for op in (coll["post"], item["put"], item["patch"]):
        assert "requestBody" in op
    assert "204" in item["delete"]["responses"] and "200" not in item["delete"]["responses"]
    assert "content" not in item["head"]["responses"]["200"]
    assert "content" in item["get"]["responses"]["200"]
