"""Adversarial review: secrets hygiene (REQ: 'never log raw tokens/passwords/secrets; only hashes stored', §4.3 shown once, §7.1).
Plants canary secrets through the real flows, then greps audit rows, DB columns, log output and later API reads.
Run: uv run python -m pytest review/tests/test_adv_secrets.py -p no:cacheprovider -q
"""
import json
import logging

import pytest
from sqlalchemy import text

from tests.api._mfa_helpers import enroll
from tests.api.conftest import _FACTORY, TEST_PASSWORD, ClientFor, TotpClock
from tests.api.test_scim import dns, enterprise_org, scim_token  # noqa: F401
from tests.api.test_sso_config import OIDC_CONFIG

pytestmark = pytest.mark.usefixtures("dns")
CLIENT_SECRET = "OIDC-SECRET-CANARY-9f3a"


async def test_no_secret_reaches_audit_logs_or_later_reads(client_for: ClientFor, anon_client, session_factory, dns, caplog, totp_clock: TotpClock) -> None:  # noqa: ANN001,F811
    caplog.set_level(logging.DEBUG)
    owner = await client_for("sec-owner@example.com")
    await enterprise_org(owner, session_factory, dns, "sec-co", "secco.test")
    canaries: dict[str, str] = {}

    # SSO client secret
    r = await owner.put("/orgs/sec-co/sso", json={**OIDC_CONFIG, "oidc_client_secret": CLIENT_SECRET})
    assert r.status_code == 200, r.text
    canaries["oidc_secret"] = CLIENT_SECRET
    # SCIM token
    st = await owner.post("/orgs/sec-co/scim/token")
    canaries["scim_token"] = st.json()["token"]
    # PAT
    pat = await owner.post("/account/tokens", json={"name": "ci", "scopes": ["read"]})
    canaries["pat"] = pat.json().get("token") or pat.json().get("secret")
    # invitation token
    inv = await owner.post("/orgs/sec-co/invitations", json={"email": "inv@secco.test", "role": "member"})
    canaries["invite_token"] = inv.json()["token"]
    # TOTP secret + recovery codes
    secret, recovery = await enroll(owner, totp_clock)
    canaries["totp_secret"] = secret
    canaries["recovery"] = recovery[0]
    canaries["password"] = TEST_PASSWORD
    canaries = {k: v for k, v in canaries.items() if v}

    # --- later GETs must not echo secrets
    reads = ["/orgs/sec-co/sso", "/orgs/sec-co/scim", "/orgs/sec-co/invitations", "/orgs/sec-co/members",
             "/orgs/sec-co/audit", "/orgs/sec-co/plan", "/orgs/sec-co/policies", "/account/tokens", "/account/mfa", "/account/me"]
    leaks = []
    for p in reads:
        resp = await owner.get(p)
        for name, val in canaries.items():
            if val in resp.text:
                leaks.append((p, name))
    # --- audit table + every text column of every table
    async with _FACTORY[0]() as s:
        tables = [t for (t,) in (await s.execute(text("select tablename from pg_tables where schemaname='public'"))).all()]
        for t in tables:
            rows = (await s.execute(text(f'select row_to_json(x)::text from "{t}" x'))).scalars().all()
            blob = "\n".join(rows)
            for name, val in canaries.items():
                if val in blob:
                    leaks.append((f"db:{t}", name))
    logs = "\n".join(rec.getMessage() for rec in caplog.records)
    for name, val in canaries.items():
        if val in logs:
            leaks.append(("log", name))
    # the expected exceptions: the invitation token is shown once at creation only, not stored raw
    assert leaks == [], leaks
