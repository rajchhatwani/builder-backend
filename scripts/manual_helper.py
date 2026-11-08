#!/usr/bin/env python3
"""Helper for scripts/manual_stack.sh. Values from ~/final_test.env are used at run time only; never printed.

  manual_helper.py run -- CMD...      exec CMD with the computed stack environment
  manual_helper.py get KEY            print a NON-secret derived value (urls, ports, flags)
  manual_helper.py matrix             print the REAL / FAKE / NOT CONNECTED table
  manual_helper.py seed               create the standard test accounts (idempotent)
  manual_helper.py okta               print the URLs to register at the IdP
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "final_test" / "credentials"))
from check_env import load_env  # noqa: E402

HOME = Path.home()
STATE = HOME / ".local/share/bbmanual"
DATA = STATE / "data"
ENV_FILE = Path(os.environ.get("ENV_FILE", str(HOME / "final_test.env"))).expanduser()
SAFE_PUBLIC = {"BUILDER_SMTP_FROM"}


def sget(name: str, default: str = "") -> str:
    p = STATE / name
    return p.read_text().strip() if p.exists() else default


def runsc_available() -> bool:
    r = subprocess.run(["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True)
    return "runsc" in r.stdout


def compute() -> dict[str, str]:
    e = load_env(ENV_FILE)
    mode = sget("mode", "local")
    mail = sget("mail", "real")
    local_origin = "http://localhost:8081"
    out: dict[str, str] = {k: v for k, v in e.items() if k.startswith("BUILDER_") or k in {
        "SECRET_KEY", "STORAGE_ENDPOINT_URL", "STORAGE_REGION", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY_ID",
        "STORAGE_SECRET_ACCESS_KEY", "REDIS_URL", "OTEL_EXPORTER_OTLP_ENDPOINT"}}
    out["BUILDER_DATABASE_URL"] = "postgresql+asyncpg://builder_app:builder_app@127.0.0.1:5432/builder"
    out["BUILDER_MIGRATIONS_DATABASE_URL"] = "postgresql+asyncpg://builder:builder@127.0.0.1:5432/builder"
    out["BUILDER_WORKSPACE_DB_ADMIN_URL"] = out["BUILDER_MIGRATIONS_DATABASE_URL"]
    out["BUILDER_WORKSPACE_ROOT"] = f"{DATA}/ws"
    out["BUILDER_PREVIEW_ROOT"] = f"{DATA}/previews"
    out["BUILDER_PREVIEW_SCHEDULER_ENABLED"] = "true"
    out["BUILDER_SANDBOX_RUNTIME"] = "runsc" if runsc_available() else "runc"
    if mode == "public":
        origin = e.get("FINAL_TEST_TUNNEL_API_URL", "").rstrip("/")
    else:
        origin = local_origin
        out.update(BUILDER_ENVIRONMENT="local", BUILDER_PUBLIC_APP_URL=origin, BUILDER_PUBLIC_API_URL=origin,
                   BUILDER_CORS_ORIGINS=json.dumps([origin]), BUILDER_TRUST_PROXY_HEADERS="false")
    if mail == "sink":
        out.update(BUILDER_SMTP_HOST="127.0.0.1", BUILDER_SMTP_PORT="1025", BUILDER_SMTP_STARTTLS="false",
                   BUILDER_SMTP_USERNAME="", BUILDER_SMTP_PASSWORD="")
    # AI: key from .env.local (read silently), orgs from state
    envlocal = ROOT / ".env.local"
    if envlocal.exists():
        k = load_env(envlocal).get("BUILDER_AI_API_KEY", "")
        if k:
            out["BUILDER_AI_API_KEY"] = k
    out["BUILDER_AI_PLATFORM_KEY_ORGS"] = sget("ai_orgs.json", "[]")
    wh = sget("stripe_whsec")
    if wh:
        out["BUILDER_STRIPE_WEBHOOK_SECRET"] = wh
    if out.get("BUILDER_STRIPE_SECRET_KEY"):
        out["STRIPE_API_KEY"] = out["BUILDER_STRIPE_SECRET_KEY"]  # the Stripe CLI reads this: no login needed
    out["BB_CTX"] = str(STATE / "ctx")
    out["BB_DATA"] = str(DATA)
    out["BB_MODE"] = mode
    out["BB_ORIGIN"] = origin
    out["BB_PREVIEW_ORIGIN"] = "http://localhost:8799"
    out = {k: v for k, v in out.items() if v != ""}
    # keep explicitly-empty SMTP creds out (dropped above); stripe key for the CLI
    return out


def cmd_run(args: list[str]) -> None:
    if args and args[0] == "--":
        args = args[1:]
    env = {**os.environ, **compute()}
    os.execvpe(args[0], args, env)


def http(method: str, url: str, body=None, token: str | None = None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", "Origin": compute()["BB_ORIGIN"], **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw[:1] in b"{[" else raw.decode(errors="replace"))
    except urllib.error.HTTPError as ex:
        raw = ex.read()
        try:
            return ex.code, json.loads(raw)
        except Exception:
            return ex.code, raw.decode(errors="replace")[:200]
    except Exception as ex:  # noqa: BLE001
        return 0, type(ex).__name__


def up_check(url: str) -> bool:
    return http("GET", url)[0] in range(200, 400)


def psql(sql: str) -> str:
    r = subprocess.run(["docker", "exec", "-i", "bbmanual-postgres", "psql", "-U", "builder", "-d", "builder", "-Atq", "-c", sql],
                       capture_output=True, text=True)
    return r.stdout.strip()


def container_running(name: str) -> bool:
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True)
    return r.stdout.strip() == "true"


def cmd_seed() -> int:
    e = load_env(ENV_FILE)
    pw = e["FINAL_TEST_PASSWORD"]
    api = "http://127.0.0.1:8000"
    if not up_check(api + "/health"):
        print("API is not up: run scripts/manual_stack.sh up first")
        return 1
    accounts = [("FINAL_TEST_OWNER_EMAIL", "bb-owner", "customer (will own org bb-acme)"),
                ("FINAL_TEST_ADMIN_EMAIL", "bb_admin", "customer (to be invited as org admin)"),
                ("FINAL_TEST_MEMBER_EMAIL", "bb_member", "customer (to be invited as org member)"),
                ("FINAL_TEST_OUTSIDER_EMAIL", "bb_outsider", "customer (outsider, will own bb-other)"),
                ("FINAL_TEST_INDIVIDUAL_EMAIL", "bb_individual", "customer (personal org only)")]
    rows = []
    for key, name, role in accounts:
        em = e.get(key) or f"{name}@{e['FINAL_TEST_SSO_DOMAIN']}"
        code, _ = http("POST", api + "/account/register", {"email": em, "password": pw, "name": name})
        if code not in (200, 201, 202):
            print(f"register {em}: HTTP {code}")
        rows.append((em, role))
    import time
    time.sleep(1.5)
    for em, _ in rows:
        psql(f"update platform_users set email_verified_at=now() where lower(email)=lower('{em}') and email_verified_at is null")
    # platform support through the repo's own script (password via stdin, never on a command line)
    sup = e.get("FINAL_TEST_PLATFORM_SUPPORT_EMAIL", f"bb-support@{e['FINAL_TEST_SSO_DOMAIN']}")
    r = subprocess.run(["docker", "exec", "-i", "bbmanual-api", "python", "/app/scripts/create_admin.py", sup,
                        "--role", "platform_support", "--password-stdin"], input=pw + "\n", capture_output=True, text=True)
    if r.returncode != 0:
        print("create_admin (support) failed: " + r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else "create_admin failed")
    rows.append((sup, "platform support (admin console, TOTP enrolment at first sign-in)"))
    rows.append((e.get("BUILDER_BOOTSTRAP_ADMIN_EMAIL", "?"), "platform admin (bootstrap from env, TOTP enrolment at first sign-in)"))
    ver = {x.lower() for x in psql("select email from platform_users where email_verified_at is not null").split("\n")}
    print(f"{'e-mail':44} {'role':58} verified")
    for em, role in rows:
        print(f"{em:44} {role:58} {'yes' if em.lower() in ver else 'n/a (staff)'}")
    print("\npassword for every row = FINAL_TEST_PASSWORD in your env file (never printed here).")
    print("Fresh database: bb-owner has FINAL_TEST_PASSWORD too (the old-DB caveat about its own password does not apply).")
    print("Staff accounts must enrol TOTP at first sign-in (new database: the TOTP secrets in the env file belong to the OLD database).")
    if sget("mail", "real") != "sink":
        print("NOTE: MAIL is real: sign-up sent verification mails to the real mailbox (counts against the ~25 mail budget).")
    return 0


def urls() -> dict[str, str]:
    c = compute()
    o = c["BB_ORIGIN"]
    return {"origin": o, "acs": f"{o}/sso/saml/<org-slug>/acs", "entity": f"{o}/sso/metadata/<org-slug>",
            "oidc": f"{o}/sso/oidc/<org-slug>/callback", "scim": f"{o}/scim/v2"}


def cmd_okta() -> None:
    e = load_env(ENV_FILE)
    o = e.get("FINAL_TEST_TUNNEL_API_URL", "").rstrip("/")
    print(f"Register at Okta (public origin = tunnel; Okta cannot reach localhost). Replace <org-slug> by your org's slug:")
    print(f"  SAML ACS / Single sign-on URL : {o}/sso/saml/<org-slug>/acs")
    print(f"  SAML Audience / SP entity id  : {o}/sso/metadata/<org-slug>")
    print(f"  OIDC sign-in redirect URI     : {o}/sso/oidc/<org-slug>/callback")
    print(f"  SCIM base URL                 : {o}/scim/v2")
    if sget("mode", "local") != "public":
        print("  (stack is in local mode: these only work after `scripts/manual_stack.sh up public`)")


def cmd_matrix() -> None:
    e = load_env(ENV_FILE)
    mode, mail = sget("mode", "local"), sget("mail", "real")
    c = compute()
    rows: list[tuple[str, str, str]] = []
    add = lambda f, s, r: rows.append((f, s, r))  # noqa: E731
    api_up = up_check("http://127.0.0.1:8000/health")
    add("Stack (api/dashboard)", "REAL" if api_up and up_check("http://127.0.0.1:8081/") else "NOT CONNECTED",
        f"mode={mode}; origin {c['BB_ORIGIN']}" if api_up else "stack is down: scripts/manual_stack.sh up")
    # Okta
    have_idp = bool(e.get("FINAL_TEST_OIDC_CLIENT_ID") and e.get("FINAL_TEST_SAML_IDP_SSO_URL"))
    tun = container_running("bbmanual-web") and mode == "public" and tunnel_running()
    add("Okta SSO (SAML+OIDC) / SCIM", "REAL" if tun and have_idp else "NOT CONNECTED",
        "real Okta tenant; owner registered callback URLs and tunnel is up" if tun and have_idp else
        "Okta must call back to a public URL: needs `up public` + ngrok + URLs registered (see `okta`)" if have_idp else "IdP values missing")
    key = e.get("BUILDER_STRIPE_SECRET_KEY", "")
    add("Stripe checkout / portal", "REAL" if key.startswith(("sk_test_", "rk_test_")) else "NOT CONNECTED",
        "Stripe TEST mode API with your key; return URLs use the current origin" if key else "no Stripe key")
    fw = stripe_running()
    add("Stripe webhooks", "REAL" if fw else "NOT CONNECTED",
        "Stripe CLI forwarder running, signing secret applied to the API" if fw else
        "no endpoint registered at Stripe (by design); run `scripts/manual_stack.sh stripe` (events from checkout will then arrive)")
    smtp = ("REAL", "GoDaddy SMTP (smtpout.secureserver.net); lands in Spam, ~25 mails budget") if mail != "sink" and e.get("BUILDER_SMTP_HOST") else ("FAKE", "mail goes to Mailpit")
    add("SMTP (platform mail)", *smtp)
    add("Mailpit", "REAL" if container_running("bbmanual-mailpit") else "NOT CONNECTED",
        "http://127.0.0.1:8025 ; receives all mail only with BB_MAIL=sink" if mail == "sink" else "running but unused (MAIL=real); start with BB_MAIL=sink to use it")
    add("MinIO / S3 (SeaweedFS)", "REAL" if container_running("bbmanual-minio") else "NOT CONNECTED",
        f"{e.get('STORAGE_ENDPOINT_URL','')} bucket {e.get('STORAGE_BUCKET','')}: S3 API for generated projects (MinIO publishes no images: SeaweedFS, same as the generator)")
    add("Redis", "REAL" if container_running("bbmanual-redis") else "NOT CONNECTED", f"{e.get('REDIS_URL','')} for generated projects")
    add("ngrok tunnel", "REAL" if tunnel_running() else "NOT CONNECTED",
        e.get("FINAL_TEST_TUNNEL_API_URL", "") if tunnel_running() else "not running: `up public` or `tunnel start`")
    add("SMS", "FAKE", "FAKE provider (no SMS account)")
    has_key = bool(c.get("BUILDER_AI_API_KEY"))
    orgs = json.loads(c.get("BUILDER_AI_PLATFORM_KEY_ORGS", "[]"))
    add("AI model", "REAL" if has_key and orgs else "NOT CONNECTED",
        f"key present, enabled for {len(orgs)} org(s), capped" if has_key and orgs else
        ("key present in .env.local; run `enable-ai <org-slug>`" if has_key else "no BUILDER_AI_API_KEY in .env.local"))
    rs = runsc_available()
    sock = os.path.exists("/var/run/docker.sock")
    add("Previews / sandbox", "REAL" if sock and (rs or True) else "NOT CONNECTED",
        f"docker socket mounted (UNSAFE, local only); runtime={'runsc (gVisor)' if rs else 'runc (no gVisor: allowed only in local mode)'}; image bb-preview-app:1 "
        + ("present" if subprocess.run(["docker", "image", "inspect", "bb-preview-app:1"], capture_output=True).returncode == 0 else "MISSING"))
    add("Draft workspaces", "REAL", "git in image; workspace root + DB admin URL set; data in " + str(DATA))
    add("Workbench (dashboard)", "REAL" if mode == "local" else "NOT CONNECTED",
        "preview origin http://localhost:8799 baked into the dashboard" + ("" if mode == "local" else "; local-mode only (no second public hostname)"))
    add("Keycloak / OTLP", "NOT CONNECTED", "no container started (optional generator features)")
    w = max(len(r[0]) for r in rows)
    print(f"{'FEATURE':{w}}  {'STATUS':14}  REASON")
    for f, s, r in rows:
        print(f"{f:{w}}  {s:14}  {r}")


def tunnel_running() -> bool:
    p = STATE / "ngrok.pid"
    return p.exists() and Path(f"/proc/{p.read_text().strip()}").exists()


def stripe_running() -> bool:
    p = STATE / "stripe.pid"
    return p.exists() and Path(f"/proc/{p.read_text().strip()}").exists()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "run":
        cmd_run(rest)
    elif cmd == "get":
        print(compute().get(rest[0], load_env(ENV_FILE).get(rest[0], "")) if rest[0] in {
            "BB_ORIGIN", "BB_MODE", "BB_PREVIEW_ORIGIN", "BB_DATA", "BUILDER_SANDBOX_RUNTIME", "FINAL_TEST_TUNNEL_API_URL",
            "STORAGE_BUCKET", "FINAL_TEST_SSO_DOMAIN"} else "")
    elif cmd == "matrix":
        cmd_matrix()
    elif cmd == "seed":
        return cmd_seed()
    elif cmd == "okta":
        cmd_okta()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
