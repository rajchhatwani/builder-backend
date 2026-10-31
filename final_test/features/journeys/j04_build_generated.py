"""Push a spec through the real API, download the zip, build a venv, migrate, run the generated tests, boot it, hit endpoints.
usage: j04_build_generated.py <fixture-name> [port]"""
from lib import *
import subprocess, shutil, zipfile, io, urllib.request, tempfile, time
FIX = pathlib.Path(os.environ.get("BBF_FIX", HERE.parents[2] / "tests" / "fixtures" / "specs"))
name = sys.argv[1]; port = int(sys.argv[2]) if len(sys.argv) > 2 else 9100
W = pathlib.Path("/tmp/claude-1000/-mnt-files-projects-builder-backend/268a2991-143d-476f-850d-216da54397b5/scratchpad/builds") / name
shutil.rmtree(W, ignore_errors=True); W.mkdir(parents=True)
J = "J4.build." + name
em, t = user("b" + name[:6])
spec = json.loads((FIX / f"{name}.json").read_text())
c, b, _ = call(t, "POST", "/projects", {"name": "bb-proj-" + name.replace("_", "-"), "slug": "bbp-" + name.replace("_", "-") + "-" + RUN}); pid = b["id"]
spec["project"]["slug"] = b["slug"]; spec["project"]["name"] = b["name"]
c, b, _ = call(t, "PUT", f"/projects/{pid}/spec", spec); expect(J + ".put_spec", "PUT fixture spec", (c, b, _), 200)
c, b, _ = call(t, "POST", f"/projects/{pid}/validate"); rec(J + ".validate", "spec validates", c == 200 and b.get("valid"), json.dumps(b)[:400])
c, b, _ = call(t, "POST", f"/projects/{pid}/generate/preview"); rec(J + ".preview", "preview lists files", c == 200 and b.get("total_files", 0) > 10, f"{c} files={b.get('total_files')}")
r = urllib.request.Request(A.base + f"/projects/{pid}/generate/download", headers={"Authorization": "Bearer " + t})
z = urllib.request.urlopen(r).read(); zipfile.ZipFile(io.BytesIO(z)).extractall(W / "src")
root = next((W / "src").iterdir()); rec(J + ".zip", "zip extracts", True, f"{len(z)} bytes -> {root.name}")
cfg = root / "app/auth/config.py"
if cfg.exists():  # point the generated mailer at Mailpit (the host is a constant in generated code, which is the user's to edit)
    t_ = cfg.read_text().replace("SMTP_HOST = 'smtp.example.com'", "SMTP_HOST = '127.0.0.1'").replace("SMTP_PORT = 587", "SMTP_PORT = 1025").replace("SMTP_USE_TLS = True", "SMTP_USE_TLS = False").replace("LOGIN_RATE_LIMIT = '5/15minutes'", "LOGIN_RATE_LIMIT = '25/15minutes'").replace("RESET_RATE_LIMIT = '3/hour'", "RESET_RATE_LIMIT = '30/hour'")
    cfg.write_text(t_)
dbn = ("bbf_" + name + "_" + RUN).lower()
def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, timeout=k.pop("timeout", 900), **k)
for d in (dbn, dbn + "_test"):
    sh("docker", "exec", "bb-final-pg", "psql", "-U", "builder", "-d", "postgres", "-c", f'create database "{d}"')
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
r = sh("uv", "venv", "--python", "3.12", str(W / "venv")); rec(J + ".venv", "venv", r.returncode == 0, r.stderr[-300:])
py = str(W / "venv/bin/python")
reqs = ["-r", "requirements.txt"] + (["-r", "requirements-dev.txt"] if (root / "requirements-dev.txt").exists() else [])
r = sh("uv", "pip", "install", "--python", py, *reqs, cwd=root, timeout=900); rec(J + ".install", "pip install generated requirements", r.returncode == 0, r.stderr[-500:])
def url(db): return f"postgresql+asyncpg://builder:builder@127.0.0.1:5432/{db}"
# project may need extra env (see .env.example): feed it
extra = {}
for line in (root / ".env.example").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); extra[k.strip()] = v.strip()
extra.pop("DATABASE_URL", None)
import secrets as _s
extra["AUTH_JWT_SECRET"] = _s.token_urlsafe(40)
if "STRIPE_SECRET_KEY" in extra:
    _ev = bb.env(); extra["STRIPE_SECRET_KEY"] = _ev.get("BUILDER_STRIPE_SECRET_KEY", ""); extra["STRIPE_WEBHOOK_SECRETS"] = "whsec_" + _s.token_hex(16)
e = {**env, **extra, "DATABASE_URL": url(dbn)}
r = sh(py, "-m", "alembic", "upgrade", "head", cwd=root, env=e); rec(J + ".migrate", "alembic upgrade head", r.returncode == 0, (r.stdout + r.stderr)[-600:])
et = {**env, **extra, "DATABASE_URL": url(dbn + "_test")}
if (root / "tests/_prepare_db.py").exists():
    sh(py, "-m", "tests._prepare_db", cwd=root, env=et)
sh(py, "-m", "alembic", "upgrade", "head", cwd=root, env=et)
r = sh(py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", cwd=root, env=et, timeout=900)
rec(J + ".pytest", "generated project's own tests pass", r.returncode == 0, (r.stdout + r.stderr)[-800:])
open(W / "pytest.log", "w").write(redact(r.stdout + r.stderr))
srv = subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=root, env=e, stdout=open(W / "server.log", "w"), stderr=subprocess.STDOUT)
try:
    base = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try: urllib.request.urlopen(base + "/health", timeout=2); break
        except Exception: time.sleep(1)
    def g(m, p, body=None, hd=None):
        rq = urllib.request.Request(base + p, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json", **(hd or {})}, method=m)
        try:
            x = urllib.request.urlopen(rq, timeout=60); raw = x.read(); return x.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as ex:
            raw = ex.read()
            try: return ex.code, json.loads(raw)
            except Exception: return ex.code, {}
    s, bd = g("GET", "/health"); rec(J + ".health", "GET /health 200", s == 200, str(s))
    s, bd = g("GET", "/ready"); rec(J + ".ready", "GET /ready 200 (db)", s == 200, str(s))
    s, bd = g("GET", "/openapi.json"); paths = sorted(bd.get("paths", {})) if s == 200 else []
    rec(J + ".openapi", "generated OpenAPI served", s == 200, f"{len(paths)} paths")
    json.dump({"paths": paths}, open(W / "paths.json", "w"))
    print("PATHS", paths)
    open(W / "base.txt", "w").write(base)
    time.sleep(0) 
    globals()["g"] = g
    if len(sys.argv) > 3:
        exec(open(sys.argv[3]).read())
finally:
    srv.terminate(); srv.wait(10)
