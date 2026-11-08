"""Dependency policy (B3-9, architecture section 8): curated sets, allow-list, gated unknowns.

Fail closed: a requirement is usable only if it is (1) in a curated set at that exact pin,
(2) an allow-listed name at an exact pin, or (3) an owner-approved request for that exact
name+version(+hashes). Everything else is blocked. Pure checks (`check_requirements`) do no I/O
and make no network calls; existence/age/licence/vuln checks belong to the later gate.
"""

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.exceptions import AppError
from app.models.dependency_policy import DependencyRequest

# -- policy data (reviewed in code, pinned exactly) -------------------------------------------
CURATED_SETS: dict[str, dict[str, str]] = {
    "web-core": {"fastapi": "0.115.6", "pydantic": "2.10.4", "uvicorn": "0.34.0"},
    "database": {"sqlalchemy": "2.0.36", "asyncpg": "0.30.0", "alembic": "1.14.0"},
    "http-client": {"httpx": "0.28.1"},
    "testing": {"pytest": "8.3.4", "pytest-asyncio": "0.25.0"},
}
# Vetted names that may be added at any exact pin without a human.
ALLOW_LIST: frozenset[str] = frozenset(
    {"orjson", "python-dateutil", "tenacity", "structlog", "email-validator", "phonenumbers"}
)
REQUEST_TTL = timedelta(days=14)

_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){0,3}(?:(?:a|b|rc)[0-9]{1,4})?"
    r"(?:\.post[0-9]{1,4})?(?:\.dev[0-9]{1,4})?$"
)
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_LINE_RE = re.compile(r"^(?P<name>[^=\s]+)\s*==\s*(?P<version>[^\s]+)(?P<rest>(?:\s+--hash=\S+)*)$")


_MANIFEST_NAMES = frozenset(
    {
        "pyproject.toml", "setup.py", "setup.cfg", "pipfile", "pipfile.lock", "poetry.lock", "pdm.lock", "uv.lock",
        "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
        "environment.yml", "environment.yaml", "conda.yml", "pip.conf", "tox.ini",
    }
)


def is_dependency_manifest(rel: str) -> bool:
    """True for any file that can declare or pin third-party packages (requirements and constraints lists
    in any spelling or folder, pyproject, setup, Pipfile, npm and lock files). Dependencies reach a project
    only through the policy (allow-list or owner approval), never through such a file written by hand."""
    parts = rel.replace("\\", "/").lower().split("/")
    name = parts[-1]
    if name in _MANIFEST_NAMES:
        return True
    if name.endswith((".txt", ".in")):
        return "requirements" in name or "constraints" in name or "requirements" in parts[:-1]
    return False


def normalize_name(name: str) -> str:
    """PEP 503 normalised name; rejects anything outside plain ASCII package-name syntax
    (so unicode homoglyphs, URLs, paths, extras and markers never normalise into a name)."""
    if len(name) > 100 or not name.isascii() or not _NAME_RE.fullmatch(name):
        raise ValueError("invalid package name")
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_version(version: str) -> str:
    if len(version) > 50 or not version.isascii() or not _VERSION_RE.fullmatch(version):
        raise ValueError("version must be one exact pin like 1.2.3 (no ranges, wildcards, local parts)")
    return version


def validate_hash(value: str) -> str:
    if not _HASH_RE.fullmatch(value):
        raise ValueError("hash must be sha256:<64 lowercase hex>")
    return value


def parse_requirement(line: str) -> tuple[str, str, list[str]]:
    """One `name==version [--hash=sha256:...]` line -> (normalised name, version, hashes)."""
    if not line.isascii() or any(ord(c) < 32 for c in line):
        raise ValueError("non-ascii or control characters")
    m = _LINE_RE.fullmatch(line.strip())
    if m is None:
        raise ValueError("expected exactly `name==version`")
    hashes = [h.removeprefix("--hash=") for h in m["rest"].split()]
    return (
        normalize_name(m["name"]),
        validate_version(m["version"]),
        [validate_hash(h) for h in hashes],
    )


@dataclass
class ReqVerdict:
    line: str
    allowed: bool
    package: str | None = None
    version: str | None = None
    source: str | None = None  # curated:<set> | allow_list | approved
    reason: str | None = None


@dataclass
class Verdict:
    ok: bool
    results: list[ReqVerdict] = field(default_factory=list)

    @property
    def blocked(self) -> list[ReqVerdict]:
        return [r for r in self.results if not r.allowed]


def _curated_source(name: str, version: str) -> str | None:
    for set_name in sorted(CURATED_SETS):
        if CURATED_SETS[set_name].get(name) == version:
            return f"curated:{set_name}"
    return None


Pin = tuple[str, str] | tuple[str, str, Iterable[str]]


