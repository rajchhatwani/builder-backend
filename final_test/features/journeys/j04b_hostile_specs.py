from lib import *
import concurrent.futures as cf
em, t = user("host")
_o = call(t, "GET", "/orgs")[1]["items"][0]["id"]
A.call("PATCH", f"/admin/organizations/{_o}/overrides", {"project_override": 500, "reason": "bbf"}, A.staff("admin"))
def proj(n):
    c, b, _ = call(t, "POST", "/projects", {"name": f"h{n}-{RUN}"}); return b["id"]
def put_gen(label, spec_mut, expect_clean=True):
    pid = proj(label.replace(" ", ""))
    c, sp, _ = call(t, "GET", f"/projects/{pid}/spec")
    sp = spec_mut(sp)
    t0 = time.time(); c1, b1, _ = call(t, "PUT", f"/projects/{pid}/spec", sp)
    c2, b2, _ = call(t, "POST", f"/projects/{pid}/validate") if c1 == 200 else (None, {}, None)
    c3, b3, _ = call(t, "POST", f"/projects/{pid}/generate/preview") if c1 == 200 else (None, {}, None)
    dt = time.time() - t0
    ok = c1 < 500 and (c2 is None or c2 < 500) and (c3 is None or c3 < 500)
    rec("J4.host." + label, f"hostile spec '{label}' fails cleanly (no 5xx, {dt:.1f}s)", ok, f"put={c1} validate={c2} {json.dumps(b2)[:150]} preview={c3} {json.dumps(b3)[:150]}")
    return c1, c2, c3, b1, b2, b3
ent = lambda n, fields=None: {"name": n, "table_name": n.lower() + "s", "plural_path": n.lower() + "s", "options": {}, "fields": fields or [{"name": "title", "type": "string", "required": True}]}
def base(sp): sp["entities"] = []; sp["relations"] = []; return sp
put_gen("empty entities", lambda sp: base(sp))
r = put_gen("duplicate entity names", lambda sp: {**base(sp), "entities": [ent("Book"), ent("Book")]})
r = put_gen("duplicate field names", lambda sp: {**base(sp), "entities": [ent("Book", [{"name": "t", "type": "string"}, {"name": "t", "type": "string"}])]})
for rw in ["Class", "Select", "Table", "User", "Order", "Group", "Metadata", "Base", "Session", "Items", "Alembic"]:
    r = put_gen("reserved entity " + rw, lambda sp, rw=rw: {**base(sp), "entities": [ent(rw)]})
for fw in ["id", "class", "from", "select", "metadata", "created_at", "__init__", "model_config", "update", "type"]:
    r = put_gen("reserved field " + fw, lambda sp, fw=fw: {**base(sp), "entities": [ent("Thing", [{"name": fw, "type": "string"}])]})
r = put_gen("unicode entity name", lambda sp: {**base(sp), "entities": [ent("Café")]})
r = put_gen("emoji field", lambda sp: {**base(sp), "entities": [ent("Thing", [{"name": "😀", "type": "string"}])]})
r = put_gen("sql keyword table", lambda sp: {**base(sp), "entities": [{**ent("Thing"), "table_name": "users; DROP TABLE x;--"}]})
r = put_gen("sql keyword plural_path", lambda sp: {**base(sp), "entities": [{**ent("Thing"), "plural_path": "../../etc/passwd"}]})
r = put_gen("quote in default", lambda sp: {**base(sp), "entities": [ent("Thing", [{"name": "t", "type": "string", "default": "'; DROP TABLE x;--"}])]})
r = put_gen("triple quote/code in default", lambda sp: {**base(sp), "entities": [ent("Thing", [{"name": "t", "type": "string", "default": "\"\"\"\nimport os;os.system('id')\n\"\"\""}])]})
r = put_gen("enum value injection", lambda sp: {**base(sp), "entities": [ent("Thing", [{"name": "t", "type": "enum", "enum_values": ["a'); import os #", "b"]}])]})
r = put_gen("enum empty", lambda sp: {**base(sp), "entities": [ent("Thing", [{"name": "t", "type": "enum", "enum_values": []}])]})
r = put_gen("min>max", lambda sp: {**base(sp), "entities": [ent("Thing", [{"name": "t", "type": "integer", "min_value": 10, "max_value": 1}])]})
r = put_gen("circular relations", lambda sp: {**base(sp), "entities": [ent("A"), ent("B"), ent("C")], "relations": [
    {"kind": "one_to_many", "from_entity": "A", "to_entity": "B", "from_name": "bs", "to_name": "a", "on_delete": "restrict", "required": True},
    {"kind": "one_to_many", "from_entity": "B", "to_entity": "C", "from_name": "cs", "to_name": "b", "on_delete": "restrict", "required": True},
    {"kind": "one_to_many", "from_entity": "C", "to_entity": "A", "from_name": "as_", "to_name": "c", "on_delete": "restrict", "required": True}]})
