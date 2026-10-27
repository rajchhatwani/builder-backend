"""The builder's own permission rules, as data, with no web framework in sight.

Three questions, three tables:
  1. Which project role does this request need?        -> required_member_role()
  2. Which API-token scope does this request need?     -> required_scope()
  3. What may each platform role do in the admin console? -> ADMIN_PERMISSIONS

A person's project role is looked up per request from `project_members`; nothing here trusts a
claim inside a token. Every deny is the default: a role or scope not named below gets nothing.
"""

from app.models.enums import MemberRole, OrgRole, PlatformRole

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


# -- organization routes (PLATFORM_SAAS_PLAN §5) -------------------------------------------
#
# (method, route template) -> the minimum org role. Default-deny: a /orgs/{slug} route that is
# not listed here is refused (a test walks the app's routes to keep this table complete).
# Handlers add the finer rules a flat table can't express: only an owner may create or remove
# owners, and anyone may remove themselves.

ORG_ROLE_LEVEL: dict[OrgRole, int] = {OrgRole.member: 1, OrgRole.admin: 2, OrgRole.owner: 3}

ORG_ROUTE_ROLES: dict[tuple[str, str], OrgRole] = {
    ("GET", "/orgs/{slug}"): OrgRole.member,
    ("PATCH", "/orgs/{slug}"): OrgRole.admin,
    ("DELETE", "/orgs/{slug}"): OrgRole.owner,  # requests deletion (grace period)
    ("POST", "/orgs/{slug}/deletion/cancel"): OrgRole.owner,
    ("GET", "/orgs/{slug}/members"): OrgRole.member,
    ("PATCH", "/orgs/{slug}/members/{user_id}"): OrgRole.admin,
    ("DELETE", "/orgs/{slug}/members/{user_id}"): OrgRole.member,  # self; else admin (handler)
    ("POST", "/orgs/{slug}/transfer"): OrgRole.owner,
    ("GET", "/orgs/{slug}/invitations"): OrgRole.admin,
    ("POST", "/orgs/{slug}/invitations"): OrgRole.admin,
    ("DELETE", "/orgs/{slug}/invitations/{invitation_id}"): OrgRole.admin,
    ("POST", "/orgs/{slug}/invitations/{invitation_id}/resend"): OrgRole.admin,
    ("GET", "/orgs/{slug}/projects"): OrgRole.member,
    ("POST", "/orgs/{slug}/projects/{project_id}/join"): OrgRole.admin,
    ("POST", "/orgs/{slug}/projects/{project_id}/transfer"): OrgRole.owner,
    ("GET", "/orgs/{slug}/plan"): OrgRole.member,
    ("POST", "/orgs/{slug}/billing/checkout"): OrgRole.admin,
    ("POST", "/orgs/{slug}/billing/portal"): OrgRole.admin,
    ("GET", "/orgs/{slug}/audit"): OrgRole.admin,
    # Enterprise SSO (§8 "SSO & SCIM", admins). Handlers also refuse API tokens.
    ("GET", "/orgs/{slug}/sso"): OrgRole.admin,
    ("PUT", "/orgs/{slug}/sso"): OrgRole.admin,
    ("DELETE", "/orgs/{slug}/sso"): OrgRole.admin,
    ("POST", "/orgs/{slug}/sso/activate"): OrgRole.admin,
    ("POST", "/orgs/{slug}/sso/deactivate"): OrgRole.admin,
    ("POST", "/orgs/{slug}/sso/domains"): OrgRole.admin,
    ("POST", "/orgs/{slug}/sso/domains/{domain}/verify"): OrgRole.admin,
    ("DELETE", "/orgs/{slug}/sso/domains/{domain}"): OrgRole.admin,
    ("POST", "/orgs/{slug}/sso/test"): OrgRole.admin,
    ("POST", "/orgs/{slug}/sso/check"): OrgRole.admin,
    # SCIM 2.0 setup (§8 "SSO & SCIM", admins). Handlers also refuse API tokens; mapping a
    # group to the owner role needs an owner (handler).
    ("GET", "/orgs/{slug}/scim"): OrgRole.admin,
    ("POST", "/orgs/{slug}/scim/token"): OrgRole.admin,
    ("PATCH", "/orgs/{slug}/scim"): OrgRole.admin,
    ("DELETE", "/orgs/{slug}/scim"): OrgRole.admin,
    # §8 Security policies (admins). The PATCH handler also refuses API tokens.
    ("GET", "/orgs/{slug}/policies"): OrgRole.admin,
    ("PATCH", "/orgs/{slug}/policies"): OrgRole.admin,
}


# Destructive and owner-level org actions need a signed-in session: a personal access token
# (script, CI, MCP client) can read and write ordinary data but never delete the org, change who
# belongs to it or who owns it, or open the billing flow.
ORG_ROUTES_SESSION_ONLY: frozenset[tuple[str, str]] = frozenset(
    {
        ("DELETE", "/orgs/{slug}"),
        ("POST", "/orgs/{slug}/deletion/cancel"),
        ("PATCH", "/orgs/{slug}/members/{user_id}"),
        ("DELETE", "/orgs/{slug}/members/{user_id}"),
        ("POST", "/orgs/{slug}/transfer"),
        ("POST", "/orgs/{slug}/projects/{project_id}/transfer"),
        ("POST", "/orgs/{slug}/billing/checkout"),
        ("POST", "/orgs/{slug}/billing/portal"),
    }
)


# While an org waits for deletion, every route is blocked (423) except these, so members can
# see what's happening and an owner can revoke the request.
ORG_ROUTES_OPEN_DURING_DELETION: frozenset[tuple[str, str]] = frozenset(
    {("GET", "/orgs/{slug}"), ("POST", "/orgs/{slug}/deletion/cancel")}
)


# When an org requires MFA (§4.4), a member whose session has no second factor is refused
# everywhere in it (403 `org_mfa_required`) except these: the org page, so the UI can say why,
# and leaving the org.
ORG_ROUTES_OPEN_WITHOUT_MFA: frozenset[tuple[str, str]] = frozenset(
    {("GET", "/orgs/{slug}"), ("DELETE", "/orgs/{slug}/members/{user_id}")}
)


def required_org_role(method: str, template: str) -> OrgRole | None:
    """None means the route is not listed: refuse it."""
    return ORG_ROUTE_ROLES.get((method.upper(), template))


def org_role_allows(role: OrgRole, needed: OrgRole) -> bool:
    return ORG_ROLE_LEVEL[role] >= ORG_ROLE_LEVEL[needed]


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
