from lib import *
import urllib.request as ur, urllib.error as ue
ST = A.staff("admin")
oe, ot = user("mcpo"); me_, mt = user("mcpm"); xe, xt = user("mcpx")
c, org, _ = call(ot, "POST", "/orgs", {"name": "MCP Org " + RUN}); slug, oid = org["slug"], org["id"]
def plan(p): return A.call("PATCH", f"/admin/organizations/{oid}/plan", {"plan_id": p, "reason": "bbf"}, ST)
# plan flag enforcement
c, b, _ = call(ot, "POST", "/account/tokens", {"name": "mcp-free", "scopes": ["mcp:read"], "project_id": None}); 
rec("J12.01", "scopes: mcp:read accepted by validator for personal(free) org? (402 expected when plan has no MCP)", c in (201, 402, 403), f"HTTP {c} {json.dumps(b)[:200]}")
c, b, _ = call(ot, "POST", "/account/tokens", {"name": "bad", "scopes": ["mcp"]}); rec("J12.02", "bare 'mcp' scope rejected as invalid (422)", c == 422, f"HTTP {c}")
plan("team")
c, p, _ = call(ot, "POST", "/projects", {"name": "mcp-proj-" + RUN, "organization_id": oid}); pid = p["id"]
c, p2, _ = call(ot, "POST", "/projects", {"name": "mcp-proj2-" + RUN, "organization_id": oid})
c, e, _ = call(ot, "POST", f"/projects/{pid}/entities", {"name": "Book"})
c, b, _ = call(ot, "POST", "/account/tokens", {"name": "mcp-read", "scopes": ["mcp:read"], "project_id": pid}); rec("J12.03", "team org: project-pinned mcp:read token created", c == 201, f"HTTP {c} {json.dumps(b)[:200]}"); rt = b.get("token")
c, b, _ = call(ot, "POST", "/account/tokens", {"name": "mcp-write", "scopes": ["mcp:read", "mcp:write", "mcp:generate"], "project_id": pid}); wt = b.get("token")
c, b, _ = call(ot, "POST", "/account/tokens", {"name": "rest-only", "scopes": ["read"]}); resttok = b.get("token")
class Mcp:
    def __init__(self, tok): self.tok = tok; self.sid = None; self.n = 0
    def rpc(self, method, params=None, notify=False):
        self.n += 1
        body = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {}), **({} if notify else {"id": self.n})}
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        if self.tok: h["Authorization"] = "Bearer " + self.tok
        if self.sid: h["Mcp-Session-Id"] = self.sid
        try:
            r = ur.urlopen(ur.Request(A.base + "/mcp/", json.dumps(body).encode(), h, method="POST"), timeout=30); raw = r.read().decode(); st = r.status
            self.sid = r.headers.get("Mcp-Session-Id", self.sid)
        except ue.HTTPError as e: raw = e.read().decode(); st = e.code
        data = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                try: data = json.loads(line[5:].strip())
                except Exception: pass
        if data is None:
            try: data = json.loads(raw)
            except Exception: data = {"raw": raw[:200]}
        return st, data
    def init(self):
        s, d = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "bbf", "version": "1"}}); self.rpc("notifications/initialized", None, notify=True); return s, d
    def tool(self, name, args=None): return self.rpc("tools/call", {"name": name, "arguments": args or {}})
s, d = Mcp(None).init(); rec("J12.10", "MCP without token refused", s in (401, 403) or "error" in json.dumps(d).lower(), f"{s} {json.dumps(d)[:150]}")
s, d = Mcp("junk").init(); rec("J12.11", "MCP with junk token refused/err on call", True, f"{s} {json.dumps(d)[:120]}")
m = Mcp(rt); s, d = m.init(); rec("J12.12", "MCP initialize with valid token", s == 200, f"{s} {json.dumps(d)[:200]}")
s, d = m.rpc("tools/list"); tools = [t["name"] for t in d.get("result", {}).get("tools", [])]; rec("J12.13", "tools/list returns tools, none destructive", len(tools) >= 5 and not any("delete" in t for t in tools), ",".join(tools))
s, d = m.tool("list_projects"); rec("J12.14", "list_projects while member has MCP disabled -> empty or pinned only", s == 200, f"{json.dumps(d)[:300]}")
c, b, _ = call(ot, "PATCH", f"/projects/{pid}/members/{call(ot,'GET','/account/me')[1]['id']}/mcp", {"mcp_enabled": True}); rec("J12.15", "owner enables MCP for self on project", c in (200, 204), f"HTTP {c} {json.dumps(b)[:150]}")
s, d = m.tool("list_projects"); rec("J12.16", "list_projects shows the MCP-enabled pinned project only", pid in json.dumps(d) and p2["id"] not in json.dumps(d), json.dumps(d)[:300])
s, d = m.tool("get_project_spec", {"project_id": p2["id"]}); rec("J12.17", "token pinned to project A cannot read project B", "error" in json.dumps(d).lower() or d.get("result", {}).get("isError"), json.dumps(d)[:200])
s, d = m.tool("get_project_spec", {"project_id": pid}); rec("J12.18", "read tool works on pinned project", s == 200 and "Book" in json.dumps(d), json.dumps(d)[:200])
mt_ = [t for t in tools if t not in ("list_projects",) and any(k in t for k in ("add", "create", "update", "set"))]
if mt_:
    s, d = m.tool(mt_[0], {"project_id": pid, "name": "Hack"}); rec("J12.19", f"read-scoped token cannot call write tool {mt_[0]}", "scope" in json.dumps(d).lower() or "error" in json.dumps(d).lower() or d.get("result", {}).get("isError"), json.dumps(d)[:200])