r = put_gen("relation to unknown entity", lambda sp: {**base(sp), "entities": [ent("A")], "relations": [{"kind": "one_to_many", "from_entity": "A", "to_entity": "Nope", "from_name": "bs", "to_name": "a", "on_delete": "restrict", "required": True}]})
r = put_gen("duplicate relation names", lambda sp: {**base(sp), "entities": [ent("A"), ent("B")], "relations": [
    {"kind": "one_to_many", "from_entity": "A", "to_entity": "B", "from_name": "x", "to_name": "a", "on_delete": "restrict", "required": False},
    {"kind": "one_to_many", "from_entity": "A", "to_entity": "B", "from_name": "x", "to_name": "a", "on_delete": "restrict", "required": False}]})
r = put_gen("1000 fields", lambda sp: {**base(sp), "entities": [ent("Wide", [{"name": f"f{i}", "type": "string"} for i in range(1000)])]})
r = put_gen("300 entities", lambda sp: {**base(sp), "entities": [ent("E" + "".join(chr(97 + int(d)) for d in str(i))) for i in range(300)]})
r = put_gen("10k char strings", lambda sp: {**base(sp), "entities": [ent("Thing", [{"name": "t", "type": "string", "default": "x" * 10000}])]})
# huge body
pid = proj("huge"); big = {"spec_version": 1, "project": {"name": "x", "slug": "x"}, "entities": [], "padding": "x" * (12 * 1024 * 1024)}
try: c, b, _ = call(t, "PUT", f"/projects/{pid}/spec", big)
except Exception as ex: c = 413 if "reset" in str(ex).lower() or "broken" in str(ex).lower() else 0
rec("J4.host.12mb_body", "12MB spec body refused 413/422 not 500", c in (413, 422, 400), f"HTTP {c}")
c, b, _ = call(t, "PUT", f"/projects/{pid}/spec", {"hello": "world"}); rec("J4.host.garbage_spec", "garbage spec 422", c == 422, f"HTTP {c}")
c, b, _ = call(t, "PUT", f"/projects/{pid}/spec", [1, 2]); rec("J4.host.array_spec", "array body 422", c == 422, f"HTTP {c}")
# builder-side CRUD edge
pid = proj("crud"); 
c, e, _ = call(t, "POST", f"/projects/{pid}/entities", {"name": "Book"}); eid = e["id"]
c, b, _ = call(t, "POST", f"/projects/{pid}/entities", {"name": "Book"}); rec("J4.crud.dup_entity", "duplicate entity 409", c == 409, f"HTTP {c}")
for nm in ["book", "1Book", "Bo ok", "", "B" * 101, "Sélect"]:
    c, b, _ = call(t, "POST", f"/projects/{pid}/entities", {"name": nm}); rec("J4.crud.bad_entity_name", f"entity name {nm[:15]!r} -> 422", c == 422, f"HTTP {c}")
c, f, _ = call(t, "POST", f"/entities/{eid}/fields", {"name": "title", "type": "string"}); fid = f["id"]
c, b, _ = call(t, "POST", f"/entities/{eid}/fields", {"name": "title", "type": "string"}); rec("J4.crud.dup_field", "duplicate field 409", c == 409, f"HTTP {c}")
c, b, _ = call(t, "POST", f"/entities/{eid}/fields", {"name": "x", "type": "nope"}); rec("J4.crud.bad_type", "unknown field type 422", c == 422, f"HTTP {c}")
c, b, _ = call(t, "PATCH", f"/fields/{fid}", {"max_length": -1}); rec("J4.crud.neg", "negative max_length 422", c == 422, f"HTTP {c}")
c, b, _ = call(t, "POST", f"/projects/{pid}/relations", {"kind": "one_to_many", "from_entity_id": eid, "to_entity_id": eid, "from_name": "kids", "to_name": "parent"}); rec("J4.crud.self_rel", "self relation accepted/refused cleanly", c in (201, 409, 422), f"HTTP {c}")
c, b, _ = call(t, "POST", f"/projects/{pid}/relations", {"kind": "one_to_many", "from_entity_id": str(uuid.uuid4()), "to_entity_id": eid, "from_name": "a", "to_name": "b"}); rec("J4.crud.rel_unknown", "relation to unknown entity 404/422", c in (404, 422), f"HTTP {c}")
c, b, _ = call(t, "DELETE", f"/entities/{eid}"); rec("J4.crud.del_entity", "delete entity", c in (200, 204, 409), f"HTTP {c}")
# optimistic locking
c, b, _ = call(t, "GET", f"/projects/{pid}"); v = b["version"]
c1, _, _ = call(t, "PATCH", f"/projects/{pid}", {"version": v, "name": "rn1-" + RUN}); c2, b2, _ = call(t, "PATCH", f"/projects/{pid}", {"version": v, "name": "rn2-" + RUN})
rec("J3.lock", "stale version PATCH -> 409", c1 == 200 and c2 == 409, f"{c1} {c2} {json.dumps(b2)[:150]}")
def rn(i): return call(t, "PATCH", f"/projects/{pid}", {"version": c1 and 2 + 0, "name": f"par{i}-{RUN}"})[0]
c, b, _ = call(t, "GET", f"/projects/{pid}"); v = b["version"]
def rn(i): return call(t, "PATCH", f"/projects/{pid}", {"version": v, "name": f"par{i}-{RUN}"})[0]
with cf.ThreadPoolExecutor(8) as ex: codes = list(ex.map(rn, range(8)))
rec("J3.lock_race", "8 parallel renames with the same version: exactly one wins", codes.count(200) == 1, str(codes))
