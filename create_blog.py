"""Create a fully-fledged blog app via the Backend Builder API.

Env: BUILDER_TOKEN (required; session JWT or bb_pat_ API token),
BUILDER_URL (default http://localhost:8000).
Not idempotent: slug "blog-app" must be free. If a later step fails, the
half-built project is deleted (also on timeouts/connection errors) so the
script can simply be re-run.
Note: Post list/get are public, so draft/archived posts are readable by
anonymous callers; add a status filter or a row rule if that matters.
"""
import json
import os
import sys

import httpx

BASE = os.environ.get("BUILDER_URL", "http://localhost:8000")
TOKEN = os.environ.get("BUILDER_TOKEN")
if not TOKEN:
    print("ERROR: set BUILDER_TOKEN to a bearer token (session JWT or bb_pat_ API token)")
    sys.exit(1)
_raw = httpx.Client(base_url=BASE, timeout=10, headers={"Authorization": f"Bearer {TOKEN}"})
pid = None

def _fail(msg):
    print(msg)
    if pid:
        try:
            _raw.delete(f"/projects/{pid}")
            print(f"  cleaned up partial project {pid}")
        except httpx.HTTPError as exc:
            print(f"  cleanup of project {pid} failed ({exc!r}); delete it manually")
    sys.exit(1)

class _Api:
    """Client proxy: transport errors (timeout/connect) also trigger cleanup."""
    def __getattr__(self, name):
        fn = getattr(_raw, name)
        def call(*a, **kw):
            try:
                return fn(*a, **kw)
            except httpx.HTTPError as exc:
                _fail(f"ERROR transport: {exc!r}")
        return call

c = _Api()

def j(r):
    if r.status_code >= 400:
        _fail(f"ERROR {r.status_code}: {r.text}")
    return r.json()

# ── 1. Project ─────────────────────────────────────────────────────────────
proj = j(c.post("/projects", json={"name": "Blog App", "slug": "blog-app", "description": "A fully-featured blog platform with posts, categories, comments and tags."}))
pid = proj["id"]  # from here on, j() deletes the project on failure
print(f"✓ Project: {proj['name']} ({pid})")

# ── 2. Entities ────────────────────────────────────────────────────────────
entities = {}
for name in ["Category", "Tag", "Post", "Comment"]:
    e = j(c.post(f"/projects/{pid}/entities", json={"name": name}))
    entities[name] = e["id"]
    print(f"✓ Entity: {name} ({e['id']})")

# ── 3. Fields ──────────────────────────────────────────────────────────────
def field(entity_id, name, type_, **kw):
    payload = {"name": name, "type": type_, "required": True, "unique": False, "indexed": False, "default": None, "max_length": None, "min_value": None, "max_value": None, "enum_values": None}
    payload.update(kw)
    r = j(c.post(f"/entities/{entity_id}/fields", json=payload))
    print(f"  + field {name}: {type_}")
    return r

# Category fields
field(entities["Category"], "name", "string", unique=True, max_length=100)
field(entities["Category"], "slug", "string", unique=True, max_length=100)
field(entities["Category"], "description", "text", required=False)
field(entities["Category"], "color", "string", required=False, max_length=7)

# Tag fields
field(entities["Tag"], "name", "string", unique=True, max_length=80)
field(entities["Tag"], "slug", "string", unique=True, max_length=80)
field(entities["Tag"], "description", "text", required=False)

# Post fields
field(entities["Post"], "title", "string", max_length=255)
field(entities["Post"], "slug", "string", unique=True, max_length=255)
field(entities["Post"], "excerpt", "text", required=False)
field(entities["Post"], "content", "text")
field(entities["Post"], "cover_image_url", "string", required=False, max_length=2048)
field(entities["Post"], "status", "enum", enum_values=["draft", "published", "archived"], default="draft")
field(entities["Post"], "published_at", "datetime", required=False)
field(entities["Post"], "views", "integer", required=False, default=0, min_value=0)
field(entities["Post"], "reading_time_minutes", "integer", required=False, default=1, min_value=1)
field(entities["Post"], "is_featured", "boolean", default=False, required=False)
field(entities["Post"], "allow_comments", "boolean", default=True, required=False)
field(entities["Post"], "meta_title", "string", required=False, max_length=255)
field(entities["Post"], "meta_description", "text", required=False)

# Comment fields
field(entities["Comment"], "body", "text")
field(entities["Comment"], "author_name", "string", required=False, max_length=100)
field(entities["Comment"], "author_email", "string", required=False, max_length=255)
field(entities["Comment"], "is_approved", "boolean", default=False, required=False)
field(entities["Comment"], "is_spam", "boolean", default=False, required=False)

# ── 4. Relations ───────────────────────────────────────────────────────────
def rel(from_e, to_e, kind, from_name, to_name):
    r = j(c.post(f"/projects/{pid}/relations", json={
        "kind": kind, "from_entity_id": from_e, "to_entity_id": to_e,
        "from_name": from_name, "to_name": to_name, "on_delete": "cascade", "required": False
    }))
    print(f"✓ Relation: {from_name} ↔ {to_name} ({kind})")
    return r

rel(entities["Category"], entities["Post"], "one_to_many", "posts", "category")
rel(entities["Post"], entities["Comment"], "one_to_many", "comments", "post")
rel(entities["Post"], entities["Tag"], "many_to_many", "tags", "posts")

