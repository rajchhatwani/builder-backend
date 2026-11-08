"""Adversarial review: account pre-hijacking via unverified sign-up + SCIM link / invite-by-id (REQ §4.2 step 3, §4.3, §8 invites).

Sign-up does not verify e-mail ownership (no email_verified column / flow).  Therefore:
  A) an attacker who registers victim@<verified-domain> BEFORE the IdP provisions the victim keeps a working
     password on the account SCIM later 'links' into the org;
  B) an attacker who registers the invitee's address sees + accepts the invitation without the e-mailed link.
Run: uv run python -m pytest review/tests/test_adv_prehijack.py -p no:cacheprovider -q
"""
import pytest

from tests.api.conftest import TEST_PASSWORD, ClientFor
from tests.api.test_scim import SCIM, dns, enterprise_org, provision, scim_token  # noqa: F401

pytestmark = pytest.mark.usefixtures("dns")


async def test_A_scim_link_keeps_attackers_password(client_for: ClientFor, anon_client, session_factory, dns) -> None:  # noqa: ANN001,F811
    owner = await client_for("ph-owner@example.com")
    await enterprise_org(owner, session_factory, dns, "ph-co", "phco.test")
    h = await scim_token(owner, "ph-co")
    # attacker self-registers the victim's corporate address (open sign-up, no verification)
    reg = await anon_client.post("/account/register", json={"email": "victim@phco.test", "password": TEST_PASSWORD + "x", "name": "attacker"})
    assert reg.status_code in (200, 201), reg.text
    # the real IdP now provisions the real victim: the existing account is linked into the org
    await provision(anon_client, h, "victim@phco.test")
    # attacker logs in with the password they set before the link
    login = await anon_client.post("/account/login", json={"email": "victim@phco.test", "password": TEST_PASSWORD + "x"})
    assert login.status_code != 200 or "access_token" not in login.text, (
        "FINDING: attacker's pre-set password still signs in to the account SCIM linked into the org"
    )


async def test_B_invite_can_be_accepted_by_unverified_address_owner(client_for: ClientFor, anon_client, session_factory) -> None:  # noqa: ANN001
    owner = await client_for("inv-owner@example.com")
    await owner.post("/orgs", json={"name": "Inv", "slug": "inv-co"})
    r = await owner.post("/orgs/inv-co/invitations", json={"email": "target@corp.test", "role": "member"})
    assert r.status_code == 201, r.text
    # attacker registers the target's address and never sees the e-mailed link
    reg = await anon_client.post("/account/register", json={"email": "target@corp.test", "password": TEST_PASSWORD, "name": "mallory"})
    assert reg.status_code in (200, 201), reg.text
    tok = reg.json().get("access_token")
    if not tok:
        lg = await anon_client.post("/account/login", json={"email": "target@corp.test", "password": TEST_PASSWORD})
        tok = lg.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    pend = (await anon_client.get("/orgs/invitations/pending", headers=h)).json()["items"]
    assert pend, "attacker sees nothing"
    acc = await anon_client.post(f"/orgs/invitations/{pend[0]['id']}/accept", headers=h)
    assert acc.status_code != 200, "FINDING: invite accepted by whoever registered the invited address (no mailbox proof)"
