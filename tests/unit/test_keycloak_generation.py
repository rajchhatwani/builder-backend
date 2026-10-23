"""What the generator emits for a Keycloak project: the realm, the compose files, the env file,
the register script and the guarantee that no secret ever lands in the output."""

import json
import os
import subprocess
import sys
import threading
import uuid
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.generator.features.keycloak.module import KEYCLOAK_IMAGE_TAG, idp_secret_env
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def files_for(data: dict[str, Any]) -> dict[str, str]:
    return generate(Spec.model_validate(data))


@pytest.fixture(scope="module")
def own() -> dict[str, str]:
    return files_for(load("keycloak_own"))


@pytest.fixture(scope="module")
def shared() -> dict[str, str]:
    return files_for(load("keycloak_shared"))


def realm_of(files: dict[str, str]) -> dict[str, Any]:
    realm: dict[str, Any] = json.loads(files["keycloak/realm.json"])
    return realm


def client(realm: dict[str, Any], client_id: str) -> dict[str, Any]:
    return next(c for c in realm["clients"] if c["clientId"] == client_id)


# --- which files exist --------------------------------------------------------------------


def test_own_mode_ships_the_realm_compose_services_and_register_script(
    own: dict[str, str],
) -> None:
    for path in ("keycloak/realm.json", "keycloak/clients.json", "scripts/keycloak_register.py"):
        assert path in own
    compose = own["docker-compose.yml"]
    assert "  keycloak:\n" in compose
    assert "  keycloak_db:\n" in compose
    assert "./keycloak/realm.json:/opt/keycloak/data/import/realm.json:ro" in compose


def test_shared_mode_ships_no_keycloak_server(shared: dict[str, str]) -> None:
    assert "keycloak/realm.json" not in shared
    assert "keycloak/clients.json" in shared
    assert "scripts/keycloak_register.py" in shared
    compose = shared["docker-compose.yml"]
    assert "  keycloak:" not in compose and "keycloak_db" not in compose
    assert "KEYCLOAK_PUBLIC_URL: ${KEYCLOAK_PUBLIC_URL:?" in compose


def test_builtin_projects_get_no_keycloak_files() -> None:
    files = files_for(load("shop_auth"))
    assert not [p for p in files if "keycloak" in p]
    assert "KEYCLOAK" not in files["docker-compose.yml"]


def test_a_disabled_keycloak_block_emits_nothing() -> None:
    data = load("keycloak_own")
    data["auth"]["provider"] = "builtin"
    # Built-in auth then needs its own settings; only the absence of Keycloak files matters here.
    data["auth"]["smtp"]["host"] = "smtp.example.com"
    data["auth"]["app_url"] = "https://hub.example.com"
    data["auth"]["registration"] = {"email_verification_required": False}
    data["auth"]["password_reset"] = {"email_magic_link": False}
    data["auth"]["roles"] = [{"name": "admin", "label": "Admin"}]
    data["auth"]["permissions"] = []
    files = files_for(data)
    assert not [p for p in files if p.startswith("keycloak/")]
    assert "auth_provider_lock" in files["alembic/versions/0002_auth.py"]


# --- the realm ----------------------------------------------------------------------------


def test_realm_basics_and_hardening(own: dict[str, str]) -> None:
    realm = realm_of(own)
    assert realm["realm"] == "hub" and realm["enabled"] is True
    assert realm["sslRequired"] == "external"
    assert realm["bruteForceProtected"] is True and realm["permanentLockout"] is False
    assert realm["failureFactor"] == 5
    assert realm["passwordPolicy"].startswith("length(12) and notUsername and notEmail")
    assert "passwordHistory(5)" in realm["passwordPolicy"]
    assert realm["revokeRefreshToken"] is True and realm["refreshTokenMaxReuse"] == 0
    assert realm["defaultSignatureAlgorithm"] == "RS256"
    assert realm["accessTokenLifespan"] == 15 * 60
    assert realm["ssoSessionIdleTimeout"] == 30 * 60
    assert realm["ssoSessionMaxLifespan"] == 10 * 3600
    assert realm["eventsEnabled"] and realm["adminEventsEnabled"]
    assert realm["eventsExpiration"] == 90 * 86400
    assert realm["duplicateEmailsAllowed"] is False and realm["rememberMe"] is False
    headers = realm["browserSecurityHeaders"]
    assert headers["xFrameOptions"] == "SAMEORIGIN"
    assert "max-age" in headers["strictTransportSecurity"]
    assert "users" not in realm  # no default accounts, no default passwords