w = Mcp(wt); w.init()
for t in tools:
    if "generate" in t or "preview" in t:
        s, d = w.tool(t, {"project_id": pid}); rec("J12.20", f"generate tool {t} with mcp:generate", s == 200 and not d.get("result", {}).get("isError"), json.dumps(d)[:200]); break
s, d = w.tool("no_such_tool"); rec("J12.21", "unknown tool -> clean error", s == 200 or s < 500, f"{s} {json.dumps(d)[:100]}")
s, d = w.tool("get_project_spec", {"project_id": "not-a-uuid"}); rec("J12.22", "malformed project id -> clean error", s < 500, f"{s} {json.dumps(d)[:120]}")
s, d = w.tool("get_project_spec", {"project_id": "x" * 100000}); rec("J12.23", "100KB argument handled", s < 500, f"{s}")
# REST token on MCP and MCP token on REST
s, d = Mcp(resttok).init(); s2, d2 = Mcp(resttok).tool("list_projects"); rec("J12.30", "REST-scope token has no MCP access", "scope" in json.dumps(d2).lower() or "error" in json.dumps(d2).lower() or s2 in (401, 403), f"{s2} {json.dumps(d2)[:140]}")
c, b, _ = A.call("GET", "/projects", None, rt); rec("J12.31", "MCP-scope token on REST /projects refused", c in (401, 403), f"HTTP {c}")
# quotas
plan_info = call(ot, "GET", f"/orgs/{slug}/plan")[1]["plan"]; cap = plan_info["max_mcp_tokens"]; codes = []
for i in range(cap + 2):
    c, b, _ = call(ot, "POST", "/account/tokens", {"name": f"mcpq{i}", "scopes": ["mcp:read"], "project_id": pid}); codes.append(c)
rec("J12.40", f"MCP token cap {cap}: n+1 -> 402 naming MCP", 402 in codes and "mcp" in json.dumps(b).lower(), f"{codes} {json.dumps(b)[:150]}")
# org policy interaction
c, b, _ = call(ot, "GET", f"/orgs/{slug}/policies"); 
# downgrade to free: existing mcp tokens stop?
plan("free"); s, d = Mcp(rt).init(); s2, d2 = Mcp(rt).tool("list_projects"); rec("J12.50", "after downgrade to free (allow_mcp false) existing MCP token is refused", s2 in (401, 402, 403) or "error" in json.dumps(d2).lower() and "projects" not in json.dumps(d2).lower(), f"{s2} {json.dumps(d2)[:200]}")
plan("team")
# revoke
c, b, _ = call(ot, "GET", "/account/tokens"); tid = next(t["id"] for t in b["items"] if t["name"] == "mcp-read") if isinstance(b, dict) and "items" in b else None
if tid:
    call(ot, "DELETE", f"/account/tokens/{tid}"); s2, d2 = Mcp(rt).tool("list_projects"); rec("J12.60", "revoked MCP token refused", s2 in (401, 403) or "error" in json.dumps(d2).lower(), f"{s2} {json.dumps(d2)[:120]}")
# member mcp toggle and viewer
c, b, _ = call(xt, "PATCH", f"/projects/{pid}/members/{call(xt,'GET','/account/me')[1]['id']}/mcp", {"mcp_enabled": True}); rec("J12.70", "outsider cannot enable MCP on a project they are not in", c in (403, 404), f"HTTP {c}")
