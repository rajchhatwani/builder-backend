"""CP-4B: sandbox networks get an explicit subnet from the dedicated pool (firewall covers the range)."""

import ipaddress

import pytest

from app.config import Settings
from app.services.sandbox import DockerSandbox, SandboxError
from app.services.sandbox.subnets import parse_pool, parse_used, pick_subnet

POOL = parse_pool("172.30.0.0/16", 28)


def test_pick_is_inside_pool_and_skips_used() -> None:
    first = pick_subnet(POOL, 28, [], start=0)
    assert first == "172.30.0.0/28"
    used = parse_used(["172.30.0.0/28", "172.30.0.16/28", "garbage", "fd00::/64"])
    assert len(used) == 2
    assert pick_subnet(POOL, 28, used, start=0) == "172.30.0.32/28"


def test_overlapping_larger_foreign_network_is_avoided() -> None:
    used = parse_used(["172.30.0.0/24"])  # a foreign docker network covering 16 blocks
    got = ipaddress.ip_network(pick_subnet(POOL, 28, used, start=0))
    assert got.subnet_of(POOL) and not got.overlaps(used[0])


def test_random_pick_always_inside_pool() -> None:
    for _ in range(200):
        assert ipaddress.ip_network(pick_subnet(POOL, 28, [])).subnet_of(POOL)


def test_exhausted_pool_fails_closed() -> None:
    small = parse_pool("172.30.0.0/26", 28)  # 4 blocks
    used = parse_used(["172.30.0.0/26"])
    with pytest.raises(SandboxError, match="exhausted"):
        pick_subnet(small, 28, used)


@pytest.mark.parametrize(
    ("pool", "prefix"),
    [("8.8.8.0/24", 28), ("169.254.0.0/16", 28), ("fd00::/48", 28), ("172.30.0.0/16", 8),
     ("172.30.0.0/16", 31), ("10.0.0.0/8", 28), ("172.30.0.0/27", 28), ("nonsense", 28),
     ("172.30.0.1/16", 28)],
)  # fmt: skip
def test_bad_pool_refused(pool: str, prefix: int) -> None:
    with pytest.raises(SandboxError):
        parse_pool(pool, prefix)


async def test_create_network_passes_subnet_and_retries_on_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = DockerSandbox(Settings(environment="test"))
    calls: list[tuple[str, ...]] = []
    creates = 0

    async def fake(*a: str, **k: object) -> tuple[int, str, str]:
        nonlocal creates
        calls.append(a)
        if a[:2] == ("network", "ls"):
            return 0, "id1\n", ""
        if a[:2] == ("network", "inspect"):
            return 0, "172.17.0.0/16 172.30.0.0/28 ", ""
        creates += 1
        if creates == 1:
            return 1, "", "Pool overlaps with other one on this address space"
        return 0, "", ""

    monkeypatch.setattr(box, "_docker", fake)
    name = await box.create_network("a" * 16)
    assert name == "bbsbx-" + "a" * 16
    made = [c for c in calls if c[:2] == ("network", "create")]
    assert len(made) == 2
    for c in made:
        subnet = ipaddress.ip_network(c[c.index("--subnet") + 1])
        assert subnet.subnet_of(ipaddress.ip_network("172.30.0.0/16"))
        assert not subnet.overlaps(ipaddress.ip_network("172.30.0.0/28"))
        assert "--internal" in c


async def test_create_network_other_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = DockerSandbox(Settings(environment="test"))
    n = 0

    async def fake(*a: str, **k: object) -> tuple[int, str, str]:
        nonlocal n
        if a[:2] in (("network", "ls"), ("network", "inspect")):
            return 0, "", ""
        n += 1
        return 1, "", "permission denied"

    monkeypatch.setattr(box, "_docker", fake)
    with pytest.raises(SandboxError):
        await box.create_network("b" * 16)
    assert n == 1


def test_bad_pool_in_settings_fails_when_sandbox_is_built() -> None:
    with pytest.raises(SandboxError):
        DockerSandbox(Settings(environment="test", sandbox_subnet_pool="8.8.0.0/16"))


def test_firewall_script_matches_the_pool_not_bridges() -> None:
    """The root scripts cannot run in CI; pin their shape: range match, no per-bridge rules."""
    from pathlib import Path

    fw = Path("scripts/sandbox_firewall.sh").read_text()
    hc = Path("scripts/sandbox_hostile_check.sh").read_text()
    assert 'POOL=${SANDBOX_SUBNET_POOL:-172.30.0.0/16}' in fw
    assert 'iptables -A "$NEWIN" -s "$POOL"' in fw and '-s "$POOL" -d 169.254.169.254/32' in fw
    assert "-i \"$br\"" not in fw and "br-${id" not in fw
    assert "--subnet" in hc and "reapply" not in hc.split("set -uo pipefail")[1]
    assert Settings().sandbox_subnet_pool == "172.30.0.0/16"
