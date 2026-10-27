"""Enumerate EVERY route (FastAPI 0.156 wraps routers in _IncludedRouter, so `app.routes` alone hides them)
and classify its guard.  Also cross-checks the org role table (platform_authz.ORG_ROUTE_ROLES) and the
access-matrix PUBLIC list.   Read-only.

Run:  PYTHONPATH=. BUILDER_ENVIRONMENT=local uv run python review/tests/dump_routes.py
Writes review/artifacts/routes.json.
"""
import json
import os
import pathlib

os.environ.setdefault("BUILDER_ENVIRONMENT", "local")
from fastapi.routing import APIRoute  # noqa: E402

from app.api import security  # noqa: E402
from app.core import platform_authz as authz  # noqa: E402
from app.main import app  # noqa: E402
from tests.api.test_access_matrix import PUBLIC  # noqa: E402


def calls(dep) -> set:
    out, st = set(), [dep]
    while st:
        d = st.pop()
        out.add(d.call)
        st.extend(d.dependencies)
    return out


def contexts():
    for r in app.routes:
        if type(r).__name__ == "_IncludedRouter":
            for c in r.effective_route_contexts():
                yield c.path, c.methods, calls(c.dependant) | {
                    getattr(d, "dependency", None) for d in c.dependencies
                }
        elif isinstance(r, APIRoute):
            yield r.path, r.methods, calls(r.dependant)


rows = []
for path, methods, cs in contexts():
    names = {getattr(c, "__qualname__", str(c)) for c in cs if c}
    for m in sorted(methods - {"HEAD", "OPTIONS"}):
        if security.guard in cs:
            g = "guard"
        elif any("require_admin" in n or "admin_principal" in n for n in names):
            g = "admin"
        elif security.org_context in cs if hasattr(security, "org_context") else False:
            g = "org_context"
        elif security.current_principal in cs or security.session_principal in cs:
            g = "principal"
        elif "scim_auth" in names:
            g = "scim"
        elif (m, path) in PUBLIC:
            g = "public"
        else:
            g = "NONE"
        rows.append({"method": m, "path": path, "guard": g, "deps": sorted(names)})

pathlib.Path("review/artifacts").mkdir(parents=True, exist_ok=True)
pathlib.Path("review/artifacts/routes.json").write_text(json.dumps(rows, indent=1))
print(len(rows), "routes")
from collections import Counter
print(Counter(r["guard"] for r in rows))
print("NO GUARD DETECTED:")
for r in rows:
    if r["guard"] == "NONE":
        print("  ", r["method"], r["path"])
missing = [(r["method"], r["path"]) for r in rows
           if r["path"].startswith("/orgs/{slug}") and authz.required_org_role(r["method"], r["path"]) is None]
print("ORG ROUTES MISSING FROM ORG_ROUTE_ROLES:", missing)
stale = [k for k in authz.ORG_ROUTE_ROLES if (k[0], k[1]) not in {(r["method"], r["path"]) for r in rows}]
print("ORG_ROUTE_ROLES ENTRIES THAT MATCH NO ROUTE:", stale)
print("public-list entries matching no route:", [p for p in PUBLIC if p not in {(r["method"], r["path"]) for r in rows}])
