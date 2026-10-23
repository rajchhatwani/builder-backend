"""Keycloak end to end: generate a Keycloak project, `docker compose up` it with a real Keycloak,
sign in the way a browser does (authorization code flow with PKCE) and call the generated API.

Proves what unit tests cannot: that Keycloak really imports the generated realm, that its
hardening holds (no password grant, no implicit flow, exact redirect URIs, PKCE, lock-out,
password policy, refresh rotation), that roles granted in Keycloak reach the API, and that two
projects can share one realm (single sign-on) without accepting each other's tokens.
Skipped when `docker compose` is unavailable. Pulls the pinned Keycloak image on first use.
"""

import base64
import hashlib
import json
import re
import secrets
import shutil
import socket
import subprocess
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
PASSWORD = "Correct-horse-battery-1"
ADMIN_PASSWORD = "Adm1n-" + secrets.token_hex(8)


def docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    not docker_compose_available(), reason="docker compose is not available"
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Stack:
    root: Path
    project: str
    api: str
    keycloak: str
    realm: str
    api_client: str
    web_client: str
    redirect: str


def compose(stack: Stack, *args: str, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-p", stack.project, *args],
        cwd=stack.root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def write_project(root: Path, spec: dict[str, Any]) -> None:
    for path, content in generate(Spec.model_validate(spec)).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def hub(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """The `keycloak_own` project running with its own Keycloak."""
    root = tmp_path_factory.mktemp("kc_hub")
    write_project(root, load("keycloak_own"))
    api_port, kc_port = free_port(), free_port()
    (root / ".env").write_text(
        "\n".join(
            [
                f"API_PORT={api_port}",
                f"API_PUBLIC_URL=http://localhost:{api_port}",
                f"KEYCLOAK_PORT={kc_port}",
                f"KEYCLOAK_PUBLIC_URL=http://localhost:{kc_port}",
                "KEYCLOAK_DB_PASSWORD=" + secrets.token_hex(12),
                "KC_BOOTSTRAP_ADMIN_USERNAME=admin",
                f"KC_BOOTSTRAP_ADMIN_PASSWORD={ADMIN_PASSWORD}",
                "SMTP_USERNAME=user",
                "SMTP_PASSWORD=pass",
                "KC_IDP_GOOGLE_CLIENT_SECRET=g",
                "KC_IDP_WORK_CLIENT_SECRET=w",
                "KC_IDP_GH_CLIENT_SECRET=h",
                "KC_IDP_CORP_CLIENT_SECRET=c",
                "",
            ]
        ),
        encoding="utf-8",
    )
    stack = Stack(
        root=root,
        project=f"kchub{secrets.token_hex(3)}",
        api=f"http://localhost:{api_port}",
        keycloak=f"http://localhost:{kc_port}",
        realm="hub",
        api_client="hub-api",
        web_client="hub-web",
        redirect="http://localhost:3000/",
    )
    try:
        up = compose(stack, "up", "-d", "--build", "--wait", "--wait-timeout", "600")
        if up.returncode != 0:
            logs = compose(stack, "logs", "--tail", "60").stdout
            raise AssertionError(f"compose up failed:\n{up.stdout}\n{up.stderr}\n{logs}")
        yield stack
    finally:
        compose(stack, "down", "-v", "--remove-orphans")


@pytest.fixture(scope="module")
def portal(hub: Stack, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """A second project, `keycloak_shared`, that trusts the realm of the first one."""
    spec = load("keycloak_shared")
    spec["auth"]["keycloak"].update(realm=hub.realm, redirect_uris=["http://localhost:3001/"])
    root = tmp_path_factory.mktemp("kc_portal")
    write_project(root, spec)
    api_port = free_port()
    (root / ".env").write_text(
        f"API_PORT={api_port}\nAPI_PUBLIC_URL=http://localhost:{api_port}\n"
        f"KEYCLOAK_PUBLIC_URL={hub.keycloak}\n"
        f"KEYCLOAK_INTERNAL_URL=http://host.docker.internal:{hub.keycloak.rsplit(':', 1)[1]}\n",
        encoding="utf-8",
    )
    # Lets the container reach the Keycloak that publishes its port on this machine.
    (root / "docker-compose.override.yml").write_text(
        "services:\n  api:\n    extra_hosts:\n      - host.docker.internal:host-gateway\n",
        encoding="utf-8",
    )
    stack = Stack(
        root=root,
        project=f"kcportal{secrets.token_hex(3)}",
        api=f"http://localhost:{api_port}",
        keycloak=hub.keycloak,
        realm=hub.realm,
        api_client="portal-api",
        web_client="portal-web",
        redirect="http://localhost:3001/",
    )
    registered = subprocess.run(
        [_python(), "scripts/keycloak_register.py"],
        cwd=root,
        env={
            **_clean_env(),
            "KEYCLOAK_PUBLIC_URL": hub.keycloak,
            "KEYCLOAK_ADMIN_USERNAME": "admin",
            "KEYCLOAK_ADMIN_PASSWORD": ADMIN_PASSWORD,
            "API_PUBLIC_URL": stack.api,
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert registered.returncode == 0, registered.stdout + registered.stderr
    try:
        up = compose(stack, "up", "-d", "--build", "--wait", "--wait-timeout", "300")
        assert up.returncode == 0, up.stdout + up.stderr
        yield stack
    finally:
        compose(stack, "down", "-v", "--remove-orphans")


def _python() -> str:
    import sys

    return sys.executable


def _clean_env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


# --- talking to Keycloak -----------------------------------------------------------------


def admin_token(stack: Stack) -> str:
    reply = httpx.post(
        f"{stack.keycloak}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": ADMIN_PASSWORD,
        },
    )
    reply.raise_for_status()
    return str(reply.json()["access_token"])


def admin_call(stack: Stack, method: str, path: str, token: str, **kwargs: Any) -> httpx.Response:
    return httpx.request(
        method,
        f"{stack.keycloak}/admin/realms/{stack.realm}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        **kwargs,
    )


def make_user(stack: Stack, email: str, roles: list[str]) -> None:
    token = admin_token(stack)
    created = admin_call(
        stack,
        "POST",
        "/users",
        token,
        json={
            "username": email,
            "email": email,
            "firstName": "Test",
            "lastName": "User",
            "enabled": True,
            "emailVerified": True,
            "requiredActions": [],
            "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
        },
    )
    if created.status_code == 409:  # already there, from another stack of the same realm
        user_id = admin_call(stack, "GET", f"/users?email={urllib.parse.quote(email)}", token)
        user_id = user_id.json()[0]["id"]
    else:
        assert created.status_code == 201, created.text
        user_id = created.headers["Location"].rsplit("/", 1)[1]
    client = admin_call(stack, "GET", f"/clients?clientId={stack.api_client}", token).json()[0]
    available = {
        r["name"]: r
        for r in admin_call(stack, "GET", f"/clients/{client['id']}/roles", token).json()
    }
    if roles:
        mapped = admin_call(
            stack,
            "POST",
            f"/users/{user_id}/role-mappings/clients/{client['id']}",
            token,
            json=[available[name] for name in roles],
        )
        assert mapped.status_code in (200, 204), mapped.text


def sign_in(
    stack: Stack,
    email: str,
    password: str = PASSWORD,
    *,
    client: str | None = None,
    redirect: str | None = None,
) -> dict[str, Any]:
    """The authorization code flow with PKCE, step by step like a browser: the login page, the
    form post, the redirect with a code, the code exchanged for tokens."""
    client = client or stack.web_client
    redirect = redirect or stack.redirect
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(8)
    cookies: dict[str, str] = {}

    def keep(response: httpx.Response) -> httpx.Response:
        # Keycloak marks its cookies Secure; browsers accept that on localhost, httpx does not.
        for line in response.headers.get_list("set-cookie"):
            name, _, rest = line.partition("=")
            cookies[name] = rest.split(";", 1)[0]
        return response

    base = f"{stack.keycloak}/realms/{stack.realm}/protocol/openid-connect"
    with httpx.Client(follow_redirects=False, timeout=30) as http:
        page = keep(
            http.get(
                f"{base}/auth",
                params={
                    "client_id": client,
                    "redirect_uri": redirect,
                    "response_type": "code",
                    "scope": "openid",
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
            )
        )
        page.raise_for_status()
        action = re.search(r'action="([^"]+)"', page.text)
        assert action, page.text[:300]
        done = keep(
            http.post(
                action.group(1).replace("&amp;", "&"),
                data={"username": email, "password": password, "credentialId": ""},
                headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())},
            )
        )
        if done.status_code != 302:
            raise SignInRefused(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", done.text))[-200:])
        location = done.headers["location"]
        assert location.startswith(redirect), location
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        assert query["state"] == [state]
    tokens = httpx.post(
        f"{base}/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client,
            "code": query["code"][0],
            "redirect_uri": redirect,
            "code_verifier": verifier,
        },
    )
    tokens.raise_for_status()
    result: dict[str, Any] = tokens.json()
    return result


class SignInRefused(Exception):
    pass


def claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    decoded: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return decoded


def api(stack: Stack, path: str, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.get(f"{stack.api}{path}", headers=headers, timeout=30)


# --- the generated realm ------------------------------------------------------------------


def test_the_generated_realm_imported_as_designed(hub: Stack) -> None:
    token = admin_token(hub)
    realm = admin_call(hub, "GET", "", token).json()
    assert realm["sslRequired"] == "external"
    assert realm["bruteForceProtected"] is True
    assert realm["passwordPolicy"].startswith("length(12)")
    assert realm["revokeRefreshToken"] is True and realm["eventsEnabled"] is True
    # ${ENV} placeholders were filled in from the container's environment.
    assert realm["smtpServer"]["user"] == "user" and "${" not in json.dumps(realm["smtpServer"])

    clients = {c["clientId"]: c for c in admin_call(hub, "GET", "/clients", token).json()}
    web = clients["hub-web"]
    assert web["publicClient"] is True and web["directAccessGrantsEnabled"] is False
    assert web["implicitFlowEnabled"] is False
    assert web["attributes"]["pkce.code.challenge.method"] == "S256"
    docs = clients["hub-web-docs"]
    assert docs["redirectUris"] == [f"{hub.api}/docs/oauth2-redirect"]
    assert clients["hub-api"]["standardFlowEnabled"] is False

    actions = {
        a["alias"]: a
        for a in admin_call(hub, "GET", "/authentication/required-actions", token).json()
    }
    assert actions["UPDATE_PASSWORD"]["enabled"] and actions["VERIFY_EMAIL"]["enabled"]

    providers = admin_call(hub, "GET", "/identity-provider/instances", token).json()
    assert {p["alias"] for p in providers} == {"corp", "gh", "google", "work"}
    assert {p["alias"]: p["trustEmail"] for p in providers}["google"] is True


def test_the_login_page_offers_every_configured_provider(hub: Stack) -> None:
    page = httpx.get(
        f"{hub.keycloak}/realms/hub/protocol/openid-connect/auth",
        params={
            "client_id": "hub-web",
            "redirect_uri": hub.redirect,
            "response_type": "code",
            "scope": "openid",
            "code_challenge": "a" * 43,
            "code_challenge_method": "S256",
        },
    )
    for alias in ("google", "work", "gh", "corp"):
        assert f"broker/{alias}/login" in page.text


# --- sign-in and roles ----------------------------------------------------------------------


def test_a_keycloak_user_signs_in_to_the_api_with_the_roles_keycloak_gave(hub: Stack) -> None:
    make_user(hub, "member@example.com", [])
    make_user(hub, "boss@example.com", ["admin"])

    member = sign_in(hub, "member@example.com")["access_token"]
    token_claims = claims(member)
    assert token_claims["iss"] == f"{hub.keycloak}/realms/hub"
    assert "hub-api" in token_claims["aud"] and token_claims["typ"] == "Bearer"
    assert "realm_access" not in token_claims  # no other roles leak into the token

    me = api(hub, "/auth/me", member)
    assert me.status_code == 200 and me.json()["roles"] == ["member"]  # the default role
    assert api(hub, "/notes", member).status_code == 200
    assert api(hub, "/reports", member).status_code == 403

    boss = sign_in(hub, "boss@example.com")["access_token"]
    assert claims(boss)["resource_access"] == {"hub-api": {"roles": ["admin"]}}
    assert "admin" in api(hub, "/auth/me", boss).json()["roles"]
    assert api(hub, "/reports", boss).status_code == 200


def test_swagger_ui_signs_in_through_keycloak(hub: Stack) -> None:
    docs = httpx.get(f"{hub.api}/docs").text
    assert "usePkceWithAuthorizationCodeGrant" in docs and "hub-web-docs" in docs
    scheme = httpx.get(f"{hub.api}/openapi.json").json()["components"]["securitySchemes"]
    flow = scheme["OAuth2AuthorizationCodeBearer"]["flows"]["authorizationCode"]
    assert flow["authorizationUrl"] == f"{hub.keycloak}/realms/hub/protocol/openid-connect/auth"

    make_user(hub, "docs@example.com", ["admin"])
    token = sign_in(
        hub,
        "docs@example.com",
        client="hub-web-docs",
        redirect=f"{hub.api}/docs/oauth2-redirect",
    )["access_token"]
    assert api(hub, "/reports", token).status_code == 200


def test_tokens_of_the_wrong_kind_are_refused(hub: Stack) -> None:
    make_user(hub, "kinds@example.com", [])
    tokens = sign_in(hub, "kinds@example.com")
    assert api(hub, "/auth/me", tokens["refresh_token"]).status_code == 401
    assert api(hub, "/auth/me", tokens["id_token"]).status_code == 401
    assert api(hub, "/auth/me", tokens["access_token"][:-4] + "AAAA").status_code == 401
    assert api(hub, "/auth/me").status_code == 401


# --- what the realm refuses ------------------------------------------------------------------


def test_the_realm_refuses_insecure_flows(hub: Stack) -> None:
    base = f"{hub.keycloak}/realms/hub/protocol/openid-connect"
    password_grant = httpx.post(
        f"{base}/token",
        data={
            "grant_type": "password",
            "client_id": "hub-web",
            "username": "member@example.com",
            "password": PASSWORD,
        },
    )
    assert "unauthorized_client" in password_grant.text

    implicit = httpx.get(
        f"{base}/auth",
        params={
            "client_id": "hub-web",
            "redirect_uri": hub.redirect,
            "response_type": "token",
            "scope": "openid",
        },
        follow_redirects=False,
    )
    assert "unauthorized_client" in implicit.headers.get("location", implicit.text)

    other = httpx.get(
        f"{base}/auth",
        params={
            "client_id": "hub-web",
            "redirect_uri": "http://localhost:3000/evil",
            "response_type": "code",
            "scope": "openid",
            "code_challenge": "a" * 43,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert other.status_code == 400 or "redirect_uri" in other.text

    no_pkce = httpx.get(
        f"{base}/auth",
        params={
            "client_id": "hub-web",
            "redirect_uri": hub.redirect,
            "response_type": "code",
            "scope": "openid",
        },
        follow_redirects=False,
    )
    assert "code_challenge" in no_pkce.headers.get("location", no_pkce.text)


def test_the_password_policy_and_lockout_hold(hub: Stack) -> None:
    token = admin_token(hub)
    weak = admin_call(
        hub,
        "POST",
        "/users",
        token,
        json={
            "username": "weak@example.com",
            "email": "weak@example.com",
            "enabled": True,
            "credentials": [{"type": "password", "value": "short", "temporary": False}],
        },
    )
    assert weak.status_code == 400

    make_user(hub, "victim@example.com", [])
    for attempt in range(6):
        with pytest.raises(SignInRefused):
            sign_in(hub, "victim@example.com", f"wrong-password-{attempt}")
    with pytest.raises(SignInRefused):  # the right password no longer works while locked
        sign_in(hub, "victim@example.com")


def test_refresh_tokens_rotate_and_cannot_be_replayed(hub: Stack) -> None:
    make_user(hub, "rotate@example.com", [])
    tokens = sign_in(hub, "rotate@example.com")
    url = f"{hub.keycloak}/realms/hub/protocol/openid-connect/token"
    data = {"grant_type": "refresh_token", "client_id": "hub-web"}
    first = httpx.post(url, data={**data, "refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    replay = httpx.post(url, data={**data, "refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 400


def test_the_database_remembers_its_identity_provider(hub: Stack) -> None:
    result = compose(
        hub,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        "app",
        "-d",
        "app",
        "-tA",
        "-c",
        "select provider, realm from auth_provider_lock",
    )
    assert result.stdout.strip() == "keycloak|hub", result.stdout + result.stderr


# --- two projects, one realm -------------------------------------------------------------------


def test_one_login_works_on_both_projects_but_tokens_stay_separate(
    hub: Stack, portal: Stack
) -> None:
    make_user(portal, "shared@example.com", ["agent"])

    portal_token = sign_in(portal, "shared@example.com")["access_token"]
    hub_token = sign_in(hub, "shared@example.com")["access_token"]

    assert api(portal, "/auth/me", portal_token).status_code == 200
    assert api(portal, "/tickets", portal_token).status_code == 200
    assert api(hub, "/auth/me", hub_token).status_code == 200
    # A token meant for one platform's API is not accepted by the other's.
    assert api(portal, "/auth/me", hub_token).status_code == 401
    assert api(hub, "/auth/me", portal_token).status_code == 401
    # Roles belong to the client: each token carries only its own project's.
    assert list(claims(portal_token)["resource_access"]) == ["portal-api"]
    assert "portal-api" not in claims(hub_token).get("resource_access", {})
