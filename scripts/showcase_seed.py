"""Seed the showcase org (neutral examples only). Run AFTER scripts/showcase_stack.sh start.

    python scripts/showcase_seed.py [--base http://localhost:8780]

Creates (idempotent): org "showcase", demo accounts editor/viewer (verified straight in the local
showcase database, setup only), two example projects from the demo specs (invoice approval, HR
leave) with the three roles on them. The agent-built project comes from scripts/demo_agent_run.py.
Passwords are generated once and kept in ~/.local/share/builder-showcase/ (never printed here).
"""

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "tests" / "fixtures" / "specs"
SECRETS = Path.home() / ".local/share/builder-showcase"
H = {"X-Requested-With": "builder"}
PG = "bb-showcase-pg"


def psql(sql: str) -> str:
    return subprocess.run(
        ["docker", "exec", PG, "psql", "-U", "builder", "-d", "builder", "-v", "ON_ERROR_STOP=1", "-Atc", sql],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def password() -> str:
    f = SECRETS / "demo_pw"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(14) + "-Aa1")
        f.chmod(0o600)
    return f.read_text().strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8780")
    a = ap.parse_args()
    admin_email = "rajchhatwani39@gmail.com"
    apw = (SECRETS / "admin_pw").read_text().strip()
    anon = httpx.Client(base_url=a.base, headers=H, timeout=60)
    admin = httpx.Client(base_url=a.base, headers=H, timeout=60)
    admin.headers["Authorization"] = "Bearer " + admin.post(
        "/account/login", json={"email": admin_email, "password": apw}
    ).json()["access_token"]

    org = admin.post("/orgs", json={"name": "Showcase", "slug": "showcase"})
    org = admin.get("/orgs/showcase") if org.status_code == 409 else org
    org.raise_for_status()
    org_id = org.json()["id"]

    people = {"editor": "showcase-editor@example.com", "viewer": "showcase-viewer@example.com"}
    pw = password()
    for who, email in people.items():
        r = anon.post("/account/register", json={"email": email, "password": pw, "name": who.title()})
        if r.status_code not in (202, 409):
            r.raise_for_status()
        psql(f"update platform_users set email_verified_at = now() where email = '{email}'")
        uid = psql(f"select id from platform_users where email = '{email}'")
        psql(
            "insert into organization_members (organization_id, user_id, role, joined_at) "
            f"values ('{org_id}', '{uid}', 'member', now()) on conflict do nothing"
        )

    existing = admin.get("/orgs/showcase/projects").json()
    existing = existing["items"] if isinstance(existing, dict) else existing
    have = {p["name"]: p["id"] for p in existing}
    for name, fixture in (("Invoice Approval", "demo_invoice"), ("HR Leave Requests", "demo_leave")):
        pid = have.get(name)
        if pid is None:
            r = admin.post("/projects", json={"name": name, "organization_id": org_id})
            r.raise_for_status()
            pid = r.json()["id"]
            spec = json.loads((SPECS / f"{fixture}.json").read_text(encoding="utf-8"))
            spec.setdefault("project", {})["name"] = name
            put = admin.put(f"/projects/{pid}/spec", json=spec)
            if put.status_code >= 400:
                print(f"! {name}: spec import refused: {put.status_code} {put.text[:200]}")
        for who, email in people.items():
            m = admin.post(f"/projects/{pid}/members", json={"email": email, "role": who})
            if m.status_code not in (201, 409):
                print(f"! {name}: adding {who} failed: {m.status_code} {m.text[:160]}")
        print(f"project {name}: {pid}")
    print("accounts: owner/platform admin =", admin_email, "; editor =", people["editor"], "; viewer =", people["viewer"])
    print("demo account password file:", SECRETS / "demo_pw")
    return 0


if __name__ == "__main__":
    sys.exit(main())
