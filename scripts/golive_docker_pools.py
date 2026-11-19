"""P7 helper for golive_check.sh: does Docker hand out addresses from the sandbox subnet pool?

Usage: golive_docker_pools.py <daemon.json path> <sandbox pool CIDR>
Prints one line starting with OK, WARN or FAIL; exit code 1 only for FAIL. Reads a world-readable
file, needs no root, prints no secrets.

Docker's built-in default pools cover 172.17.0.0/16 .. 172.31.0.0/16, so with no
"default-address-pools" key in daemon.json a normal `docker network create` can take the range the
firewall reserves for sandboxes (default 172.30.0.0/16).
"""

import ipaddress
import json
import sys

BUILTIN = ipaddress.ip_network("172.16.0.0/12")


def check(daemon_json: str, sandbox_pool: str) -> tuple[str, str]:
    pool = ipaddress.ip_network(sandbox_pool, strict=False)
    try:
        with open(daemon_json, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        cfg = {}
    except (OSError, ValueError) as exc:
        return "WARN", f"cannot read {daemon_json} ({exc.__class__.__name__}); verify default-address-pools by hand"
    pools = cfg.get("default-address-pools") if isinstance(cfg, dict) else None
    if not pools:
        if pool.overlaps(BUILTIN):
            return (
                "WARN",
                f"daemon.json has no default-address-pools, so Docker may allocate {pool} to a normal network "
                "(set default-address-pools away from it, or set SANDBOX_SUBNET_POOL elsewhere)",
            )
        return "OK", f"sandbox pool {pool} is outside Docker's built-in pools"
    for entry in pools:
        try:
            base = ipaddress.ip_network(str(entry.get("base")), strict=False)
        except (AttributeError, ValueError):
            return "WARN", "default-address-pools has an entry that could not be parsed"
        if base.overlaps(pool):
            return "FAIL", f"default-address-pools entry {base} overlaps the sandbox pool {pool}"
    return "OK", f"default-address-pools do not overlap the sandbox pool {pool}"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("FAIL usage: golive_docker_pools.py <daemon.json> <pool-cidr>")
        return 1
    level, detail = check(argv[1], argv[2])
    print(f"{level} {detail}")
    return 1 if level == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
