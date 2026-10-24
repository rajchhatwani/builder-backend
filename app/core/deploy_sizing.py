"""Deployment sizing: turns an environment's profile and overrides into the numbers a cloud needs.

Same idea as `payments_sizing`: a profile fills what the owner left empty; an override wins.
Everything is data, so the dashboard can preview the result and the generator writes it into
`environments/<name>.tfvars`; changing capacity later is editing numbers in that file, never code.

CPU is in millicores (1000 = one vCPU) and memory in MB. Not every pair is valid on every platform
(Fargate, Container Apps and Cloud Run each accept a fixed set): `valid_combo` is the one check.
"""

import re
from dataclasses import dataclass

CLOUDS = ("aws", "azure", "gcp")
PROFILES = ("small", "medium", "large")
ENV_NAME_RE = re.compile(r"[a-z][a-z0-9]{1,11}")
REGION_RE = {
    "aws": re.compile(r"[a-z]{2}(?:-[a-z]+)+-\d"),
    "azure": re.compile(r"[a-z][a-z0-9]{3,24}"),
    "gcp": re.compile(r"[a-z]+-[a-z]+\d+"),
}
REPO_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")
MAX_ENVIRONMENTS = 6

# (cpu millicores, memory MB) pairs each platform accepts, smallest first.
_COMBOS = {
    # Fargate: 256 CPU units and up; these are the pairs worth offering for a Python API.
    "aws": (
        (512, 1024),
        (512, 2048),
        (1024, 2048),
        (1024, 4096),
        (2048, 4096),
        (2048, 8192),
        (4096, 8192),
    ),
    # Container Apps (consumption): whole list of combinations the service documents.
    "azure": ((500, 1024), (1000, 2048), (1500, 3072), (2000, 4096)),
    # Cloud Run: at least one vCPU keeps request concurrency and CPU always available predictable.
    "gcp": ((1000, 1024), (1000, 2048), (2000, 2048), (2000, 4096), (4000, 8192)),
}


@dataclass(frozen=True)
class Profile:
    cpu: int
    memory: int
    min_instances: int
    max_instances: int
    db_storage_gb: int
    db_size: str  # small | medium | large, mapped to a class per cloud below


_PROFILES = {
    "small": Profile(512, 1024, 1, 2, 20, "small"),
    "medium": Profile(1024, 2048, 2, 6, 50, "medium"),
    "large": Profile(2048, 4096, 3, 20, 100, "large"),
}
# GCP and Azure have different CPU steps: the profile's pair is moved to the nearest valid one.
_PROFILE_COMBO = {
    "aws": {"small": (512, 1024), "medium": (1024, 2048), "large": (2048, 4096)},
    "azure": {"small": (500, 1024), "medium": (1000, 2048), "large": (2000, 4096)},
    "gcp": {"small": (1000, 1024), "medium": (1000, 2048), "large": (2000, 4096)},
}
DB_CLASSES = {
    "aws": {"small": "db.t4g.small", "medium": "db.m7g.large", "large": "db.m7g.xlarge"},
    "azure": {
        "small": "B_Standard_B1ms",
        "medium": "GP_Standard_D2ds_v5",
        "large": "GP_Standard_D4ds_v5",
    },
    "gcp": {
        "small": "db-custom-1-3840",
        "medium": "db-custom-2-7680",
        "large": "db-custom-4-15360",
    },
}


@dataclass(frozen=True)
class Resolved:
    name: str
    profile: str
    cpu: int
    memory: int
    min_instances: int
    max_instances: int
    db_class: str
    db_storage_gb: int
    db_high_availability: bool
    deletion_protection: bool


def valid_combo(cloud: str, cpu: int, memory: int) -> bool:
    return (cpu, memory) in _COMBOS.get(cloud, ())


def combos(cloud: str) -> list[tuple[int, int]]:
    return list(_COMBOS.get(cloud, ()))


def resolve(
    cloud: str,
    name: str,
    profile: str,
    *,
    cpu: int | None = None,
    memory: int | None = None,
    min_instances: int | None = None,
    max_instances: int | None = None,
    db_storage_gb: int | None = None,
    db_high_availability: bool | None = None,
    deletion_protection: bool | None = None,
) -> Resolved:
    """Concrete numbers for one environment. Unknown profile or cloud raises KeyError (validation
    reports those first)."""
    base = _PROFILES[profile]
    pair = _PROFILE_COMBO[cloud][profile]
    return Resolved(
        name=name,
        profile=profile,
        cpu=cpu if cpu is not None else pair[0],
        memory=memory if memory is not None else pair[1],
        min_instances=min_instances if min_instances is not None else base.min_instances,
        max_instances=max_instances if max_instances is not None else base.max_instances,
        db_class=DB_CLASSES[cloud][base.db_size],
        db_storage_gb=db_storage_gb if db_storage_gb is not None else base.db_storage_gb,
        # Production needs a standby database and a delete lock; cheap environments skip them.
        db_high_availability=(
            db_high_availability if db_high_availability is not None else profile != "small"
        ),
        deletion_protection=(
            deletion_protection if deletion_protection is not None else name == "prod"
        ),
    )


def assignments(pairs: list[tuple[str, str]]) -> str:
    """`name = value` lines aligned the way `terraform fmt` aligns a block of attributes."""
    width = max(len(name) for name, _ in pairs)
    return "".join(f"{name.ljust(width)} = {value}\n" for name, value in pairs)


def tfvars_text(region: str, r: Resolved, app_env: str = "production") -> str:
    """The contents of environments/<name>.tfvars: plain numbers an operator can edit by hand."""

    def flag(value: bool) -> str:
        return "true" if value else "false"

    return (
        f"# {r.name}: generated from the project spec (profile {r.profile}).\n"
        "# Edit the numbers to change capacity (cpu in millicores, memory in MB):\n"
        "# no code change or rebuild is needed.\n"
        + assignments(
            [
                ("environment", f'"{r.name}"'),
                ("region", f'"{region}"'),
                ("cpu", str(r.cpu)),
                ("memory", str(r.memory)),
                ("min_instances", str(r.min_instances)),
                ("max_instances", str(r.max_instances)),
                ("db_class", f'"{r.db_class}"'),
                ("db_storage_gb", str(r.db_storage_gb)),
                ("db_high_availability", flag(r.db_high_availability)),
                ("deletion_protection", flag(r.deletion_protection)),
                ("app_env", f'"{app_env}"'),
            ]
        )
    )