def test_realm_follows_the_auth_settings(own: dict[str, str]) -> None:
    realm = realm_of(own)
    assert realm["verifyEmail"] is True
    assert realm["resetPasswordAllowed"] is True
    assert realm["registrationAllowed"] is True
    smtp = realm["smtpServer"]
    assert (smtp["host"], smtp["port"], smtp["from"]) == (
        "smtp.example.com",
        "587",
        "noreply@hub.example.com",
    )
    assert smtp["user"] == "${SMTP_USERNAME}" and smtp["password"] == "${SMTP_PASSWORD}"
    assert smtp["starttls"] == "true" and smtp["ssl"] == "false"


def test_invite_only_turns_self_registration_off(shared: dict[str, str]) -> None:
    data = load("keycloak_own")
    data["auth"]["registration"]["invite_only"] = True
    realm = realm_of(files_for(data))
    assert realm["registrationAllowed"] is False


def test_without_smtp_there_is_no_password_reset() -> None:
    data = load("keycloak_own")
    data["auth"]["smtp"] = None
    data["auth"]["registration"] = {"email_verification_required": False}
    realm = realm_of(files_for(data))
    assert realm["resetPasswordAllowed"] is False and "smtpServer" not in realm
    assert realm["verifyEmail"] is False


def test_implicit_tls_smtp_port() -> None:
    data = load("keycloak_own")
    data["auth"]["smtp"]["port"] = 465
    smtp = realm_of(files_for(data))["smtpServer"]
    assert smtp["ssl"] == "true" and smtp["starttls"] == "false"


def test_clients_are_locked_down(own: dict[str, str]) -> None:
    realm = realm_of(own)
    api = client(realm, "hub-api")
    assert api["publicClient"] is False
    for flow in (
        "standardFlowEnabled",
        "implicitFlowEnabled",
        "directAccessGrantsEnabled",
        "serviceAccountsEnabled",
    ):
        assert api[flow] is False, flow

    for client_id in ("hub-web", "hub-web-docs"):
        c = client(realm, client_id)
        assert c["publicClient"] is True and "secret" not in c
        assert c["standardFlowEnabled"] is True
        assert c["implicitFlowEnabled"] is False and c["directAccessGrantsEnabled"] is False
        assert c["serviceAccountsEnabled"] is False and c["fullScopeAllowed"] is False
        assert c["attributes"]["pkce.code.challenge.method"] == "S256"
        mapper = c["protocolMappers"][0]
        assert mapper["protocolMapper"] == "oidc-audience-mapper"
        assert mapper["config"]["included.client.audience"] == "hub-api"


def test_redirect_uris_are_exact_and_origins_are_derived(own: dict[str, str]) -> None:
    web = client(realm_of(own), "hub-web")
    assert web["redirectUris"] == [
        "http://localhost:3000/",
        "https://app.example.com/auth/callback",
    ]
    assert web["webOrigins"] == ["http://localhost:3000", "https://app.example.com"]
    assert "*" not in json.dumps(web["redirectUris"] + web["webOrigins"])
    assert web["attributes"]["post.logout.redirect.uris"] == (
        "http://localhost:3000/##https://app.example.com/auth/callback"
    )


def test_swagger_client_returns_to_the_api(own: dict[str, str]) -> None:
    docs = client(realm_of(own), "hub-web-docs")
    assert docs["redirectUris"] == ["${API_PUBLIC_URL}/docs/oauth2-redirect"]
    assert docs["webOrigins"] == ["${API_PUBLIC_URL}"]


