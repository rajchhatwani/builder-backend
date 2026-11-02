"""B3-4: Sandbox limits and docker command construction. No docker needed."""

from pathlib import Path

import pytest

from app.config import Settings
from app.services.sandbox import DockerSandbox, Limits, SandboxError, SandboxSpec, build_run_args


def args(spec: SandboxSpec, runtime: str = "runsc", network: str = "net1") -> list[str]:
    return build_run_args(spec, runtime, network, now=1000.0)


def spec(**kw: object) -> SandboxSpec:
    return SandboxSpec(image="python:3.12-slim", sandbox_id="a" * 16, **kw)  # type: ignore[arg-type]


def test_default_flags_match_spike() -> None:
    a = args(spec(command=["python", "-c", "pass"]))
    joined = " ".join(a)
    for flag in (
        "--runtime runsc", "--network net1", "--read-only", "--cap-drop ALL",
        "--security-opt no-new-privileges", "--pids-limit 100", "--memory 512m",
        "--memory-swap 512m", "--cpus 0.5", "--user 10001:10001",
    ):  # fmt: skip
        assert flag in joined
    assert any(x.startswith("/tmp:rw,noexec,nosuid,nodev,size=64m") for x in a)
    assert "bb.sandbox=1" in a and "bb.sandbox.expires=4600" in a
    assert a[-3:] == ["python", "-c", "pass"]


def test_never_privileged_socket_or_host_network() -> None:
    a = args(spec())
    joined = " ".join(a)
    assert "--privileged" not in a and "docker.sock" not in joined
    assert "--network host" not in joined and "--publish" not in a and "-p" not in a
    assert "--mount" not in a  # no mounts at all without code_dir


def test_code_mount_is_single_and_readonly(tmp_path: Path) -> None:
    a = args(spec(code_dir=tmp_path))
    mounts = [a[i + 1] for i, x in enumerate(a) if x == "--mount"]
    assert len(mounts) == 1 and mounts[0].endswith("target=/workspace,readonly")
    with pytest.raises(SandboxError):
        args(spec(code_dir=tmp_path / "missing"))


def test_env_values_never_on_command_line() -> None:
    a = args(spec(env={"DB_PASSWORD": "hunter2-secret"}))
    assert "hunter2-secret" not in " ".join(a)
    assert a[a.index("-e") + 1] == "DB_PASSWORD"


@pytest.mark.parametrize("name", ["PATH", "DOCKER_HOST", "lower", "A B", "BB_SANDBOX_X"])
def test_bad_env_names_refused(name: str) -> None:
    with pytest.raises(SandboxError):
        args(spec(env={name: "x"}))


def test_extra_hosts_and_tmpfs_validated() -> None:
    a = args(spec(extra_hosts={"db": "10.0.0.5"}, tmpfs={"/var/lib/postgresql/data": "256m"}))
    assert "db:10.0.0.5" in a and "/var/lib/postgresql/data:rw,nosuid,nodev,size=256m" in a
    for bad in ({"db": "not-an-ip"}, {"d;b": "10.0.0.5"}):
        with pytest.raises(SandboxError):
            args(spec(extra_hosts=bad))
    for bad_path in ("/", "relative", "/a/../b", "/x,y"):
        with pytest.raises(SandboxError):
            args(spec(tmpfs={bad_path: "1m"}))


@pytest.mark.parametrize(
    "limits",
    [
        Limits(cpus=0), Limits(cpus=64), Limits(memory="64g"), Limits(memory="1"),
        Limits(memory="abc"), Limits(pids=0), Limits(pids=10**6), Limits(wall_seconds=0),
        Limits(ttl_seconds=10**9),
    ],
)  # fmt: skip
def test_unsafe_limits_refused(limits: Limits) -> None:
    with pytest.raises(SandboxError):
        args(spec(limits=limits))


@pytest.mark.parametrize("user", ["0", "0:0", "root", "10001:abc"])
def test_root_user_refused(user: str) -> None:
    with pytest.raises(SandboxError):
        args(spec(user=user))


@pytest.mark.parametrize("image", ["", "--privileged", "a b", "x;rm", "UPPER"])
def test_bad_image_refused(image: str) -> None:
    with pytest.raises(SandboxError):
        args(SandboxSpec(image=image, sandbox_id="b" * 16))


