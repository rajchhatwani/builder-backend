"""Adversarial review: NUL bytes / odd Unicode in string fields must never produce a 500 (REQ: input handling).
Run: uv run python -m pytest review/tests/test_adv_nul_and_unicode.py -p no:cacheprovider -q
"""
import pytest
from httpx import AsyncClient

from tests.api.conftest import ClientFor
from tests.api.test_scim import SCIM, dns, enterprise_org, scim_token, user_body  # noqa: F401

NUL = "a\x00b"
BAD = [NUL, "\ud800", "x" * 70000, "‮evil", "﻿", "á" * 200]


@pytest.mark.parametrize("val", BAD)
async def test_no_500_on_authenticated_json_fields(val: str, client_for: ClientFor) -> None:
    u = await client_for("nul@example.com")
    probes = [
        ("POST", "/orgs", {"name": val, "slug": "nul-co"}),
        ("POST", "/orgs", {"name": "ok", "slug": val}),
        ("POST", "/projects", {"name": val, "slug": "nulp"}),
        ("POST", "/account/tokens", {"name": val, "scopes": ["read"]}),
    ]
    org = await u.post("/orgs", json={"name": "ok", "slug": "nul-base"})
    slug = org.json()["slug"]
    probes += [
        ("PATCH", f"/orgs/{slug}", {"name": val}),
        ("POST", f"/orgs/{slug}/invitations", {"email": val, "role": "member"}),
    ]
    bad = []
    for m, p, b in probes:
        try:
            r = await u.request(m, p, json=b)
        except Exception as e:  # noqa: BLE001  (client-side encoding errors are not product bugs)
            if "surrogate" in str(e) or "encode" in str(e).lower():
                continue
            raise
        if r.status_code >= 500:
            bad.append((m, p, r.status_code))
    assert bad == [], bad


async def test_no_500_on_public_endpoints(anon_client: AsyncClient) -> None:
    bad = []
    for val in [NUL, "x" * 70000]:
        for p, b in [
            ("/account/register", {"email": f"{val}@example.com", "password": "correct horse battery 1", "name": val}),
            ("/account/login", {"email": f"{val}@example.com", "password": val}),
            ("/account/login/discover", {"email": f"{val}@example.com"}),
            ("/admin/login", {"email": f"{val}@example.com", "password": val}),
        ]:
            r = await anon_client.post(p, json=b)
            if r.status_code >= 500:
                bad.append((p, len(val), r.status_code))
    assert bad == [], bad