def test_roles_are_client_roles_of_the_api_client(own: dict[str, str]) -> None:
    realm = realm_of(own)
    assert set(realm["roles"]) == {"client"}
    assert [r["name"] for r in realm["roles"]["client"]["hub-api"]] == ["admin", "editor", "member"]
    mappings = realm["clientScopeMappings"]["hub-api"]
    assert {m["client"] for m in mappings} == {"hub-web", "hub-web-docs"}
    for m in mappings:
        assert m["roles"] == ["admin", "editor", "member"]


def test_identity_providers(own: dict[str, str]) -> None:
    providers = {p["alias"]: p for p in realm_of(own)["identityProviders"]}
    assert set(providers) == {"corp", "gh", "google", "work"}

    google = providers["google"]
    assert google["providerId"] == "google" and google["trustEmail"] is True
    assert google["config"]["hostedDomain"] == "example.com"
    assert google["config"]["clientId"] == "1234.apps.googleusercontent.com"

    work = providers["work"]
    tenant = "11111111-2222-3333-4444-555555555555"
    assert work["providerId"] == "oidc" and work["trustEmail"] is False
    assert work["config"]["issuer"] == f"https://login.microsoftonline.com/{tenant}/v2.0"
    assert work["config"]["authorizationUrl"].startswith(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/"
    )
    assert work["config"]["validateSignature"] == "true" and work["config"]["pkceMethod"] == "S256"

    assert providers["gh"]["providerId"] == "github" and providers["gh"]["trustEmail"] is False
    corp = providers["corp"]["config"]
    assert corp["jwksUrl"] == "https://sso.example.com/keys"
    assert corp["userInfoUrl"] == "https://sso.example.com/userinfo"


def test_client_secrets_are_placeholders_never_values(own: dict[str, str]) -> None:
    for provider in realm_of(own)["identityProviders"]:
        secret = provider["config"]["clientSecret"]
        assert secret == "${" + idp_secret_env(provider["alias"]) + "}"
    assert idp_secret_env("my-idp") == "KC_IDP_MY_IDP_CLIENT_SECRET"


@pytest.mark.parametrize("mfa", ["off", "optional", "required"])
def test_mfa_modes(mfa: str) -> None:
    data = load("keycloak_own")
    data["auth"]["keycloak"]["mfa"] = mfa
    realm = realm_of(files_for(data))
    actions = realm.get("requiredActions")
    if mfa == "optional":
        assert actions is None  # Keycloak's own defaults
        return
    assert actions is not None
    by_alias = {a["alias"]: a for a in actions}
    # Naming any action replaces Keycloak's list, so the ordinary ones must all still be there.
    for needed in ("UPDATE_PASSWORD", "VERIFY_EMAIL", "UPDATE_PROFILE", "VERIFY_PROFILE"):
        assert by_alias[needed]["enabled"] is True and by_alias[needed]["defaultAction"] is False
    assert by_alias["CONFIGURE_TOTP"]["enabled"] is (mfa == "required")
    assert by_alias["CONFIGURE_TOTP"]["defaultAction"] is (mfa == "required")


def test_realm_settings_come_from_the_spec() -> None:
    data = load("keycloak_own")
    kc = data["auth"]["keycloak"]
    kc.update(password_min_length=16, session_idle_minutes=15, session_max_hours=2)
    kc.update(audit_retention_days=30)
    data["auth"]["access_token_ttl_minutes"] = 5
    realm = realm_of(files_for(data))
    assert realm["passwordPolicy"].startswith("length(16)")
    assert (realm["ssoSessionIdleTimeout"], realm["ssoSessionMaxLifespan"]) == (900, 7200)
    assert realm["eventsExpiration"] == 30 * 86400
    assert realm["accessTokenLifespan"] == 300


def test_output_is_deterministic(own: dict[str, str]) -> None:
    assert files_for(load("keycloak_own")) == own
    assert list(files_for(load("keycloak_own"))) == sorted(own)


# --- compose and env ----------------------------------------------------------------------


