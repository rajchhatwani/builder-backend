"""Preview limits (B3-10): defaults, validated bounds, and the effective-limits resolver.

Pure functions, no I/O. Precedence: hard-coded defaults < platform settings row < per-org
override. The kill switch is platform-wide; an org can additionally be switched off
(`enabled=False` on its override row).
"""

from dataclasses import asdict, dataclass, fields

from app.exceptions import AppError

# key -> (minimum, maximum), inclusive. Admins can move values inside these bounds only.
BOUNDS: dict[str, tuple[float, float]] = {
    "max_live_per_user": (0, 20),
    "sleep_after_minutes": (1, 24 * 60),
    "delete_after_days": (1, 30),
    "cpus": (0.1, 2.0),
    "memory_mb": (128, 2048),
    "db_mb": (256, 1024),
    "rate_per_minute": (1, 6000),
}


@dataclass(frozen=True)
class PreviewLimits:
    max_live_per_user: int = 3
    sleep_after_minutes: int = 30
    delete_after_days: int = 14
    cpus: float = 0.5
    memory_mb: int = 512
    db_mb: int = 1024
    rate_per_minute: int = 300

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


KEYS = tuple(f.name for f in fields(PreviewLimits))
_INT_KEYS = frozenset(k for k in KEYS if k != "cpus")


def validate_limits(raw: dict[str, object], *, partial: bool = True) -> dict[str, float]:
    """Check keys, types and bounds. Unknown keys and out-of-range values raise 422."""
    out: dict[str, float] = {}
    for key, value in raw.items():
        if key not in BOUNDS:
            raise AppError("invalid_limit", f"unknown preview limit {key!r}", 422)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise AppError("invalid_limit", f"{key} must be a number", 422)
        if key in _INT_KEYS and float(value) != int(value):
            raise AppError("invalid_limit", f"{key} must be a whole number", 422)
        lo, hi = BOUNDS[key]
        if not (lo <= value <= hi):
            raise AppError("invalid_limit", f"{key} must be between {lo:g} and {hi:g}", 422)
        out[key] = int(value) if key in _INT_KEYS else float(value)
    if not partial:
        missing = [k for k in KEYS if k not in out]
        if missing:
            raise AppError("invalid_limit", f"missing limits: {', '.join(missing)}", 422)
    return out


def resolve(
    platform: dict[str, object] | None,
    org: dict[str, object] | None = None,
    allow_above_default: bool = False,
) -> PreviewLimits:
    """Defaults, then platform values, then org values. Stored values are re-validated, so a
    row edited by hand outside the bounds cannot widen anything (it is ignored). An org value
    above the platform default is clamped to it unless `allow_above_default` is set."""
    merged: dict[str, float] = PreviewLimits().as_dict()
    for key, value in (platform or {}).items():
        try:
            merged.update(validate_limits({key: value}))
        except AppError:
            continue
    base = dict(merged)
    for key, value in (org or {}).items():
        try:
            ok = validate_limits({key: value})
        except AppError:
            continue
        if not allow_above_default:
            ok = {k: min(v, base[k]) for k, v in ok.items()}
        merged.update(ok)
    return PreviewLimits(**merged)  # type: ignore[arg-type]


def check_org_overrides(
    platform: dict[str, object] | None, overrides: dict[str, float], allow_above_default: bool
) -> None:
    """Admin write check: without the explicit flag an override may not exceed the default."""
    if allow_above_default:
        return
    base = resolve(platform).as_dict()
    for key, value in overrides.items():
        if value > base[key]:
            raise AppError(
                "above_default",
                f"{key}={value:g} is above the platform default {base[key]:g}; "
                "set allow_above_default to permit it",
                422,
            )


@dataclass(frozen=True)
class Effective:
    limits: PreviewLimits
    enabled: bool  # False when the kill switch is on or the org is switched off
    reason: str | None = None  # "kill_switch" | "org_disabled"


def effective(
    kill_switch: bool,
    platform: dict[str, object] | None,
    org: dict[str, object] | None = None,
    org_enabled: bool = True,
    allow_above_default: bool = False,
) -> Effective:
    limits = resolve(platform, org, allow_above_default)
    if kill_switch:
        return Effective(limits, False, "kill_switch")
    if not org_enabled:
        return Effective(limits, False, "org_disabled")
    return Effective(limits, True)
