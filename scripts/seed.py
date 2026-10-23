"""Load demo projects into a running Backend Builder through its public API.

    python scripts/seed.py                      # against http://localhost:8000
    python scripts/seed.py --base-url http://localhost:8000 --reset
    docker compose exec api python /app/scripts/seed.py

It creates six projects, each of which validates and can be downloaded as a zip:

  helpdesk  entities + relations + email/SMS sign-in, roles, custom registration fields, invite
            only roles and every kind of permission (roles, owner, role_scoped, custom_filter)
  vault     RS256 tokens and refresh tokens in Redis
  bookshop  a plain CRUD backend with a many-to-many relation and no auth
  workspace multi-tenant: sign-up creates a tenant, invitations join one, rows are tenant-scoped
  sso-hub   Keycloak that ships with the project: Google + Microsoft Entra ID logins, MFA, roles
  sso-portal a second platform that trusts sso-hub's Keycloak realm (single sign-on across projects)

Running it again skips projects that already exist (by slug); --reset recreates them. Standard
library only, so it runs anywhere Python 3.10+ does. Credentials are not seeded: the generated
projects read them from environment variables.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

SMTP = {
    "host": "smtp.example.com",
    "port": 587,
    "use_tls": True,
    "from_email": "noreply@example.com",
    "from_name": "Demo",
}
ALL_OPS = ["list", "get", "head", "create", "replace", "update", "delete"]


class Api:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise SystemExit(f"{method} {path} -> {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"cannot reach {self.base}: {exc.reason}") from exc
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self.call("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.call("POST", path, body)

    def patch(self, path: str, body: Any) -> Any:
        return self.call("PATCH", path, body)

    def put(self, path: str, body: Any) -> Any:
        return self.call("PUT", path, body)

    def delete(self, path: str) -> Any:
        return self.call("DELETE", path)


def field(name: str, type_: str, *, required: bool = True, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "type": type_,
        "required": required,
        "unique": False,
        "indexed": False,
        "default": None,
        "max_length": None,
        "min_value": None,
        "max_value": None,
        "enum_values": None,
    }
    payload.update(extra)
    return payload


class Builder:
    """Creates one project, step by step, remembering the ids it needs."""

    def __init__(self, api: Api, name: str, slug: str, description: str) -> None:
        project = api.post("/projects", {"name": name, "slug": slug, "description": description})
        self.api, self.id, self.slug = api, project["id"], slug
        self.entities: dict[str, str] = {}

    def entity(
        self,
        name: str,
        fields: list[dict[str, Any]],
        *,
        operations: list[str] | None = None,
        filterable: list[str] | None = None,
        sortable: list[str] | None = None,
        searchable: list[str] | None = None,
        soft_delete: bool = False,
    ) -> None:
        created = self.api.post(f"/projects/{self.id}/entities", {"name": name})
        self.entities[name] = created["id"]
        for f in fields:
            self.api.post(f"/entities/{created['id']}/fields", f)
        self.api.patch(
            f"/entities/{created['id']}",
            {
                "options": {
                    "operations": operations or ALL_OPS,
                    "filterable": filterable or [],
                    "sortable": sortable or [],
                    "searchable": searchable or [],
                    "default_page_size": 20,
                    "max_page_size": 100,
                    "soft_delete": soft_delete,
                }
            },
        )

    def relation(
        self, kind: str, from_: str, to: str, from_name: str, to_name: str, **extra: Any
    ) -> None:
        self.api.post(
            f"/projects/{self.id}/relations",
            {
                "kind": kind,
                "from_entity_id": self.entities[from_],
                "to_entity_id": self.entities[to],
                "from_name": from_name,
                "to_name": to_name,
                "on_delete": extra.get("on_delete", "cascade"),
                "required": extra.get("required", False),
            },
        )

    def auth(self, **config: Any) -> None:
        self.api.post(f"/projects/{self.id}/auth", config)

    def role(self, name: str, label: str, **flags: Any) -> None:
        self.api.post(f"/projects/{self.id}/roles", {"name": name, "label": label, **flags})

    def keycloak(self, enable: bool = True, **settings: Any) -> None:
        """Save the Keycloak settings and, unless told not to, switch the project to Keycloak."""
        self.api.put(f"/projects/{self.id}/keycloak", settings)
        if enable:
            self.api.post(f"/projects/{self.id}/keycloak/enable", {"confirm": True})

    def custom_field(self, name: str, label: str, type_: str, **extra: Any) -> None:
        self.api.post(
            f"/projects/{self.id}/auth/custom-fields",
            {"name": name, "label": label, "type": type_, **extra},
        )

    def permissions(self, entries: list[tuple[str, str, list[str], dict[str, Any]]]) -> None:
        self.api.post(
            f"/projects/{self.id}/permissions",
            {
                "permissions": [
                    {
                        "entity_id": self.entities[entity],
                        "operation": op,
                        "roles": roles,
                        "row_rule": rule.get("row_rule"),
                        "custom_filter_field": rule.get("field"),
                        "custom_filter_value": rule.get("value"),
                    }
                    for entity, op, roles, rule in entries
                ]
            },
        )

    def report(self) -> bool:
        result = self.api.post(f"/projects/{self.id}/validate")
        if result["valid"]:
            print(
                f"  valid: ready to generate ({self.api.base}/projects/{self.id}/generate/download)"
            )
        else:
            for issue in result["issues"]:
                print(f"  PROBLEM {issue['path']}: {issue['message']}")
        return bool(result["valid"])


def helpdesk(api: Api) -> Builder:
    b = Builder(
        api,
        "Helpdesk",
        "helpdesk",
        "Support desk: knowledge base articles and tickets, with roles, invitations and row rules.",
    )
    b.entity(
        "Category",
        [
            field("name", "string", unique=True, max_length=80),
            field("slug", "string", max_length=80),
        ],
        filterable=["slug"],
        sortable=["name"],
    )
    b.entity(
        "Article",
        [
            field("title", "string", max_length=160),
            field("body", "text"),
            field("status", "enum", enum_values=["draft", "published"], default="draft"),
            field("views", "integer", required=False, default=0, min_value=0),
        ],
        filterable=["status"],
        sortable=["title", "views", "created_at"],
        searchable=["title", "body"],
    )
    b.entity(
        "Ticket",
        [
            field("subject", "string", max_length=160),
            field("description", "text"),
            field("priority", "enum", enum_values=["low", "normal", "high"], default="normal"),
            field("state", "enum", enum_values=["open", "closed"], default="open"),
        ],
        filterable=["priority", "state"],
        sortable=["created_at", "priority"],
        searchable=["subject"],
    )
    b.entity("Comment", [field("body", "text")], operations=["list", "get", "create", "delete"])
    b.relation("one_to_many", "Category", "Article", "articles", "category")
    b.relation("one_to_many", "Ticket", "Comment", "comments", "ticket")

    b.auth(
        app_name="Helpdesk",
        app_url="http://localhost:3000",
        smtp_config=SMTP,
        sms_otp_enabled=True,
        sms_provider="twilio",
        sms_config={"from_number": "+14155550100"},
        email_verification_required=True,
        invite_only=False,
        deletion_mode="soft",
        access_token_ttl_minutes=30,
        login_rate_limit="5/15minutes",
    )
    b.role("admin", "Administrator", inherits_from=None, position=0)
    b.role("staff", "Support staff", position=1)
    b.role("customer", "Customer", is_default=True, position=2)
    b.role("subscriber", "Newsletter subscriber", self_assignable=True, position=3)
    b.role("vip", "VIP customer", invite_only=True, position=4)
    b.custom_field("full_name", "Full name", "string", required=True, max_length=80)
    b.custom_field("company", "Company", "string", indexed=True, max_length=80)
    b.custom_field("plan", "Plan", "enum", enum_values=["free", "pro"], default_value="free")
    b.permissions(
        [
            # Articles: anyone reads published ones, staff write, admins delete.
            (
                "Article",
                "list",
                [],
                {"row_rule": "custom_filter", "field": "status", "value": "published"},
            ),
            (
                "Article",
                "get",
                [],
                {"row_rule": "custom_filter", "field": "status", "value": "published"},
            ),
            ("Article", "create", ["staff", "admin"], {}),
            ("Article", "update", ["staff", "admin"], {}),
            ("Article", "delete", ["admin"], {}),
            # Tickets: customers see and delete their own; admins see all tickets.
            ("Ticket", "create", ["customer", "staff", "admin"], {}),
            ("Ticket", "list", ["customer", "staff", "admin"], {"row_rule": "role_scoped"}),
            ("Ticket", "get", ["customer", "staff", "admin"], {"row_rule": "role_scoped"}),
            ("Ticket", "update", ["staff", "admin"], {}),
            ("Ticket", "delete", ["customer", "admin"], {"row_rule": "owner"}),
            # Comments: signed-in users write them, the author or an admin removes them.
            ("Comment", "list", ["customer", "staff", "admin"], {}),
            ("Comment", "create", ["customer", "staff", "admin"], {}),
            ("Comment", "delete", ["customer", "staff", "admin"], {"row_rule": "role_scoped"}),
        ]
    )
    return b


def vault(api: Api) -> Builder:
    b = Builder(
        api,
        "Vault",
        "vault",
        "Private notes API: RS256 tokens (verifiable with the public key), Redis sessions.",
    )
    b.entity(
        "Secret",
        [field("label", "string", max_length=80), field("value", "text")],
        operations=["list", "get", "create", "update", "delete"],
        sortable=["label", "created_at"],
        searchable=["label"],
    )
    b.auth(
        app_name="Vault",
        app_url="http://localhost:3000",
        smtp_config={**SMTP, "from_name": "Vault"},
        email_magic_link_enabled=True,
        email_verification_required=True,
        jwt_algorithm="RS256",
        token_store="redis",
        deletion_mode="hard",
        refresh_token_ttl_days=14,
    )
    b.role("admin", "Administrator", position=0)
    b.role("member", "Member", is_default=True, position=1)
    b.permissions(
        [
            ("Secret", "create", ["member", "admin"], {}),
            ("Secret", "list", ["member", "admin"], {"row_rule": "owner"}),
            ("Secret", "get", ["member", "admin"], {"row_rule": "owner"}),
            ("Secret", "update", ["member", "admin"], {"row_rule": "owner"}),
            ("Secret", "delete", ["member", "admin"], {"row_rule": "owner"}),
        ]
    )
    return b


def bookshop(api: Api) -> Builder:
    b = Builder(
        api,
        "Bookshop",
        "bookshop",
        "Plain CRUD backend (no auth): authors, books and a many-to-many to tags.",
    )
    b.entity(
        "Author",
        [field("name", "string", max_length=120), field("born", "date", required=False)],
        sortable=["name"],
        searchable=["name"],
    )
    b.entity(
        "Book",
        [
            field("title", "string", max_length=200),
            field("isbn", "string", unique=True, max_length=20),
            field("price", "decimal", min_value=0),
            field("in_stock", "boolean", default=True, required=False),
        ],
        filterable=["in_stock"],
        sortable=["title", "price"],
        searchable=["title", "isbn"],
        soft_delete=True,
    )
    b.entity("Tag", [field("name", "string", unique=True, max_length=40)])
    b.relation(
        "one_to_many", "Author", "Book", "books", "author", on_delete="restrict", required=True
    )
    b.relation("many_to_many", "Book", "Tag", "tags", "books")
    return b


def workspace(api: Api) -> Builder:
    b = Builder(
        api,
        "Workspace",
        "workspace",
        "Multi-tenant task tracker: every sign-up creates a tenant, invitations join one.",
    )
    b.entity(
        "Announcement",
        [field("title", "string", max_length=120), field("body", "text", required=False)],
        sortable=["created_at"],
    )
    b.entity(
        "Task",
        [
            field("title", "string", max_length=120),
            field("done", "boolean", default=False, required=False),
        ],
        filterable=["done"],
        sortable=["created_at"],
        searchable=["title"],
    )
    b.auth(
        app_name="Workspace",
        app_url="http://localhost:3000",
        smtp_config={**SMTP, "from_name": "Workspace"},
        multi_tenant=True,
        email_verification_required=True,
        invite_only=False,
    )
    b.role("admin", "Tenant admin", position=0)
    b.role("member", "Member", is_default=True, position=1)
    b.permissions(
        [
            # Announcements: everyone in the tenant reads them, admins post them.
            ("Announcement", "list", [], {"row_rule": "tenant"}),
            ("Announcement", "create", ["admin"], {}),
            # Tasks: tenant-scoped; members see their own tasks, admins see the tenant's.
            ("Task", "create", ["member", "admin"], {"row_rule": "tenant"}),
            ("Task", "list", ["member", "admin"], {"row_rule": "role_scoped"}),
            ("Task", "delete", ["member", "admin"], {"row_rule": "owner"}),
        ]
    )
    return b


def sso_hub(api: Api) -> Builder:
    b = Builder(
        api,
        "SSO Hub",
        "sso-hub",
        "Keycloak ships with the project: Google and Entra ID logins, MFA, roles from Keycloak.",
    )
    b.entity(
        "Note",
        [field("title", "string", max_length=120), field("body", "text", required=False)],
        sortable=["created_at"],
    )
    b.entity("Report", [field("name", "string", max_length=80)])
    b.role("admin", "Admin", position=0)
    b.role("member", "Member", is_default=True, position=1)
    b.keycloak(
        mode="own",
        realm="company",
        redirect_uris=["http://localhost:3000/"],
        mfa="optional",
        identity_providers=[
            {"alias": "google", "type": "google", "display_name": "Google", "client_id": "demo"},
            {
                "alias": "work",
                "type": "microsoft",
                "display_name": "Work account",
                "client_id": "demo",
                "tenant_id": "11111111-2222-3333-4444-555555555555",
            },
        ],
    )
    b.api.patch(
        f"/projects/{b.id}/auth",
        {"app_name": "SSO Hub", "smtp_config": {**SMTP, "from_name": "SSO Hub"}},
    )
    b.api.patch(f"/projects/{b.id}/auth", {"email_verification_required": True})
    b.permissions(
        [
            ("Note", "list", ["member", "admin"], {"row_rule": "role_scoped"}),
            ("Note", "create", ["member", "admin"], {}),
            ("Report", "list", ["admin"], {}),
        ]
    )
    return b


def sso_portal(api: Api) -> Builder:
    hub = next(
        (p for p in api.get("/projects?limit=200&offset=0")["items"] if p["slug"] == "sso-hub"),
        None,
    )
    if hub is None:
        raise SystemExit("seed sso-hub first: sso-portal trusts its Keycloak realm")
    b = Builder(
        api,
        "SSO Portal",
        "sso-portal",
        "A second platform on the same Keycloak realm as SSO Hub: one login for both.",
    )
    b.entity("Ticket", [field("subject", "string", max_length=120)], sortable=["created_at"])
    b.role("admin", "Admin", position=0)
    b.role("agent", "Agent", is_default=True, position=1)
    b.keycloak(
        mode="shared",
        source_project_id=hub["id"],
        redirect_uris=["http://localhost:3001/"],
    )
    b.permissions(
        [
            ("Ticket", "list", ["agent", "admin"], {"row_rule": "owner"}),
            ("Ticket", "create", ["agent", "admin"], {}),
            ("Ticket", "delete", ["admin"], {}),
        ]
    )
    return b


PROJECTS = {
    "helpdesk": helpdesk,
    "vault": vault,
    "bookshop": bookshop,
    "workspace": workspace,
    "sso-hub": sso_hub,
    "sso-portal": sso_portal,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--reset", action="store_true", help="delete and recreate existing demos")
    parser.add_argument("only", nargs="*", choices=list(PROJECTS), help="seed only these")
    args = parser.parse_args()

    api = Api(args.base_url)
    api.get("/health")
    existing = {p["slug"]: p for p in api.get("/projects?limit=200&offset=0")["items"]}
    ok = True
    for slug, build in PROJECTS.items():
        if args.only and slug not in args.only:
            continue
        print(f"{slug}:")
        if slug in existing:
            if not args.reset:
                print("  already exists, skipping (use --reset to recreate)")
                continue
            api.delete(f"/projects/{existing[slug]['id']}")
            print("  removed the old one")
        builder = build(api)
        ok = builder.report() and ok
    print("\nOpen the dashboard (http://localhost:5173) to explore them.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