def test_compose_is_pinned_and_requires_its_secrets(own: dict[str, str]) -> None:
    compose = own["docker-compose.yml"]
    assert f"quay.io/keycloak/keycloak:{KEYCLOAK_IMAGE_TAG}" in compose
    assert "latest" not in compose
    for required in (
        "KEYCLOAK_DB_PASSWORD",
        "KC_BOOTSTRAP_ADMIN_USERNAME",
        "KC_BOOTSTRAP_ADMIN_PASSWORD",
        "KC_IDP_GOOGLE_CLIENT_SECRET",
        "KC_IDP_WORK_CLIENT_SECRET",
        "KC_IDP_GH_CLIENT_SECRET",
        "KC_IDP_CORP_CLIENT_SECRET",
    ):
        assert f"${{{required}:?" in compose, required
    assert "KEYCLOAK_PUBLIC_URL" in compose
    assert "KEYCLOAK_INTERNAL_URL: http://keycloak:8080" in compose
    assert 'command: ["start", "--import-realm"]' in compose
    assert "start-dev" not in compose
    # The management port (health, metrics) stays inside the compose network.
    assert "9000:" not in compose and '"${KEYCLOAK_PORT:-8081}:8080"' in compose
    assert "keycloak:\n        condition: service_healthy" in compose


def test_compose_has_no_default_passwords_for_keycloak(own: dict[str, str]) -> None:
    compose = own["docker-compose.yml"]
    keycloak_part = compose[compose.index("  keycloak_db:") :]
    assert "POSTGRES_PASSWORD: ${KEYCLOAK_DB_PASSWORD:?" in keycloak_part
    for weak in ("admin\n", "password\n", "keycloak\n"):
        assert f"PASSWORD: {weak}" not in keycloak_part


def test_env_example_lists_every_variable_without_values(own: dict[str, str]) -> None:
    env = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in own[".env.example"].splitlines()
        if "=" in line and not line.startswith("#")
    }
    for name in (
        "KEYCLOAK_DB_PASSWORD",
        "KC_BOOTSTRAP_ADMIN_PASSWORD",
        "KC_IDP_GOOGLE_CLIENT_SECRET",
        "SMTP_PASSWORD",
        "AUTH_ALLOW_PROVIDER_SWITCH",
    ):
        assert name in env, name
    for secret in ("KEYCLOAK_DB_PASSWORD", "KC_BOOTSTRAP_ADMIN_PASSWORD", "SMTP_PASSWORD"):
        assert env[secret] == ""
    assert env["AUTH_ALLOW_PROVIDER_SWITCH"] == "false"


def test_no_jwt_secret_is_asked_for(own: dict[str, str]) -> None:
    assert "AUTH_JWT" not in own[".env.example"] and "AUTH_JWT" not in own["docker-compose.yml"]
    assert "cryptography" in own["requirements.txt"]


def test_makefile_tests_do_not_start_keycloak(own: dict[str, str]) -> None:
    make = own["Makefile"]
    assert "up -d --wait db" in make and "--no-deps" in make
    assert "KEYCLOAK_DB_PASSWORD=unused" in make


def test_readme_explains_the_setup(own: dict[str, str], shared: dict[str, str]) -> None:
    readme = own["README.md"]
    assert "/realms/hub/broker/google/endpoint" in readme
    assert "KC_IDP_GOOGLE_CLIENT_SECRET" in readme
    assert "example.com" in readme  # the Workspace domain restriction is stated
    assert "tenant `11111111-2222-3333-4444-555555555555`" in readme
    assert "TLS" in readme and "AUTH_ALLOW_PROVIDER_SWITCH" in readme
    assert "keycloak_register.py" in shared["README.md"]
    assert "does **not** start Keycloak" in shared["README.md"]


def test_nothing_secret_shaped_is_in_any_output(own: dict[str, str]) -> None:
    blob = "\n".join(own.values())
    for marker in ("BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY", "client_secret_value"):
        assert marker not in blob


# --- the register script, against a fake Keycloak --------------------------------------------


