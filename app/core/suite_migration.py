"""Suite identity, path (b): an existing app moves its users to the suite hub (pure, spec level).

The builder never reads end-user identities. This module only reasons about the SPEC: which
transitions of `auth.suite.migration` are allowed, whether the dual window is well formed, and what
the move would change (the impact report). The data-level steps are CLI commands the customer runs
inside their own app over identity-v1 files (`python -m app.auth.export ...`).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.spec_models import Spec, SpecSuiteMigration
from app.core.suite_identity import hub_base_url, suite_realm

STATES = ("legacy_read_only", "dual", "hub_only")
MAX_DUAL_DAYS = 90
MAX_DUAL_WINDOW = timedelta(days=MAX_DUAL_DAYS)

# `claims["sub"]`, `token['sub']`, `claims.get("sub")`: code that treats the subject as a user id.
_SUB_READ = re.compile(r"""(\[\s*["']sub["']\s*\]|\.get\(\s*["']sub["'])""")
_MAX_SOURCE_BYTES = 200_000
_MAX_FINDINGS = 50


@dataclass(frozen=True)
class SubReader:
    path: str
    line: int
    text: str


def scan_sub_readers(sources: Mapping[str, str]) -> list[SubReader]:
    """Lines of hook / custom code that read the token subject directly. Under a hub the subject
    is the hub's id for the person, not this app's user id: such code must take a Principal."""
    found: list[SubReader] = []
    for path in sorted(sources):
        text = sources[path][:_MAX_SOURCE_BYTES]
        for number, line in enumerate(text.splitlines(), start=1):
            if _SUB_READ.search(line):
                found.append(SubReader(path, number, line.strip()[:200]))
                if len(found) >= _MAX_FINDINGS:
                    return found
    return found


def state_rank(state: str | None) -> int:
    """-1 for 'no migration yet', then the position in STATES."""
    return -1 if state is None else STATES.index(state)


def transition_problem(
    current: SpecSuiteMigration | None, requested: SpecSuiteMigration
) -> str | None:
    """Why `requested` may not replace `current`, or None. Moves are forward and one step at a
    time (none -> legacy_read_only -> dual -> hub_only); the same state may be rewritten (for the
    window or the issuer) except hub_only, which is terminal."""
    if requested.state not in STATES:
        return "state must be legacy_read_only, dual or hub_only"
    now_rank = state_rank(current.state if current else None)
    want = state_rank(requested.state)
    if current is not None and current.state == "hub_only":
        if requested == current:
            return None
        return "hub_only is final: legacy sign-in is closed and cannot be reopened"
    if want < now_rank:
        return f"cannot go back from {current.state if current else 'none'} to {requested.state}"
    if want > now_rank + 1:
        expected = STATES[now_rank + 1]
        return f"moves are one step at a time: the next state is {expected}"
    return None


def migration_change_problem(
    current: SpecSuiteMigration | None,
    requested: SpecSuiteMigration | None,
    now: datetime,
) -> str | None:
    """The one rule every write path (PUT migration, PATCH auth, spec replace) applies: forward-only
    steps, a dual window anchored to the real clock (started within a day of now, ending at most
    90 days after now) and never extended once open. Removing the migration closes legacy sign-in
    and is always allowed."""
    if requested is None or requested == current:
        return None
    problem = transition_problem(current, requested)
    if problem is not None:
        return problem
    if current is not None and current.legacy_issuer != requested.legacy_issuer:
        return "legacy_issuer cannot change once the migration is open"
    if requested.state == "dual" and requested.dual_until and requested.window_started_at:
        if current is not None and current.state == "dual":
            if requested.window_started_at != current.window_started_at:
                return "the dual window cannot be restarted"
            if current.dual_until and requested.dual_until > current.dual_until:
                return "the dual window can be shortened, never extended"
        else:
            if abs(requested.window_started_at - now) > timedelta(days=1):
                return "window_started_at must be the current time (within a day)"
        if requested.dual_until > now + MAX_DUAL_WINDOW:
            return f"dual_until must be at most {MAX_DUAL_DAYS} days from now"
    return None


def window_problems(m: SpecSuiteMigration) -> list[tuple[str, str, str]]:
    """(field, code, message) for a malformed migration block; the spec stays deterministic, so
    the dual window is two explicit instants and never 'now'."""
    problems: list[tuple[str, str, str]] = []
    if m.state not in STATES:
        problems.append(("state", "invalid_value", "must be legacy_read_only, dual or hub_only"))
        return problems
    for name in ("dual_until", "window_started_at"):
        value = getattr(m, name)
        if value is not None and value.tzinfo is None:
            problems.append((name, "timezone_required", "must carry a timezone (e.g. Z)"))
    if m.state == "dual":
        if m.dual_until is None or m.window_started_at is None:
            problems.append(
                (
                    "dual_until",
                    "dual_window_required",
                    "dual needs both window_started_at and dual_until (explicit, never 'now')",
                )
            )
        elif m.dual_until.tzinfo is not None and m.window_started_at.tzinfo is not None:
            if m.dual_until <= m.window_started_at:
                problems.append(("dual_until", "dual_window_invalid", "must be after window_started_at"))
            elif m.dual_until - m.window_started_at > MAX_DUAL_WINDOW:
                problems.append(
                    (
                        "dual_until",
                        "dual_window_too_long",
                        f"the dual window is at most {MAX_DUAL_DAYS} days",
                    )
                )
    elif m.dual_until is not None or m.window_started_at is not None:
        what = "hub_only closes legacy sign-in, so it carries no legacy window" if (
            m.state == "hub_only"
        ) else "only the dual state has a window"
        problems.append(("dual_until", "window_not_allowed", what))
    return problems


def legacy_settings(m: SpecSuiteMigration | None) -> dict[str, Any] | None:
    """What the generated app reads: None when no legacy token may be accepted at all."""
    if m is None or m.state == "hub_only":
        return None
    return {
        "state": m.state,
        "issuer": m.legacy_issuer,
        "dual_until": m.dual_until.isoformat() if m.dual_until else None,
    }


def _step(order: int, title: str, detail: str, command: str | None = None) -> dict[str, Any]:
    return {"order": order, "title": title, "detail": detail, "command": command}


def impact_report(
    spec: Spec,
    *,
    sources: Mapping[str, str] | None,
    problems: list[str],
) -> dict[str, Any]:
    """What moving this app under its suite hub changes. Spec-level only: no user data is read.

    `sources` are the hook / custom code files to scan (None = not scanned); `problems` are the
    spec's own validation messages for auth.suite."""
    auth = spec.auth
    slug = spec.project.slug
    suite = auth.suite if auth else None
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if auth is None or not auth.enabled:
        blockers.append({"code": "no_auth", "message": "the project has no sign-in to migrate"})
    if suite is None:
        blockers.append(
            {"code": "no_suite", "message": "set auth.suite (suite id) before planning the join"}
        )
    for message in problems:
        blockers.append({"code": "invalid_suite", "message": message})
    provider = auth.provider if auth else "none"
    if auth is not None and auth.provider == "keycloak" and (
        suite is None or suite.migration is None
    ):
        warnings.append(
            {
                "code": "already_keycloak",
                "message": "the project already uses Keycloak; path (b) moves a built-in app "
                "into a hub, so confirm this is the intended path",
            }
        )
    readers: list[SubReader] = []
    if sources is None:
        warnings.append(
            {
                "code": "hooks_not_scanned",
                "message": "hook and custom code was not scanned for claims[\"sub\"]; "
                "pass workspace_id to scan a workspace",
            }
        )
    else:
        readers = scan_sub_readers(sources)
        if readers:
            warnings.append(
                {
                    "code": "reads_claims_sub",
                    "message": f"{len(readers)} place(s) read claims[\"sub\"]: under the hub the "
                    "subject is not the local user id; use the Principal instead",
                }
            )
    roles = sorted(auth.roles, key=lambda r: r.name) if auth else []
    client_id = slug
    realm = suite_realm(suite.suite_id) if suite else None
    multi_tenant = bool(auth and auth.multi_tenant)
    if multi_tenant:
        warnings.append(
            {
                "code": "tenants_to_organisations",
                "message": "every tenant becomes a Keycloak organisation; create them in the "
                "hub before users sign in",
            }
        )
    warnings.append(
        {
            "code": "passwords_not_moved",
            "message": "password hashes are never exported to the hub: users set a new password "
            "(UPDATE_PASSWORD) on first hub sign-in",
        }
    )
    warnings.append(
        {
            "code": "refresh_tokens_not_moved",
            "message": "built-in refresh tokens are not portable: clients sign in again at the hub",
        }
    )
    commands = [
        "python -m app.auth.export export --out users.ndjson",
        "python -m app.auth.export impact --hub-users hub.ndjson",
        "python -m app.auth.export keycloak-import --out kc.json",
        "python -m app.auth.export import users.ndjson",
        "python -m app.auth.export relink --from <legacy issuer> --to <hub issuer> --copy",
    ]
    steps = [
        _step(1, "Plan the join", "Set auth.suite and switch the project to Keycloak; the realm "
              f"is derived ({realm}) and the client id is the project slug ({client_id})."),
        _step(2, "Open the migration", "PUT /suite/migration state legacy_read_only with the "
              "legacy issuer; fix every blocker above first."),
        _step(3, "Measure", "Run the impact command in the CURRENT app against a hub user list.",
              commands[1]),
        _step(4, "Export the accounts", "identity-v1, no password hashes.", commands[0]),
        _step(5, "Create the hub users", "Write the Keycloak partial-import file (no credentials, "
              "UPDATE_PASSWORD required) and import it into the realm.", commands[2]),
        _step(6, "Open the dual window", "PUT /suite/migration state dual with window_started_at "
              "and dual_until (at most 90 days); deploy the regenerated app with "
              "LEGACY_JWT_SECRET set, import the identity-v1 file, then link the hub identities.",
              commands[3]),
        _step(7, "Link the hub identities", "Copy each identity to the hub issuer (same subjects) "
              "so a hub token resolves to the same local user.", commands[4]),
        _step(8, "Close legacy sign-in", "PUT /suite/migration state hub_only (final); remove "
              "LEGACY_JWT_SECRET."),
    ]
    return {
        "current_provider": provider,
        "suite_id": suite.suite_id if suite else None,
        "migration": suite.migration.model_dump(mode="json") if suite and suite.migration else None,
        "realm": realm,
        "client_id": client_id,
        "hub_url": hub_base_url(suite.hub_issuer) if suite and suite.hub_issuer else None,
        "roles_to_client_roles": [
            {"role": r.name, "client_role": r.name, "client_id": client_id} for r in roles
        ],
        "tenants_to_organisations": multi_tenant,
        "claims_sub_readers": [
            {"path": r.path, "line": r.line, "text": r.text} for r in readers
        ],
        "hooks_scanned": sources is not None,
        "blockers": blockers,
        "warnings": warnings,
        "steps": steps,
        "commands": commands,
    }

