"""Registers this project's clients and roles in a Keycloak realm.

Use it when the realm already exists, for example to add this project to a Keycloak that
other projects share (single sign-on across platforms), or to apply changed settings after the
first start. It reads keycloak/clients.json (generated), needs only the Python standard
library, and can be run again at any time: existing clients are updated, missing roles are
added, nothing is deleted and nobody's role assignments change.

    KEYCLOAK_PUBLIC_URL=https://id.example.com \\
    KEYCLOAK_ADMIN_USERNAME=... KEYCLOAK_ADMIN_PASSWORD=... \\
    API_PUBLIC_URL=https://api.example.com \\
    python scripts/keycloak_register.py

The admin credentials are read from the environment and sent only to Keycloak over the
address you give; they are never stored or printed.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TIMEOUT = 15
DOCUMENT = Path(__file__).resolve().parent.parent / "keycloak" / "clients.json"


class RegisterError(Exception):
    pass


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise RegisterError(f"set {name}")
    return value


def call(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any = None,
    form: dict[str, str] | None = None,
    allow_missing: bool = False,
) -> tuple[Any, dict[str, str]]:
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
            return (json.loads(raw) if raw else None), dict(response.headers)
    except urllib.error.HTTPError as exc:
        if allow_missing and exc.code == 404:
            return None, {}
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        path = urllib.parse.urlsplit(url).path
        raise RegisterError(f"{method} {path} -> {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RegisterError(f"cannot reach Keycloak: {exc.reason}") from exc


def admin_token(base: str) -> str:
    username = env("KEYCLOAK_ADMIN_USERNAME", os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME"))
    password = env("KEYCLOAK_ADMIN_PASSWORD", os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD"))
    reply, _ = call(
        "POST",
        f"{base}/realms/master/protocol/openid-connect/token",
        form={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": username,
            "password": password,
        },
    )
    return str(reply["access_token"])


def fill(value: Any, replacements: dict[str, str]) -> Any:
    """Substitute ${NAME} placeholders in every string of a JSON document."""
    if isinstance(value, str):
        for name, text in replacements.items():
            value = value.replace("${" + name + "}", text)
        return value
    if isinstance(value, list):
        return [fill(v, replacements) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, replacements) for k, v in value.items()}
    return value


def ensure_client(admin: str, token: str, desired: dict[str, Any]) -> str:
    """Create the client or bring an existing one in line. Returns its internal id."""
    client_id = desired["clientId"]
    query = urllib.parse.urlencode({"clientId": client_id})
    found, _ = call("GET", f"{admin}/clients?{query}", token=token)
    mappers = desired.get("protocolMappers", [])
    if not found:
        call("POST", f"{admin}/clients", token=token, body=desired)
        found, _ = call("GET", f"{admin}/clients?{query}", token=token)
        print(f"  created client {client_id}")
    else:
        update = {k: v for k, v in desired.items() if k != "protocolMappers"}
        current = found[0]
        update["attributes"] = {**current.get("attributes", {}), **desired.get("attributes", {})}
        call("PUT", f"{admin}/clients/{current['id']}", token=token, body={**current, **update})
        print(f"  updated client {client_id}")
    internal = str(found[0]["id"])
    existing, _ = call("GET", f"{admin}/clients/{internal}/protocol-mappers/models", token=token)
    have = {m["name"] for m in existing}
    for mapper in mappers:
        if mapper["name"] not in have:
            call(
                "POST",
                f"{admin}/clients/{internal}/protocol-mappers/models",
                token=token,
                body=mapper,
            )
    return internal


def ensure_roles(admin: str, token: str, api_internal: str, roles: list[dict[str, Any]]) -> None:
    for role in roles:
        name = urllib.parse.quote(role["name"], safe="")
        found, _ = call(
            "GET",
            f"{admin}/clients/{api_internal}/roles/{name}",
            token=token,
            allow_missing=True,
        )
        if found is None:
            call("POST", f"{admin}/clients/{api_internal}/roles", token=token, body=role)
            print(f"  added role {role['name']}")


def map_scopes(admin: str, token: str, api_internal: str, browser_internal: list[str]) -> None:
    """Let the browser clients' tokens carry this API's roles, and nothing else."""
    roles, _ = call("GET", f"{admin}/clients/{api_internal}/roles", token=token)
    if not roles:
        return
    for client in browser_internal:
        call(
            "POST",
            f"{admin}/clients/{client}/scope-mappings/clients/{api_internal}",
            token=token,
            body=roles,
        )


def enable_organizations(admin: str, token: str) -> None:
    """Tenants are Keycloak organizations, which a realm must have switched on."""
    realm, _ = call("GET", admin, token=token)
    if not realm.get("organizationsEnabled"):
        call("PUT", admin, token=token, body={**realm, "organizationsEnabled": True})
        print("  turned organizations on")


def ensure_default_scope(admin: str, token: str, client: str, scope_name: str) -> None:
    scopes, _ = call("GET", f"{admin}/client-scopes", token=token)
    scope = next((s for s in scopes if s["name"] == scope_name), None)
    if scope is None:
        raise RegisterError(f"the realm has no client scope {scope_name!r}")
    call("PUT", f"{admin}/clients/{client}/default-client-scopes/{scope['id']}", token=token)


def ensure_user_profile(admin: str, token: str, attributes: list[dict[str, Any]]) -> None:
    """Add this project's registration fields to the realm's user profile. An attribute the realm
    already defines is left as it is (it may be shared with another project)."""
    if not attributes:
        return
    profile, _ = call("GET", f"{admin}/users/profile", token=token)
    have = {a["name"] for a in profile["attributes"]}
    added = [a for a in attributes if a["name"] not in have]
    if added:
        profile["attributes"].extend(added)
        call("PUT", f"{admin}/users/profile", token=token, body=profile)
        for attribute in added:
            print(f"  added user attribute {attribute['name']}")


def main() -> int:
    document = json.loads(DOCUMENT.read_text(encoding="utf-8"))
    base = env("KEYCLOAK_PUBLIC_URL").rstrip("/")
    if not base.startswith("https://") and "localhost" not in base and "127.0.0.1" not in base:
        raise RegisterError("KEYCLOAK_PUBLIC_URL must be https (or localhost for local work)")
    api_url = env("API_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    realm = document["realm"]
    admin = f"{base}/admin/realms/{urllib.parse.quote(realm, safe='')}"
    document = fill(document, {"API_PUBLIC_URL": api_url})

    print(f"Registering in realm {realm} at {base}")
    token = admin_token(base)
    internal: dict[str, str] = {}
    for client in document["clients"]:
        internal[client["clientId"]] = ensure_client(admin, token, client)
    api_internal = internal[document["api_client_id"]]
    ensure_roles(admin, token, api_internal, document["roles"])
    map_scopes(admin, token, api_internal, [internal[c] for c in document["browser_client_ids"]])
    ensure_user_profile(admin, token, document.get("user_profile_attributes", []))
    if document.get("organizations"):
        enable_organizations(admin, token)
        for client_id in document["browser_client_ids"]:
            ensure_default_scope(admin, token, internal[client_id], "organization")
    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RegisterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