def _approved_map(approved: Iterable[Pin]) -> dict[tuple[str, str], frozenset[str]]:
    out: dict[tuple[str, str], frozenset[str]] = {}
    for item in approved:
        name, version = item[0], item[1]
        hashes = frozenset(item[2]) if len(item) == 3 else frozenset()
        out[(name, version)] = out.get((name, version), frozenset()) | hashes
    return out


def _lines(requirements: str | Iterable[str]) -> list[object]:
    raw = requirements.splitlines() if isinstance(requirements, str) else list(requirements)
    return [r for r in raw if not (isinstance(r, str) and (not r.strip() or r.strip().startswith("#")))]


def check_requirements(
    requirements: str | Iterable[str],
    approved: Iterable[Pin] = (),
) -> Verdict:
    """Pure gate check. `approved` = (normalised name, version, hashes) for owner-approved pins that
    are neither expired nor revoked (the service filters those). An approved pin is usable only when
    the line carries `--hash=` values, all of them among the approved hashes. Any unparseable,
    unknown or unapproved line blocks the whole set."""
    approved_map = _approved_map(approved)
    results: list[ReqVerdict] = []
    for raw in _lines(requirements):
        if not isinstance(raw, str):
            results.append(ReqVerdict(repr(raw)[:80], False, reason="not a string"))
            continue
        stripped = raw.strip()
        try:
            name, version, hashes = parse_requirement(stripped)
        except ValueError as exc:
            results.append(ReqVerdict(stripped[:200], False, reason=f"rejected: {exc}"))
            continue
        source = _curated_source(name, version)
        if source is None and name in ALLOW_LIST:
            source = "allow_list"
        if source is None and (name, version) in approved_map:
            ok_hashes = approved_map[(name, version)]
            if not hashes or not ok_hashes or not set(hashes) <= ok_hashes:
                results.append(
                    ReqVerdict(
                        stripped, False, name, version,
                        reason="approved pin needs --hash values within the approved hashes",
                    )
                )
                continue
            source = "approved"
        if source is None:
            results.append(
                ReqVerdict(stripped, False, name, version, reason="unknown: request_dependency needed")
            )
        else:
            results.append(ReqVerdict(stripped, True, name, version, source))
    return Verdict(ok=all(r.allowed for r in results), results=results)


def verify_install_plan(
    requirements: str | Iterable[str],
    plan_hashes: Mapping[str, Iterable[str]],
    approved: Iterable[Pin] = (),
) -> Verdict:
    """Fail-closed check of what an installer will actually fetch. `plan_hashes` maps a package name
    to the artifact hashes the install resolved (`sha256:<hex>`). Passes only when check_requirements
    passes, every requirement line carries hashes, every planned hash is one the line names (and, for
    approved pins, one the owner approved), and nothing is planned that was not required."""
    base = check_requirements(requirements, approved)
    approved_map = _approved_map(approved)
    plan: dict[str, set[str]] = {}
    try:
        for k, v in plan_hashes.items():
            plan[normalize_name(k)] = {validate_hash(h) for h in v}
    except (ValueError, TypeError, AttributeError):
        return Verdict(False, [*base.results, ReqVerdict("<plan>", False, reason="malformed install plan")])
    results = list(base.results)
    seen: set[str] = set()
    for r in base.results:
        if not r.allowed or r.package is None or r.version is None:
            continue
        seen.add(r.package)
        _n, _v, line_hashes = parse_requirement(r.line)
        planned = plan.get(r.package, set())
        allowed = set(line_hashes)
        if r.source == "approved":
            allowed &= approved_map[(r.package, r.version)]
        if not line_hashes or not planned or not planned <= allowed:
            r.allowed = False
            r.reason = "install hashes missing or not matching the pinned hashes"
    for extra in sorted(set(plan) - seen):
        results.append(ReqVerdict(extra, False, extra, reason="planned but not required"))
    return Verdict(ok=all(r.allowed for r in results), results=results)


def is_active(row: DependencyRequest, now: datetime | None = None) -> bool:
    if row.status != "approved" or row.revoked_at is not None or row.expires_at is None:
        return False  # no expiry recorded = not trusted
    exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    return exp > (now or datetime.now(UTC))


