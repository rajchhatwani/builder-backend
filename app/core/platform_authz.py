"""The builder's own permission rules, as data, with no web framework in sight.

Three questions, three tables:
  1. Which project role does this request need?        -> required_member_role()
  2. Which API-token scope does this request need?     -> required_scope()
  3. What may each platform role do in the admin console? -> ADMIN_PERMISSIONS

A person's project role is looked up per request from `project_members`; nothing here trusts a
claim inside a token. Every deny is the default: a role or scope not named below gets nothing.
"""

from app.models.enums import MemberRole, PlatformRole

SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPE_GENERATE = "generate"
# MCP endpoint scopes (WP6).
SCOPE_MCP_READ = "mcp:read"
SCOPE_MCP_WRITE = "mcp:write"
SCOPE_MCP_GENERATE = "mcp:generate"
VALID_SCOPES = frozenset(
    {SCOPE_READ, SCOPE_WRITE, SCOPE_GENERATE, SCOPE_MCP_READ, SCOPE_MCP_WRITE, SCOPE_MCP_GENERATE}
)

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# (method or "*", route template or template prefix ending in "/") -> role needed.
_OWNER_ONLY: tuple[tuple[str, str], ...] = (
    ("DELETE", "/projects/{project_id}"),
    ("POST", "/projects/{project_id}/members"),
    ("PATCH", "/projects/{project_id}/members/"),
    ("DELETE", "/projects/{project_id}/members/"),
    # MCP access grant: only an owner may enable/disable MCP for a member.
    ("PATCH", "/projects/{project_id}/members/{user_id}/mcp"),
    # Project-scoped token management: owner sees and revokes pinned tokens.
    ("GET", "/projects/{project_id}/tokens"),
    ("DELETE", "/projects/{project_id}/tokens/"),
    # Credentials for e-mail / SMS providers: the most sensitive thing the builder stores.
    ("PUT", "/projects/{project_id}/auth/secrets"),
)

# Routes that are about no project at all: any signed-in, active person may call them.
UNSCOPED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/projects"), ("GET", "/projects")}
)

# POST routes that only compute an answer and change nothing: a viewer may call them.
_READ_ONLY_POSTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/projects/{project_id}/authorization/simulate"),
        ("POST", "/projects/{project_id}/authorization/recommend"),
        ("POST", "/projects/{project_id}/deployment/plan"),
        ("POST", "/projects/{project_id}/documents/preview"),
    }
)


def _matches(method: str, template: str, rule: tuple[str, str]) -> bool:
    rule_method, rule_path = rule
    if rule_method not in ("*", method):
        return False
    return template == rule_path or (rule_path.endswith("/") and template.startswith(rule_path))


def required_member_role(method: str, template: str) -> MemberRole:
    """Viewer for reads, editor for changes, owner for the few things only an owner may do."""
    method = method.upper()
    if any(_matches(method, template, rule) for rule in _OWNER_ONLY):
        return MemberRole.owner
    if (method, template) in _READ_ONLY_POSTS:
        return MemberRole.viewer
    return MemberRole.viewer if method in _READ_METHODS else MemberRole.editor


def required_scope(method: str, template: str) -> str:
    if "/generate/" in template or template.startswith("/generations/"):
        return SCOPE_GENERATE
    if (method.upper(), template) in _READ_ONLY_POSTS:
        return SCOPE_READ
    return SCOPE_READ if method.upper() in _READ_METHODS else SCOPE_WRITE


def scopes_allow(granted: frozenset[str], needed: str) -> bool:
    """`write` includes `read`; `generate` is separate because a zip leaves the platform."""
    if needed in granted:
        return True
    return needed == SCOPE_READ and SCOPE_WRITE in granted


# -- admin console ----------------------------------------------------------------------

ADMIN_PERMISSIONS: dict[PlatformRole, frozenset[str]] = {
    PlatformRole.customer: frozenset(),
    PlatformRole.platform_support: frozenset(
        {"users:read", "projects:read", "audit:read", "stats:read", "settings:read"}
    ),
    PlatformRole.platform_admin: frozenset(
        {
            "users:read",
            "users:write",
            "projects:read",
            "audit:read",
            "stats:read",
            "settings:read",
        }
    ),
}


def admin_can(role: PlatformRole, permission: str) -> bool:
    return permission in ADMIN_PERMISSIONS.get(role, frozenset())
