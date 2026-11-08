"""Drive one REAL builder-agent run against the showcase stack: chat prompt + requirements PDF ->
plan (Gate A) -> build -> gates -> final approval (C) -> applied project.

    python scripts/demo_agent_run.py [--base http://localhost:8780] [--dry]

Reads the admin password from ~/.local/share/builder-showcase/admin_pw (never printed). Spends real
model money (bounded by the platform hard cap and the per-run budget). Neutral example only.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

PROMPT = (
    "Build a small leave-request backend. Employees request leave with a start date, end date and a "
    "reason. A manager approves or rejects each request. See the attached requirements document."
)
DOC_LINES = [
    "Leave Desk - requirements",
    "1. A LeaveRequest has employee name, start date, end date, reason and a status.",
    "2. Status moves: pending -> approved or rejected. Only a manager may move it.",
    "3. End date must not be before the start date.",
    "4. Managers can list requests filtered by status.",
]


def make_pdf(lines: list[str]) -> bytes:
    """A tiny valid one-page PDF with the given text lines (no external libraries)."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    text = "BT /F1 12 Tf 50 750 Td 16 TL " + " T* ".join(f"({esc(x)}) Tj" for x in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8780")
    ap.add_argument("--email", default=os.environ.get("SC_ADMIN_EMAIL", "admin@example.test"))
    ap.add_argument("--project", default="Leave Desk (built by the agent)")
    ap.add_argument("--max-loops", type=int, default=30)
    a = ap.parse_args()
    pw = (Path.home() / ".local/share/builder-showcase/admin_pw").read_text().strip()
    h = {"X-Requested-With": "builder"}
    c = httpx.Client(base_url=a.base, headers=h, timeout=300)

    r = c.post("/account/login", json={"email": a.email, "password": pw})
    if r.status_code != 200 or "access_token" not in r.json():
        r = c.post("/admin/login", json={"email": a.email, "password": pw})
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    r = c.post("/orgs", json={"name": "Showcase", "slug": "showcase"})
    if r.status_code not in (201, 409):
        r.raise_for_status()
    org = c.get("/orgs/showcase").json() if r.status_code == 409 else r.json()
    listed = c.get("/orgs/showcase/projects").json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    found = [p for p in rows if p["name"] == a.project]
    if found:  # the free plan caps projects: reuse the one from an earlier attempt
        pid = found[0]["id"]
    else:
        r = c.post("/projects", json={"name": a.project, "organization_id": org["id"]})
        if r.status_code == 402:  # plan limit: the operator (platform admin) raises the demo org's plan
            adm = c.post("/admin/login", json={"email": a.email, "password": pw})
            adm.raise_for_status()
            up = c.patch(
                f"/admin/organizations/{org['id']}/plan",
                json={"plan_id": "business", "reason": "showcase demo"},
                headers={"Authorization": f"Bearer {adm.json()['access_token']}"},
            )
            up.raise_for_status()
            r = c.post("/projects", json={"name": a.project, "organization_id": org["id"]})
        r.raise_for_status()
        pid = r.json()["id"]
    wss = c.get(f"/projects/{pid}/workspaces").json()
    wss = wss["items"] if isinstance(wss, dict) else wss
    active = [w for w in wss if w.get("state", "active") == "active"]
    if active:
        wid = active[0]["id"]
    else:
        ws = c.post(f"/projects/{pid}/workspaces", json={"name": "draft"})
        ws.raise_for_status()
        wid = ws.json()["id"]
    print("project", pid, "workspace", wid)

    r = c.post(
        f"/projects/{pid}/requirements/intake",
        data={"prompt": PROMPT},
        files=[("files", ("leave-requirements.pdf", make_pdf(DOC_LINES), "application/pdf"))],
    )
    r.raise_for_status()
    m = r.json()
    print("requirements:", len(m.get("items", [])), "items,", len(m.get("questions", [])), "questions")
    r = c.post(f"/projects/{pid}/requirements/start-run", json={"accept_assumptions": True, "workspace_id": wid})
    r.raise_for_status()
    rid = r.json()["id"]
    print("run", rid)

    for i in range(a.max_loops):
        r = c.post(f"/projects/{pid}/agent/runs/{rid}/resume")
        r.raise_for_status()
        run = r.json()
        bud = c.get("/orgs/showcase/ai/platform-budget").json()
        print(f"[{i}] state={run['state']} phase={run.get('phase')} stop={run.get('stop_code')} "
              f"spent={bud['spent_micro_usd'] / 1e6:.3f} USD of {bud['cap_micro_usd'] / 1e6:.2f}")
        if run["state"] in ("stopped", "finished", "done", "cancelled", "failed", "applied"):
            if run.get("stop_detail"):
                print("detail:", run["stop_detail"])
            break
        if run["state"] == "awaiting_approval":
            pend = c.get(f"/projects/{pid}/agent/approvals?state=pending").json()
            items = pend["items"] if isinstance(pend, dict) else pend
            for ap_ in items:
                print("  approving", ap_["kind"], ap_["subject"], "flags=", ap_["risk_flags"])
                if ap_["kind"] == "C" and ap_["payload"].get("final"):
                    print("  spec_diff:", json.dumps(ap_["payload"].get("spec_diff")), "empty_change:", ap_["payload"].get("empty_change"))
                    if ap_["payload"].get("empty_change"):
                        print("  NOTHING WAS BUILT: denying this final review instead of applying an empty change")
                        c.post(f"/projects/{pid}/agent/approvals/{ap_['id']}/decision", json={"approve": False, "note": "empty change"})
                        continue
                body = {"approve": True}
                if ap_.get("payload_hash"):  # decisions are bound to the payload that was read
                    body["expected_payload_hash"] = ap_["payload_hash"]
                d = c.post(f"/projects/{pid}/agent/approvals/{ap_['id']}/decision", json=body)
                if d.status_code != 200:
                    print("  decision failed", d.status_code, d.text[:300])
                    return 1
        time.sleep(1)
    final = c.get(f"/projects/{pid}/agent/runs/{rid}").json()
    print("final state:", final["state"], final.get("stop_code"))
    print("spec entities:", [e["name"] for e in c.get(f"/projects/{pid}/spec").json().get("entities", [])])
    return 0


if __name__ == "__main__":
    sys.exit(main())