# -- persistence -------------------------------------------------------------------------------
class DependencyPolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_requests(self, project_id: uuid.UUID) -> list[DependencyRequest]:
        q = select(DependencyRequest).where(DependencyRequest.project_id == project_id)
        return list((await self.session.execute(q.order_by(DependencyRequest.created_at.desc()))).scalars())

    async def approved_pins(self, project_id: uuid.UUID) -> list[DependencyRequest]:
        """Approved, unrevoked and unexpired pins only (expiry is re-checked on every read)."""
        q = select(DependencyRequest).where(
            DependencyRequest.project_id == project_id, DependencyRequest.status == "approved"
        )
        rows = (await self.session.execute(q.order_by(DependencyRequest.package))).scalars()
        return [r for r in rows if is_active(r)]

    async def check(self, project_id: uuid.UUID, requirements: str | Iterable[str]) -> Verdict:
        pins = [(r.package, r.version, r.hashes) for r in await self.approved_pins(project_id)]
        return check_requirements(requirements, pins)

    async def verify_plan(
        self, project_id: uuid.UUID, requirements: str | Iterable[str], plan_hashes: Mapping[str, Iterable[str]]
    ) -> Verdict:
        pins = [(r.package, r.version, r.hashes) for r in await self.approved_pins(project_id)]
        return verify_install_plan(requirements, plan_hashes, pins)

    async def revoke(
        self, project_id: uuid.UUID, request_id: uuid.UUID, revoker: uuid.UUID, note: str | None
    ) -> DependencyRequest:
        row = (
            await self.session.execute(
                select(DependencyRequest)
                .where(DependencyRequest.id == request_id, DependencyRequest.project_id == project_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise AppError("not_found", "not found", 404)
        if row.status != "approved":
            raise AppError("dependency_not_approved", f"request is {row.status}, not approved", 409)
        row.status = "revoked"
        row.revoked_by = revoker
        row.revoked_at = datetime.now(UTC)
        row.decision_note = note or row.decision_note
        await self.session.flush()
        return row

    async def request(
        self,
        project_id: uuid.UUID,
        package: str,
        version: str,
        reason: str,
        hashes: list[str],
        requested_by: uuid.UUID | None,
    ) -> tuple[DependencyRequest, bool]:
        try:
            name = normalize_name(package)
            ver = validate_version(version)
            hs = sorted({validate_hash(h) for h in hashes})
        except ValueError as exc:
            raise AppError("invalid_dependency", str(exc), 422) from exc
        if _curated_source(name, ver) is not None or name in ALLOW_LIST:
            raise AppError("dependency_already_allowed", "this pin is already allowed", 409)
        now = datetime.now(UTC)
        stale = (
            await self.session.execute(
                select(DependencyRequest).where(
                    DependencyRequest.project_id == project_id,
                    DependencyRequest.package == name,
                    DependencyRequest.version == ver,
                    DependencyRequest.status == "approved",
                )
            )
        ).scalars()
        for old in stale:
            if not is_active(old, now):
                old.status = "expired"  # frees the open-request slot for a fresh request
        await self.session.flush()
        existing = (
            await self.session.execute(
                select(DependencyRequest).where(
                    DependencyRequest.project_id == project_id,
                    DependencyRequest.package == name,
                    DependencyRequest.version == ver,
                    DependencyRequest.status.in_(("pending", "approved")),
                )
            )
        ).scalars().first()
        if existing is not None:
            return existing, False
        row = DependencyRequest(
            project_id=project_id,
            package=name,
            version=ver,
            reason=reason,
            hashes=hs,
            status="pending",
            requested_by=requested_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row, True

    async def decide(
        self,
        project_id: uuid.UUID,
        request_id: uuid.UUID,
        approve: bool,
        decider: uuid.UUID,
        expected_package: str | None = None,
        expected_version: str | None = None,
        expected_hashes: list[str] | None = None,
        note: str | None = None,
    ) -> DependencyRequest:
        row = (
            await self.session.execute(
                select(DependencyRequest)
                .where(DependencyRequest.id == request_id, DependencyRequest.project_id == project_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise AppError("not_found", "not found", 404)
        if row.status != "pending":
            raise AppError("dependency_request_decided", f"request is already {row.status}", 409)
        if approve:
            # The approver confirms exactly what they reviewed; anything changed since is refused.
            try:
                same = (
                    expected_package is not None
                    and expected_version is not None
                    and normalize_name(expected_package) == row.package
                    and expected_version == row.version
                    and sorted(expected_hashes or []) == sorted(row.hashes)
                )
            except ValueError:
                same = False
            if not same:
                raise AppError(
                    "dependency_approval_mismatch",
                    "the request differs from what was reviewed; review it again",
                    409,
                )
            created = row.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if datetime.now(UTC) - created > REQUEST_TTL:
                raise AppError("dependency_request_stale", "request is stale; ask again", 409)
        if approve and not row.hashes:
            raise AppError(
                "dependency_hashes_required", "an approved package needs recorded sha256 hashes", 409
            )
        row.status = "approved" if approve else "denied"
        if approve:
            days = get_settings().dependency_approval_ttl_days
            row.expires_at = datetime.now(UTC) + timedelta(days=days)
        row.decided_by = decider
        row.decided_at = datetime.now(UTC)
        row.decision_note = note
        await self.session.flush()
        return row
