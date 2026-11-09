"""P1 narrow runner: request validation, RemoteSandbox against an in-process runner with a fake
docker binary, and the fail-closed configuration. No real docker, no network."""

import json
import stat
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.sandbox import DockerSandbox, Limits, RemoteSandbox, SandboxError, SandboxSpec
from app.services.sandbox.factory import make_sandbox
from app.services.sandbox.runner import RunnerCore, create_app

TOKEN = "t0ken-" + "x" * 40  # not a real secret
ID = "a" * 16
FAKE_DOCKER = r'''#!{py}
import json, os, sys
st_path = {state!r}
st = json.load(open(st_path)) if os.path.exists(st_path) else {{"containers": {{}}, "networks": {{}}, "calls": []}}
a = sys.argv[1:]
st["calls"].append({{"args": a, "has_docker_host": "DOCKER_HOST" in os.environ}})
def done(rc=0, out="", err=""):
    json.dump(st, open(st_path, "w")); sys.stdout.write(out); sys.stderr.write(err); sys.exit(rc)
def labels(args):
    d = {{}}
    for i, x in enumerate(args):
        if x == "--label":
            k, _, v = args[i + 1].partition("="); d[k] = v
    return d
if a[:1] == ["info"]: done(0, '{{"runsc": {{}}}}')
if a[:2] == ["network", "create"]:
    st["networks"][a[-1]] = {{"internal": "--internal" in a, "labels": labels(a)}}; done()
if a[:2] == ["network", "inspect"]:
    n = st["networks"].get(a[2])
    if n is None: done(1, "", "no such network")
    done(0, ("true" if n["internal"] else "false") + "|" + n["labels"].get("bb.sandbox.id", ""))
if a[:2] == ["network", "ls"]:
    out = ""
    for name, n in st["networks"].items():
        want = [x for x in a if x.startswith("label=")]
        if all(n["labels"].get(w[6:].split("=")[0]) == (w[6:].split("=", 1)[1]) for w in want): out += name + "\n"
    done(0, out)
if a[:2] == ["network", "rm"]:
    st["networks"].pop(a[2], None); done()
if a[:1] == ["run"]:
    name = a[a.index("--name") + 1]
    if name in st["containers"]: done(125, "", "name in use")
    st["containers"][name] = {{"labels": labels(a), "args": a}}; done(0, "cid\n")
if a[:1] == ["inspect"]:
    c = st["containers"].get(a[-1])
    if c is None: done(1, "", "no such container")
    fmt = a[a.index("--format") + 1]
    if "json .State" in fmt: done(0, '{{"Running": true, "ExitCode": 0}}')
    if "IPAddress" in fmt: done(0, "10.9.0.2\n")
    done(0, c["labels"].get("bb.sandbox", "") + "\n")
if a[:1] == ["rm"]:
    st["containers"].pop(a[-1], None); done()
if a[:1] == ["logs"]: done(0, "hello\n")
if a[:1] == ["wait"]: done(0, "0\n")
if a[:1] == ["exec"]: done(0, "execout\n")
if a[:1] in (["stop"], ["kill"]): done()
if a[:1] == ["ps"]: done(0, "")
done(0)
'''


class Rig:
    def __init__(self, tmp: Path) -> None:
        self.root = tmp / "mounts"
        (self.root / "code").mkdir(parents=True)
        self.state = tmp / "state.json"
        self.bin = tmp / "fakedocker"
        self.bin.write_text(FAKE_DOCKER.format(py=sys.executable, state=str(self.state)))
        self.bin.chmod(self.bin.stat().st_mode | stat.S_IXUSR)
        self.settings = Settings(
            environment="test", runner_mount_root=str(self.root), sandbox_runtime="runsc",
            sandbox_docker_bin=str(self.bin),
        )
        box = DockerSandbox(self.settings, runner_process=True)
        self.app = create_app(self.settings, token=TOKEN, core=RunnerCore(self.settings, box), max_body=4096)
        self.transport = httpx.ASGITransport(app=self.app)
        self.api_settings = Settings(
            environment="production", sandbox_runner_url="http://127.0.0.1:8790",
            sandbox_runner_token=TOKEN,  # type: ignore[arg-type]
        )

    def remote(self) -> RemoteSandbox:
        return RemoteSandbox(self.api_settings, transport=self.transport)

    def st(self) -> dict:  # type: ignore[type-arg]
        return json.loads(self.state.read_text()) if self.state.exists() else {"calls": [], "containers": {}, "networks": {}}

    def verbs(self) -> list[str]:
        return [c["args"][0] for c in self.st()["calls"]]

    async def post(self, op: str, body: object, token: str | None = TOKEN, raw: bytes | None = None) -> httpx.Response:
        h = {"Authorization": f"Bearer {token}"} if token is not None else {}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://r") as c:
            if raw is not None:
                return await c.post(f"/v1/{op}", content=raw, headers=h)
            return await c.post(f"/v1/{op}", json=body, headers=h)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def spec_body(**kw: object) -> dict:  # type: ignore[type-arg]
    return {"spec": {"image": "python:3.12-slim", "sandbox_id": ID, **kw}}


