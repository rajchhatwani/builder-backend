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


async def test_runc_refused_when_environment_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # S2-006: the default "local" must not unlock runc; only an explicit local/test does.
    monkeypatch.delenv("BUILDER_ENVIRONMENT", raising=False)
    unset = Settings(_env_file=None, sandbox_runtime="runc")  # type: ignore[call-arg]
    assert unset.environment == "local" and not unset.environment_explicit
    with pytest.raises(SandboxError, match="not isolated"):
        await DockerSandbox(unset).check_runtime()
    for env in ("local", "test"):
        explicit = Settings(_env_file=None, environment=env, sandbox_runtime="runc")  # type: ignore[call-arg]
        assert DockerSandbox(explicit)._allow_runc
    monkeypatch.setenv("BUILDER_ENVIRONMENT", "local")
    from_env = Settings(_env_file=None, sandbox_runtime="runc")  # type: ignore[call-arg]
    assert DockerSandbox(from_env)._allow_runc
    prod = Settings(_env_file=None, environment="production", sandbox_runtime="runc")  # type: ignore[call-arg]
    assert not DockerSandbox(prod)._allow_runc


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


# -- audit B1-025 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["LD_AUDIT", "LD_DEBUG", "GCONV_PATH", "GODEBUG", "HTTPS_PROXY", "ALL_PROXY",
             "SSL_CERT_FILE", "OTEL_EXPORTER_X", "NLSPATH", "LOCPATH", "HOSTALIASES"]
)
def test_cli_behaviour_env_names_refused(name: str) -> None:  # F-0226
    with pytest.raises(SandboxError):
        args(spec(env={name: "x"}))


@pytest.mark.parametrize("user", ["00", "00:00", "10001:0", "10001:00", "0000:5", "10001:10001\n"])
def test_root_user_forms_refused(user: str) -> None:  # F-0227
    with pytest.raises(SandboxError):
        args(spec(user=user))


def test_normal_user_and_env_still_accepted() -> None:
    a = args(spec(user="10001", env={"PYTHONUNBUFFERED": "1", "DATABASE_URL": "x"}))
    assert "10001" in a


async def test_reap_spares_young_empty_network_and_young_exited_container() -> None:  # F-0229
    box = DockerSandbox(Settings(environment="test"), runner_process=True)
    removed: list[tuple[str, ...]] = []

    async def fake(*a: str, **_: object) -> tuple[int, str, str]:
        if a[0] == "ps":
            return 0, "c-young|exited|\nc-old|exited|\n", ""
        if a[:2] == ("network", "ls"):
            return 0, "n-young|\nn-old|\n", ""
        if a[:2] == ("network", "inspect"):
            created = "2026-11-16T10:00:00.123456789Z" if a[2] == "n-old" else "2026-11-16T11:59:59.5Z"
            return 0, f"0|{created}", ""
        if a[0] == "inspect":
            fin = "2026-11-16T10:00:00Z" if a[-1] == "c-old" else "2026-11-16T11:59:59.9Z"
            return 0, fin, ""
        removed.append(a)
        return 0, "", ""

    box._docker = fake  # type: ignore[method-assign]
    import datetime as dt

    now = dt.datetime(2026, 11, 16, 12, 0, 0, tzinfo=dt.UTC).timestamp()
    res = await box.reap(now)
    assert res.containers == ["c-old"] and res.networks == ["n-old"]


async def test_reap_removes_old_empty_network_with_real_docker_created_shape() -> None:  # F-0950
    box = DockerSandbox(Settings(environment="test"), runner_process=True)
    removed: list[tuple[str, ...]] = []

    async def fake(*a: str, **_: object) -> tuple[int, str, str]:
        if a[0] == "ps":
            return 0, "", ""
        if a[:2] == ("network", "ls"):
            return 0, "n-old|\n", ""
        if a[:2] == ("network", "inspect"):
            fmt = a[-1]
            if "json .Created" in fmt:  # real docker: JSON-quoted RFC3339
                return 0, '0|"2026-11-16T10:00:00.678868047+05:30"\n', ""
            return 0, "0|2026-11-16 10:00:00.678868047 +0530 IST\n", ""  # go time.String()
        removed.append(a)
        return 0, "", ""

    box._docker = fake  # type: ignore[method-assign]
    import datetime as dt

    now = dt.datetime(2026, 11, 16, 12, 0, 0, tzinfo=dt.UTC).timestamp()
    res = await box.reap(now)
    assert res.networks == ["n-old"]


async def test_inspect_calls_are_container_typed() -> None:  # F-0951
    box = DockerSandbox(Settings(environment="test"), runner_process=True)
    calls: list[tuple[str, ...]] = []

    async def fake(*a: str, **_: object) -> tuple[int, str, str]:
        calls.append(a)
        if a[0] == "inspect" and "--type" not in a:  # would resolve to the same-named network
            return 1, "", "template parsing error: map has no entry for key State"
        return 1, "", "Error: No such container: bbsbx-x"

    box._docker = fake  # type: ignore[method-assign]
    assert await box.is_running("aaaabbbbccccdddd") is False
    assert await box.ip_of("aaaabbbbccccdddd", "net1") is None
    with pytest.raises(SandboxError):
        await box._verify_mounts("aaaabbbbccccdddd")
    inspects = [c for c in calls if c[0] == "inspect"]
    assert inspects and all(c[1:3] == ("--type", "container") for c in inspects)
