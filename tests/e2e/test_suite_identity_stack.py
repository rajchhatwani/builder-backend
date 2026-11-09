"""Suite identity, path (a), end to end: three generated projects and one real Keycloak.

Two projects are new members of the same suite (`acme`, realm `suite-acme`); the third belongs to
another suite (`other`, realm `suite-other`) on the same Keycloak. The first member's `register`
script creates the realm. Proves that one sign-in works for both members (the token's `aud` lists
both clients) and that the unrelated project refuses it, and the reverse.
Skipped when `docker compose` is unavailable. Pulls the pinned Keycloak image on first use.
"""

import secrets
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.generator.features.keycloak.module import KEYCLOAK_IMAGE, KEYCLOAK_IMAGE_TAG
from tests.e2e.test_keycloak_stack import (
    ADMIN_PASSWORD,
    Stack,
    _clean_env,
    _python,
    api,
    claims,
    compose,
    docker_compose_available,
    free_port,
    load,
    make_user,
    sign_in,
    write_project,
)

pytestmark = pytest.mark.skipif(
    not docker_compose_available(), reason="docker compose is not available"
)


@pytest.fixture(scope="module")
def keycloak(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A bare Keycloak (dev mode) with only the admin user; the projects create their realms."""
    root = tmp_path_factory.mktemp("suite_kc")
    port = free_port()
    (root / "docker-compose.yml").write_text(
        "services:\n"
        "  keycloak:\n"
        f"    image: {KEYCLOAK_IMAGE}:{KEYCLOAK_IMAGE_TAG}\n"
        "    command: start-dev\n"
        "    environment:\n"
        "      KC_BOOTSTRAP_ADMIN_USERNAME: admin\n"
        f"      KC_BOOTSTRAP_ADMIN_PASSWORD: {ADMIN_PASSWORD}\n"
        "    ports:\n"
        f'      - "{port}:8080"\n',
        encoding="utf-8",
    )
    project = f"suitekc{secrets.token_hex(3)}"

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", "-p", project, *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=900,
        )

    url = f"http://localhost:{port}"
    try:
        up = run("up", "-d")
        assert up.returncode == 0, up.stdout + up.stderr
        deadline = time.time() + 240
        while True:
            try:
                if httpx.get(f"{url}/realms/master", timeout=3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert time.time() < deadline, "Keycloak did not start:\n" + run("logs", "--tail", "40").stdout
            time.sleep(3)
        yield url
    finally:
        run("down", "-v", "--remove-orphans")


def start_member(
    tmp_path_factory: pytest.TempPathFactory,
    keycloak: str,
    *,
    slug: str,
    suite_id: str,
    web_port: int,
    hub_issuer: bool,
) -> Iterator[Stack]:
    realm = f"suite-{suite_id}"
    spec = load("keycloak_suite")
    spec["project"].update(name=slug.replace("-", " ").title(), slug=slug)
    spec["auth"]["suite"] = {
        "suite_id": suite_id,
        "hub_issuer": f"{keycloak}/realms/{realm}" if hub_issuer else None,
        "join_state": "joined",
    }
    spec["auth"]["keycloak"].update(
        realm=realm, redirect_uris=[f"http://localhost:{web_port}/"]
    )
    root: Path = tmp_path_factory.mktemp(slug)
    write_project(root, spec)
    api_port = free_port()
    kc_port = keycloak.rsplit(":", 1)[1]
    (root / ".env").write_text(
        f"APP_ENV=development\nAPI_PORT={api_port}\nAPI_PUBLIC_URL=http://localhost:{api_port}\n"
        f"KEYCLOAK_PUBLIC_URL={keycloak}\n"
        f"KEYCLOAK_INTERNAL_URL=http://host.docker.internal:{kc_port}\n",
        encoding="utf-8",
    )
    # Lets the container reach the Keycloak that publishes its port on this machine.
    (root / "docker-compose.override.yml").write_text(
        "services:\n  api:\n    extra_hosts:\n      - host.docker.internal:host-gateway\n",
        encoding="utf-8",
    )
    stack = Stack(
        root=root,
        project=f"{slug.replace('-', '')}{secrets.token_hex(3)}",
        api=f"http://localhost:{api_port}",
        keycloak=keycloak,
        realm=realm,
        api_client=slug,
        web_client=slug,
        redirect=f"http://localhost:{web_port}/",
    )
    registered = subprocess.run(
        [_python(), "scripts/keycloak_register.py"],
        cwd=root,
        env={
            **_clean_env(),
            "KEYCLOAK_PUBLIC_URL": keycloak,
            "KEYCLOAK_ADMIN_USERNAME": "admin",
            "KEYCLOAK_ADMIN_PASSWORD": ADMIN_PASSWORD,
            "API_PUBLIC_URL": stack.api,
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert registered.returncode == 0, registered.stdout + registered.stderr
    try:
        up = compose(stack, "up", "-d", "--build", "--wait", "--wait-timeout", "300")
        assert up.returncode == 0, up.stdout + up.stderr
        yield stack
    finally:
        compose(stack, "down", "-v", "--remove-orphans")


@pytest.fixture(scope="module")
def one(keycloak: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    yield from start_member(
        tmp_path_factory, keycloak, slug="suite-one", suite_id="acme", web_port=3101, hub_issuer=True
    )


@pytest.fixture(scope="module")
def two(keycloak: str, one: Stack, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    yield from start_member(
        tmp_path_factory, keycloak, slug="suite-two", suite_id="acme", web_port=3102, hub_issuer=False
    )


@pytest.fixture(scope="module")
def other(keycloak: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    yield from start_member(
        tmp_path_factory, keycloak, slug="other-app", suite_id="other", web_port=3103, hub_issuer=False
    )


def audiences(token: str) -> list[str]:
    aud: Any = claims(token)["aud"]
    return [aud] if isinstance(aud, str) else list(aud)


def test_the_first_member_created_the_suite_realm_with_one_client_each(
    one: Stack, two: Stack
) -> None:
    admin = httpx.post(
        f"{one.keycloak}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": ADMIN_PASSWORD,
        },
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {admin}"}
    realm = httpx.get(f"{one.keycloak}/admin/realms/suite-acme", headers=headers).json()
    assert realm["sslRequired"] == "external" and realm["bruteForceProtected"] is True
    clients = httpx.get(f"{one.keycloak}/admin/realms/suite-acme/clients", headers=headers).json()
    ours = {c["clientId"] for c in clients} & {"suite-one", "suite-two"}
    assert ours == {"suite-one", "suite-two"}  # one client per project, no -api/-web/-docs extras
    assert not {c["clientId"] for c in clients} & {"suite-one-api", "suite-one-web"}


def test_a_suite_token_is_accepted_by_the_other_member_and_refused_elsewhere(
    one: Stack, two: Stack, other: Stack
) -> None:
    make_user(one, "ann@example.com", ["agent"])
    make_user(two, "ann@example.com", ["agent"])

    token = sign_in(one, "ann@example.com")["access_token"]
    token_claims = claims(token)
    assert token_claims["iss"] == f"{one.keycloak}/realms/suite-acme"
    assert {"suite-one", "suite-two"} <= set(audiences(token))
    assert "other-app" not in audiences(token)

    assert api(one, "/auth/me", token).status_code == 200
    assert api(two, "/auth/me", token).status_code == 200  # suite-wide sign-in
    assert api(other, "/auth/me", token).status_code == 401  # a different suite and realm


def test_the_unrelated_project_tokens_are_refused_by_the_suite(
    one: Stack, two: Stack, other: Stack
) -> None:
    make_user(other, "bob@example.com", ["agent"])
    token = sign_in(other, "bob@example.com")["access_token"]
    assert api(other, "/auth/me", token).status_code == 200
    assert api(one, "/auth/me", token).status_code == 401
    assert api(two, "/auth/me", token).status_code == 401
    assert "suite-one" not in audiences(token)


def test_roles_stay_per_app(one: Stack, two: Stack) -> None:
    make_user(one, "carol@example.com", ["admin"])
    make_user(two, "carol@example.com", [])
    token = sign_in(one, "carol@example.com")["access_token"]
    resource_access = claims(token)["resource_access"]
    assert "admin" in resource_access["suite-one"]["roles"]
    assert "admin" not in resource_access.get("suite-two", {}).get("roles", [])