# -- authentication and framing ----------------------------------------------------------------


async def test_missing_or_wrong_token_is_401_and_touches_nothing(rig: Rig) -> None:
    assert (await rig.post("state", {"sandbox_id": ID}, token=None)).status_code == 401
    assert (await rig.post("state", {"sandbox_id": ID}, token="wrong")).status_code == 401
    assert (await rig.post("state", {"sandbox_id": ID}, token=TOKEN[:-1])).status_code == 401
    assert rig.verbs() == []


def test_runner_refuses_to_start_without_a_strong_token(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BB_RUNNER_TOKEN", raising=False)
    with pytest.raises(SandboxError):
        create_app(rig.settings)
    with pytest.raises(SandboxError):
        create_app(rig.settings, token="short")


async def test_unknown_operation_unknown_field_and_oversize_are_refused(rig: Rig) -> None:
    assert (await rig.post("shell", {})).status_code == 404
    assert (await rig.post("state", {"sandbox_id": ID, "extra": 1})).status_code == 422
    assert (await rig.post("state", {"sandbox_id": "../etc"})).status_code == 422
    assert (await rig.post("state", None, raw=b"not json")).status_code == 422
    assert (await rig.post("exec", {"sandbox_id": ID, "argv": ["x" * 5000], "timeout": 1})).status_code == 413
    assert (await rig.post("exec", None, raw=b"{" + b" " * 9000 + b"}")).status_code == 413
    assert rig.verbs() == []


# -- hostile specs ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"labels": {"bb.sandbox": "0"}},  # callers cannot set labels
        {"privileged": True},
        {"cap_add": ["SYS_ADMIN"]},
        {"mounts": ["/:/host"]},
        {"publish": ["80:80"]},
        {"image": "evil/image:latest"},  # not on the allow-list
        {"image": "python:3.12-slim --privileged"},
        {"code_dir": "/etc"},
        {"code_dir": "/var/run/docker.sock"},
        {"code_dir": "__ROOT__/../outside"},
        {"code_dir": "__ROOT__"},  # the root itself is not a project dir
        {"env": {"DOCKER_HOST": "tcp://evil:2375"}},
        {"env": {"DOCKER_CONFIG": "/x"}},
        {"env": {"PATH": "/tmp"}},
        {"network": "host"},
        {"network": "bridge"},
        {"user": "0:0"},
        {"user": "root"},
        {"tmpfs": {"/workspace": "1m"}},
        {"limits": {"memory": "999g"}},
        {"limits": {"cpus": 64}},
    ],
)
async def test_hostile_start_specs_are_rejected_without_running_docker(rig: Rig, extra: dict) -> None:  # type: ignore[type-arg]
    extra = json.loads(json.dumps(extra).replace("__ROOT__", str(rig.root)))
    r = await rig.post("start", spec_body(**extra))
    assert r.status_code in (404, 422), r.text
    assert "run" not in rig.verbs()


async def test_symlink_under_root_pointing_outside_is_rejected(rig: Rig, tmp_path: Path) -> None:
    outside = tmp_path / "secret"
    outside.mkdir()
    (rig.root / "link").symlink_to(outside)
    assert (await rig.post("start", spec_body(code_dir=str(rig.root / "link")))).status_code == 422
    assert "run" not in rig.verbs()