# ── 5. Update entity API options ────────────────────────────────────────────
ops_all = ["list", "get", "head", "create", "replace", "update", "delete"]
ops_ro = ["list", "get", "head"]

for name, ops, filterable, sortable, searchable in [
    ("Category", ops_all, ["name", "slug"], ["name", "created_at"], ["name", "description"]),
    ("Tag",      ops_all, ["name", "slug"], ["name", "created_at"], ["name", "description"]),
    ("Post",     ops_all, ["status", "is_featured", "allow_comments", "slug"], ["published_at", "views", "created_at", "title"], ["title", "excerpt", "content"]),
    ("Comment",  ops_all, ["is_approved", "is_spam"], ["created_at"], ["body", "author_name"]),
]:
    j(c.patch(f"/entities/{entities[name]}", json={
        "options": {
            "operations": ops,
            "filterable": filterable,
            "sortable": sortable,
            "searchable": searchable,
            "default_page_size": 20,
            "max_page_size": 100,
            "soft_delete": True,
        }
    }))
    print(f"✓ Options updated: {name}")

# ── 6. Auth config ─────────────────────────────────────────────────────────
auth = j(c.post(f"/projects/{pid}/auth", json={
    "enabled": True,
    "email_magic_link_enabled": False,
    "sms_otp_enabled": False,
    "email_verification_required": False,
    "invite_only": False,
    "multi_tenant": False,
    "deletion_mode": "soft",
    "token_store": "db",
    "access_token_ttl_minutes": 60,
    "refresh_token_ttl_days": 30,
    "jwt_algorithm": "HS256",
    "login_rate_limit": "10/minute",
    "register_rate_limit": "5/hour",
    "reset_rate_limit": "3/hour",
    "security_headers_enabled": True,
    "app_name": "Blog App",
    "app_url": "https://blog.example.com",
}))
print("✓ Auth config created")

# ── 7. Roles ────────────────────────────────────────────────────────────────
for role_data in [
    {"name": "admin",  "label": "Administrator", "is_default": False, "self_assignable": False, "position": 0},
    {"name": "author", "label": "Author",        "is_default": False, "self_assignable": False, "position": 1},
    {"name": "reader", "label": "Reader",        "is_default": True,  "self_assignable": True,  "position": 2},
]:
    r = j(c.post(f"/projects/{pid}/roles", json=role_data))
    print(f"✓ Role: {r['name']}")

# ── 8. Custom auth fields ───────────────────────────────────────────────────
for cf in [
    {"name": "display_name", "label": "Display Name", "type": "string", "required": True, "unique": False, "indexed": False, "max_length": 100, "position": 0},
    {"name": "bio",          "label": "Bio",           "type": "text",   "required": False,"unique": False, "indexed": False, "position": 1},
    {"name": "website_url",  "label": "Website URL",   "type": "url",    "required": False,"unique": False, "indexed": False, "position": 2},
    {"name": "avatar_url",   "label": "Avatar URL",    "type": "url",    "required": False,"unique": False, "indexed": False, "position": 3},
]:
    j(c.post(f"/projects/{pid}/auth/custom-fields", json=cf))
    print(f"✓ Custom field: {cf['name']}")

# ── 9. Permissions ─────────────────────────────────────────────────────────
perms = []
for eid, entity_name in [(entities["Category"], "Category"), (entities["Tag"], "Tag"),
                          (entities["Post"], "Post"), (entities["Comment"], "Comment")]:
    # Public read, except Comment (author_email / spam / unapproved): admin only
    read_roles = ["admin"] if entity_name == "Comment" else []
    for op in ["list", "get", "head"]:
        perms.append({"entity_id": eid, "operation": op, "roles": read_roles, "row_rule": None})
    # Taxonomy is admin-curated; authors/admins create Posts; readers may comment
    create_roles = {"Category": ["admin"], "Tag": ["admin"], "Post": ["author", "admin"],
                    "Comment": ["reader", "author", "admin"]}[entity_name]
    perms.append({"entity_id": eid, "operation": "create", "roles": create_roles, "row_rule": None})
    # Authors edit own Posts/Comments (role_scoped: admins see all), taxonomy admin only
    for op in ["replace", "update"]:
        if entity_name in ("Post", "Comment"):
            perms.append({"entity_id": eid, "operation": op, "roles": ["author", "admin"], "row_rule": "role_scoped"})
        else:
            perms.append({"entity_id": eid, "operation": op, "roles": ["admin"], "row_rule": None})
    # Only admins delete
    perms.append({"entity_id": eid, "operation": "delete", "roles": ["admin"], "row_rule": None})

j(c.post(f"/projects/{pid}/permissions", json={"permissions": perms}))
print(f"✓ Permissions set ({len(perms)} entries)")

# ── 10. Validate ────────────────────────────────────────────────────────────
report = j(c.post(f"/projects/{pid}/validate"))
if report["valid"]:
    print("\n🎉 Blog App project is VALID and ready to generate!")
else:
    print(f"\n⚠ Validation issues: {json.dumps(report['issues'], indent=2)}")

print(f"\n📋 Project ID: {pid}")
print("🌐 Open: http://localhost:5173")