def test_bad_sandbox_id_refused() -> None:
    with pytest.raises(SandboxError):
        args(SandboxSpec(image="alpine", sandbox_id="../etc"))


async def test_runc_refused_outside_local_test() -> None:
    prod = DockerSandbox(Settings(environment="production", sandbox_runtime="runc"))
    with pytest.raises(SandboxError):
        await prod.check_runtime()


async def test_unregistered_runtime_fails_closed() -> None:
    box = DockerSandbox(Settings(environment="local", sandbox_runtime="no-such-runtime"))
    with pytest.raises(SandboxError):
        await box.check_runtime()


# -- SENTINEL B3-4 fix round -----------------------------------------------------------------


def test_image_must_be_on_allowlist_and_never_pulled() -> None:
    a = args(spec())
    assert a[a.index("--pull") + 1] == "never"
    for image in ("evil.example/x:1", "localhost:5000/img", "python:3.11"):
        with pytest.raises(SandboxError):
            args(SandboxSpec(image=image, sandbox_id="c" * 16))
    # an explicit allowlist wins over the default one
    ok = build_run_args(
        SandboxSpec(image="reg/x@sha256:" + "a" * 64, sandbox_id="c" * 16),
        "runsc", "n", allowed_images={"reg/x@sha256:" + "a" * 64},
    )  # fmt: skip
    assert ok[-1].startswith("reg/x@sha256:")


@pytest.mark.parametrize("net", ["host", "none", "bridge", "container:abc", "default"])
def test_host_and_container_networks_refused_in_build_run_args(net: str) -> None:
    with pytest.raises(SandboxError):
        args(spec(), network=net)
    with pytest.raises(SandboxError):
        args(spec(network=net))


@pytest.mark.parametrize("path", ["/proc", "/dev/shm", "/workspace", "/tmp", "/sys/x"])
def test_tmpfs_over_system_paths_refused(path: str) -> None:
    with pytest.raises(SandboxError):
        args(spec(tmpfs={path: "1m"}))
    with pytest.raises(SandboxError):
        args(spec(tmpfs={"/data": "64g"}))


async def test_supplied_network_must_be_owned_by_this_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = DockerSandbox(Settings(environment="test"))
    answers = iter(["true|" + "d" * 16, "true|" + "e" * 16, "false|" + "d" * 16, "true|"])

    async def fake(*a: str, **k: object) -> tuple[int, str, str]:
        return 0, next(answers), ""

    monkeypatch.setattr(box, "_docker", fake)
    await box._ensure_owned_internal("n", "d" * 16)  # ours and internal
    for _ in range(3):  # another tenant's / not internal / unlabelled
        with pytest.raises(SandboxError):
            await box._ensure_owned_internal("n", "d" * 16)


async def test_reaper_hook_raises_when_daemon_cannot_be_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = DockerSandbox(Settings(environment="test"))

    async def fail(*a: str, **k: object) -> tuple[int, str, str]:
        return 1, "", "boom"

    monkeypatch.setattr(box, "_docker", fail)
    with pytest.raises(SandboxError):
        await box.reap()
    assert Settings().sandbox_reap_interval_seconds > 0


def test_shared_preview_network_owner_and_tmpfs_uid() -> None:
    """B3-10: app + db of one preview share a network owned by the db sandbox id; the db data
    dir is a tmpfs owned by the postgres uid. Both stay validated."""
    s = spec(
        network_owner="b" * 16, tmpfs_uid=70,
        tmpfs={"/var/lib/postgresql/data": "256m", "/var/run/postgresql": "8m"},
    )  # fmt: skip
    a = args(s)
    assert "/var/lib/postgresql/data:rw,nosuid,nodev,size=256m,uid=70,gid=70,mode=0700" in a
    assert "/var/run/postgresql:rw,nosuid,nodev,size=8m,uid=70,gid=70,mode=0755" in a
    for bad in ({"network_owner": "not hex!"}, {"tmpfs_uid": 0}, {"tmpfs_uid": 70000}):
        with pytest.raises(SandboxError):
            args(spec(**bad))
