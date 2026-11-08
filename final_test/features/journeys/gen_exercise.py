# exec()'d inside j04_build_generated.py (uses g, base, J, rec, json)
s, oa = g("GET", "/openapi.json")
sch = oa.get("components", {}).get("schemas", {})
def resolve(x):
    if "$ref" in x: return sch[x["$ref"].split("/")[-1]]
    for k in ("anyOf", "oneOf"):
        if k in x:
            for y in x[k]:
                if y.get("type") != "null": return resolve(y)
    return x
import random, string, datetime
def val(name, p, ids):
    p = resolve(p); t = p.get("type"); f = p.get("format")
    if p.get("enum"): return p["enum"][0]
    if name.endswith("_id") and name[:-3] in ids: return ids[name[:-3]]
    if f == "uuid": return str(uuid.uuid4())
    if f == "date-time": return datetime.datetime.utcnow().isoformat()
    if f == "date": return "2026-01-01"
    if f == "email": return f"x{RUN}@example.com"
    if t == "integer": return max(int(p.get("minimum", 1)), 1)
    if t == "number": return max(float(p.get("minimum", 1)), 1.0)
    if t == "boolean": return True
    if t == "array": return []
    if t == "object": return {}
    if f in ("password",): return "Passw0rd!x"
    n = int(p.get("maxLength", 12)); return ("v" + RUN + name)[:n] or "v"
ids = {}; made = {}
colls = [p for p in oa["paths"] if "{" not in p and "post" in oa["paths"][p] and p not in ("/health", "/ready")]
for rnd in range(4):
    for path in colls:
        if path in made: continue
        body_s = resolve(oa["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"])
        props = body_s.get("properties", {}); req = body_s.get("required", [])
        body = {k: val(k, v, ids) for k, v in props.items() if k in req}
        s, r = g("POST", path, body)
        if s in (200, 201):
            made[path] = (body, r)
            n_ = path.strip("/"); sing = n_[:-3] + "y" if n_.endswith("ies") else n_[:-3] + "f" if n_.endswith("ves") else n_[:-2] if n_.endswith("ses") else n_.rstrip("s")
            ids[sing] = r.get("id")
for path in colls:
    n = path.strip("/")
    if path not in made:
        rec(J + ".crud." + n, f"POST {path} create", False, "could not create via generic exerciser (FK/needs auth?)"); continue
    body, r = made[path]; rid = r.get("id")
    rec(J + ".crud." + n, f"POST {path} create 201 with id", bool(rid), json.dumps(r)[:200])
    s, r2 = g("GET", f"{path}/{rid}"); rec(J + ".get." + n, f"GET {path}/id", s == 200 and r2.get("id") == rid, f"{s}")
    s, r2 = g("GET", f"{path}?limit=2&offset=0"); rec(J + ".list." + n, f"list {path} paginates", s == 200, f"{s} {json.dumps(r2)[:120]}")
    s, r2 = g("GET", f"{path}?limit=100000"); rec(J + ".listmax." + n, f"{path} limit>max clamped or 422, not 500", s < 500, f"{s}")
    s, r2 = g("GET", f"{path}/{uuid.uuid4()}"); rec(J + ".404." + n, f"{path} unknown id 404", s == 404, f"{s}")
    s, r2 = g("GET", f"{path}/not-a-uuid"); rec(J + ".badid." + n, f"{path} malformed id 4xx not 500", 400 <= s < 500, f"{s}")
    s, r2 = g("POST", path, {}); rec(J + ".empty." + n, f"{path} empty body 422", s == 422, f"{s}")
    s, r2 = g("POST", path, {"x" * 10: 1, **body}); rec(J + ".extra." + n, f"{path} unknown field handled", s < 500, f"{s}")
    s, r2 = g("PATCH", f"{path}/{rid}", {}); rec(J + ".patch0." + n, f"PATCH {path}/id empty body not 500", s < 500, f"{s}")
    s, r2 = g("DELETE", f"{path}/{rid}"); rec(J + ".del." + n, f"DELETE {path}/id", s in (200, 204, 409, 405), f"{s} {json.dumps(r2)[:150]}")
    if s in (200, 204):
        s, r2 = g("GET", f"{path}/{rid}"); rec(J + ".gone." + n, f"{path} after delete 404", s == 404, f"{s}")