async def test_no_mount_root_means_no_code_mounts(tmp_path: Path) -> None:
    s = Settings(environment="test", sandbox_docker_bin="/bin/false")
    r = Rig(tmp_path)
    app = create_app(s, token=TOKEN, core=RunnerCore(s, DockerSandbox(s, runner_process=True)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://r") as c:
        resp = await c.post("/v1/start", json=spec_body(code_dir=str(r.root / "code")),
                            headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 422


# -- RemoteSandbox through the runner ----------------------------------------------------------


async def test_remote_sandbox_full_lifecycle_uses_only_labelled_safe_docker_args(rig: Rig) -> None:
    box = rig.remote()
    code = rig.root / "code"
    secret_val = "v" + "9" * 12
    await box.check_runtime()
    sid = await box.start(SandboxSpec(image="python:3.12-slim", sandbox_id=ID, code_dir=code,
                                      command=["python", "-V"], env={"APP_KEY": secret_val}))
    assert sid == ID
    run_calls = [c for c in rig.st()["calls"] if c["args"][0] == "run"]
    assert len(run_calls) == 1
    args = run_calls[0]["args"]
    joined = " ".join(args)
    assert "bb.sandbox=1" in args and f"bb.sandbox.id={ID}" in args
    assert f"source={code.resolve()}" in joined and joined.count("--mount") == 1
    assert "--privileged" not in args and "docker.sock" not in joined and "--network host" not in joined
    assert secret_val not in joined  # env value never on the command line
    assert not any(c["has_docker_host"] for c in rig.st()["calls"])
    assert await box.is_running(ID) is True
    assert await box.ip_of(ID, "bbsbx-" + ID) == "10.9.0.2"
    assert "hello" in await box.logs(ID, tail=5)
    res = await box.exec(ID, ["echo", "x"], 5)
    assert res.exit_code == 0 and res.stdout == "execout\n"
    assert await box.create_network("b" * 16, Limits()) == "bbsbx-" + "b" * 16
    await box.stop(ID)
    await box.destroy(ID)
    assert "bbsbx-" + ID not in rig.st()["containers"]
    reaped = await box.reap()
    assert reaped.containers == [] and reaped.networks == []
    r = await box.run(SandboxSpec(image="python:3.12-slim", sandbox_id="c" * 16))
    assert r.sandbox_id == "c" * 16 and r.stdout == "hello\n"


async def test_remote_sandbox_surfaces_runner_refusals_as_sandbox_error(rig: Rig) -> None:
    box = rig.remote()
    with pytest.raises(SandboxError, match="refused"):
        await box.start(SandboxSpec(image="evil:1", sandbox_id=ID))
    with pytest.raises(SandboxError):
        await box.start(SandboxSpec(image="python:3.12-slim", sandbox_id=ID, code_dir=Path("/etc")))
    bad = Settings(environment="production", sandbox_runner_url="http://127.0.0.1:8790",
                   sandbox_runner_token="y" * 40)  # type: ignore[arg-type]
    with pytest.raises(SandboxError):
        await RemoteSandbox(bad, transport=rig.transport).check_runtime()  # wrong token -> 401


async def test_foreign_container_with_our_name_is_never_touched(rig: Rig) -> None:
    rig.state.write_text(json.dumps({"calls": [], "networks": {}, "containers": {
        "bbsbx-" + ID: {"labels": {}, "args": []}}}))
    box = rig.remote()
    await box.destroy(ID)
    with pytest.raises(SandboxError):
        await box.stop(ID)
    assert await box.is_running(ID) is False and await box.ip_of(ID, "n") is None
    assert "rm" not in rig.verbs() and "stop" not in rig.verbs()


async def test_remote_sandbox_never_spawns_a_process(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    box = rig.remote()  # built first: the runner side (in-process here) legitimately spawns
    real = asyncio.create_subprocess_exec
    seen: list[str] = []

    async def spy(prog: str, *a: str, **k: object):  # type: ignore[no-untyped-def]
        seen.append(prog)
        return await real(prog, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    monkeypatch.setenv("DOCKER_HOST", "tcp://evil:2375")
    await box.is_running(ID)
    # only the runner's own fake docker was spawned, and it did NOT inherit the caller's DOCKER_HOST
    # as an option: the CLI env is the runner process's own.
    assert seen == [str(rig.bin)]


# -- fail-closed configuration -------------------------------------------------------------------


def test_runner_url_requires_a_strong_token_and_a_safe_scheme() -> None:
    with pytest.raises(ValidationError):
        Settings(sandbox_runner_url="http://127.0.0.1:1")
    with pytest.raises(ValidationError):
        Settings(sandbox_runner_url="http://127.0.0.1:1", sandbox_runner_token="short")  # type: ignore[arg-type]
    for url in ("http://runner.example:80", "ftp://x", "tcp://127.0.0.1:1", "unix:relative"):
        with pytest.raises(ValidationError):
            Settings(sandbox_runner_url=url, sandbox_runner_token=TOKEN)  # type: ignore[arg-type]
    for url in ("http://127.0.0.1:8790", "unix:///run/bb/runner.sock", "https://runner.example"):
        assert Settings(sandbox_runner_url=url, sandbox_runner_token=TOKEN).sandbox_runner_url == url  # type: ignore[arg-type]


async def test_direct_docker_is_refused_when_runner_set_or_deployed(rig: Rig) -> None:
    with_runner = Settings(environment="test", sandbox_runner_url="http://127.0.0.1:1",
                           sandbox_runner_token=TOKEN, sandbox_docker_bin=str(rig.bin))  # type: ignore[arg-type]
    with pytest.raises(SandboxError, match="runner is configured"):
        await DockerSandbox(with_runner).is_running(ID)
    deployed = Settings(environment="production", sandbox_docker_bin=str(rig.bin))
    with pytest.raises(SandboxError, match="not allowed"):
        await DockerSandbox(deployed).is_running(ID)
    assert rig.verbs() == []  # the binary was never executed
    assert isinstance(make_sandbox(with_runner), RemoteSandbox)
    assert isinstance(make_sandbox(Settings(environment="test")), DockerSandbox)


def test_docker_env_names_are_not_forwardable_by_callers() -> None:
    from app.services.sandbox.docker import _validate

    for name in ("DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "HOME"):
        with pytest.raises(SandboxError):
            _validate(SandboxSpec(image="python:3.12-slim", sandbox_id=ID, env={name: "x"}))