class FakeKeycloak(BaseHTTPRequestHandler):
    clients: dict[str, dict[str, Any]] = {}
    roles: dict[str, dict[str, dict[str, Any]]] = {}
    mappers: dict[str, list[dict[str, Any]]] = {}
    scope_mappings: list[tuple[str, str, list[str]]] = []
    log: list[tuple[str, str]] = []
    auth_headers: list[str | None] = []

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        raw = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length)) if length else None

    def _route(self, method: str) -> None:
        path = self.path.split("?")[0]
        FakeKeycloak.log.append((method, self.path))
        if path == "/realms/master/protocol/openid-connect/token":
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self._send(200, {"access_token": "fake-admin-token"})
        FakeKeycloak.auth_headers.append(self.headers.get("Authorization"))
        parts = path.strip("/").split("/")
        assert parts[:3] == ["admin", "realms", "hub"], path
        rest = parts[3:]
        body = self._body() if method in ("POST", "PUT") else None
        if rest == ["clients"] and method == "GET":
            wanted = self.path.split("clientId=")[1]
            return self._send(200, [c for c in self.clients.values() if c["clientId"] == wanted])
        if rest == ["clients"] and method == "POST":
            new_id = str(uuid.uuid4())
            stored = {k: v for k, v in body.items() if k != "protocolMappers"}
            self.clients[new_id] = {**stored, "id": new_id}
            self.mappers[new_id] = list(body.get("protocolMappers", []))
            return self._send(201, headers={"Location": f"/admin/realms/hub/clients/{new_id}"})
        client_id = rest[1] if len(rest) > 1 else ""
        if rest[:1] == ["clients"] and len(rest) == 2 and method == "PUT":
            self.clients[client_id] = {**body, "id": client_id}
            return self._send(204)
        tail = rest[2:]
        if tail == ["protocol-mappers", "models"]:
            if method == "GET":
                return self._send(200, self.mappers[client_id])
            self.mappers[client_id].append(body)
            return self._send(201)
        if tail == ["roles"]:
            if method == "GET":
                return self._send(200, list(self.roles.get(client_id, {}).values()))
            self.roles.setdefault(client_id, {})[body["name"]] = {**body, "id": str(uuid.uuid4())}
            return self._send(201)
        if tail[:1] == ["roles"] and method == "GET":
            found = self.roles.get(client_id, {}).get(tail[1])
            return self._send(200, found) if found else self._send(404, {"error": "no"})
        if tail[:2] == ["scope-mappings", "clients"] and method == "POST":
            FakeKeycloak.scope_mappings.append((client_id, tail[2], [r["name"] for r in body]))
            return self._send(204)
        raise AssertionError(f"unexpected {method} {self.path}")

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_PUT(self) -> None:
        self._route("PUT")


@pytest.fixture
def fake_keycloak() -> Any:
    for attr in ("clients", "roles", "mappers"):
        setattr(FakeKeycloak, attr, {})
    FakeKeycloak.scope_mappings, FakeKeycloak.log, FakeKeycloak.auth_headers = [], [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeKeycloak)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def write_project(tmp_path: Path, files: dict[str, str]) -> Path:
    for path, content in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return tmp_path


def register(root: Path, url: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    base.update(
        KEYCLOAK_PUBLIC_URL=url,
        KEYCLOAK_ADMIN_USERNAME="admin",
        KEYCLOAK_ADMIN_PASSWORD="s3cret-admin-pass",
        API_PUBLIC_URL="https://api.example.com",
    )
    base.update(env)
    return subprocess.run(
        [sys.executable, "scripts/keycloak_register.py"],
        cwd=root,
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_register_script_creates_clients_roles_and_scope_mappings(
    tmp_path: Path, fake_keycloak: str
) -> None:
    data = load("keycloak_shared")
    data["auth"]["keycloak"]["realm"] = "hub"
    root = write_project(tmp_path, files_for(data))

    result = register(root, fake_keycloak)

    assert result.returncode == 0, result.stdout + result.stderr
    created = {c["clientId"]: c for c in FakeKeycloak.clients.values()}
    assert set(created) == {"portal-api", "portal-web", "portal-web-docs"}
    docs = created["portal-web-docs"]
    # ${API_PUBLIC_URL} was filled in from the environment.
    assert docs["redirectUris"] == ["https://api.example.com/docs/oauth2-redirect"]
    assert created["portal-web"]["redirectUris"] == ["https://portal.example.com/callback"]
    api_id = created["portal-api"]["id"]
    assert set(FakeKeycloak.roles[api_id]) == {"admin", "agent"}
    mapped = {(src, dst) for src, dst, _ in FakeKeycloak.scope_mappings}
    assert mapped == {
        (created["portal-web"]["id"], api_id),
        (created["portal-web-docs"]["id"], api_id),
    }
    for mappers in (FakeKeycloak.mappers[created["portal-web"]["id"]],):
        assert [m["name"] for m in mappers] == ["api-audience"]
    # The admin password is used to get a token and then never again; it is not printed.
    assert "s3cret-admin-pass" not in result.stdout + result.stderr
    assert set(FakeKeycloak.auth_headers) == {"Bearer fake-admin-token"}


def test_register_script_can_run_again_without_duplicating_or_deleting(
    tmp_path: Path, fake_keycloak: str
) -> None:
    data = load("keycloak_shared")
    data["auth"]["keycloak"]["realm"] = "hub"
    root = write_project(tmp_path, files_for(data))
    assert register(root, fake_keycloak).returncode == 0
    before = deepcopy(FakeKeycloak.roles)
    api_id = next(i for i, c in FakeKeycloak.clients.items() if c["clientId"] == "portal-api")
    web_id = next(i for i, c in FakeKeycloak.clients.items() if c["clientId"] == "portal-web")
    # Someone tightened the client in the admin console in the meantime.
    FakeKeycloak.clients[web_id]["attributes"]["custom.setting"] = "kept"

    second = register(root, fake_keycloak)

    assert second.returncode == 0, second.stdout + second.stderr
    assert len(FakeKeycloak.clients) == 3
    assert FakeKeycloak.roles == before  # no role was re-created, so no assignment is lost
    assert FakeKeycloak.clients[web_id]["attributes"]["custom.setting"] == "kept"
    assert len(FakeKeycloak.mappers[web_id]) == 1  # the audience mapper is not added twice
    assert not [m for m, p in FakeKeycloak.log if m == "DELETE"], FakeKeycloak.log
    assert api_id in FakeKeycloak.roles


def test_register_script_adds_only_the_roles_that_are_missing(
    tmp_path: Path, fake_keycloak: str
) -> None:
    data = load("keycloak_shared")
    data["auth"]["keycloak"]["realm"] = "hub"
    assert register(write_project(tmp_path / "one", files_for(data)), fake_keycloak).returncode == 0
    api_id = next(i for i, c in FakeKeycloak.clients.items() if c["clientId"] == "portal-api")
    admin_role = dict(FakeKeycloak.roles[api_id]["admin"])
    data["auth"]["roles"].append({"name": "auditor", "label": "Auditor"})

    root = write_project(tmp_path / "two", files_for(data))
    assert register(root, fake_keycloak).returncode == 0

    assert set(FakeKeycloak.roles[api_id]) == {"admin", "agent", "auditor"}
    assert FakeKeycloak.roles[api_id]["admin"] == admin_role  # untouched, same id


def test_register_script_refuses_a_plain_http_keycloak_that_is_not_local(tmp_path: Path) -> None:
    data = load("keycloak_shared")
    data["auth"]["keycloak"]["realm"] = "hub"
    root = write_project(tmp_path, files_for(data))

    result = register(root, "http://id.example.com")

    assert result.returncode == 1
    assert "https" in result.stderr


def test_register_script_needs_credentials_and_says_so(tmp_path: Path, fake_keycloak: str) -> None:
    data = load("keycloak_shared")
    data["auth"]["keycloak"]["realm"] = "hub"
    root = write_project(tmp_path, files_for(data))

    result = register(root, fake_keycloak, KEYCLOAK_ADMIN_PASSWORD="")

    assert result.returncode == 1
    assert "KEYCLOAK_ADMIN_PASSWORD" in result.stderr
