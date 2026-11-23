"""Move accounts in and out of this app: `identity-v1` export / import, and issuer relinking (generated).

    python -m app.auth.export export --out users.ndjson            # no password hashes
    python -m app.auth.export export --out users.ndjson --include-hashes   # SENSITIVE file
    python -m app.auth.export import users.ndjson
    python -m app.auth.export relink --from https://old/realms/x --to https://new/realms/x
    python -m app.auth.export relink --from old --to new --copy   # keep the old identities too
    python -m app.auth.export keycloak-import --out kc.json        # Keycloak partial import, no credentials
    python -m app.auth.export impact --hub-users hub.ndjson        # what moving to a hub would touch
    python -m app.auth.export overlap --other other.ndjson         # dry run: who exists in both apps

The file is NDJSON: a header line, then one record per line (`tenant`, `user`, `identity`,
`credential`), sorted so the same data always produces the same file. Password hashes are
written only with --include-hashes; treat such a file like a password database. Importing
skips what already exists, so running it twice changes nothing.

`keycloak-import`, `impact` and `overlap` only READ: they never change data and never print or
write a password hash (a credential record in an input file is ignored). They work on e-mail
addresses that are VERIFIED on every side that is compared; an unverified address is listed apart
and never matched.
"""

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import uuid
from collections.abc import Iterable, Mapping
from typing import Any, TextIO

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from app.auth import config, identity
from app.auth.models import AuthIdentity, AuthTenant, AuthUser
from app.db import session_factory

FORMAT = "identity-v1"
_NO_PASSWORD = "!imported-without-credentials"  # never matches any password
_B64 = re.compile(r"[A-Za-z0-9+/_=-]{1,512}")


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return value


def _row(model: Any, row: Any, skip: Iterable[str] = ()) -> dict[str, Any]:
    return {
        c.key: _plain(getattr(row, c.key)) for c in model.__table__.columns if c.key not in skip
    }


def _coerce(column: sa.Column[Any], value: Any) -> Any:
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value
    if python_type is uuid.UUID:
        return uuid.UUID(value)
    if python_type is dt.datetime:
        return dt.datetime.fromisoformat(value)
    if python_type is dt.date:
        return dt.date.fromisoformat(value)
    return value


def _credential(user_id: str, password_hash: str) -> dict[str, Any] | None:
    parts = password_hash.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    return {
        "type": "credential",
        "user_id": user_id,
        "algorithm": "scrypt",
        "n": int(parts[1]),
        "r": int(parts[2]),
        "p": int(parts[3]),
        "salt": parts[4],
        "hash": parts[5],
    }


def _stored_hash(record: dict[str, Any]) -> str:
    for part in (record["salt"], record["hash"]):
        if not isinstance(part, str) or not _B64.fullmatch(part):
            raise ValueError("a credential record has a malformed salt or hash")
    return f"scrypt${int(record['n'])}${int(record['r'])}${int(record['p'])}${record['salt']}${record['hash']}"


async def export_records(*, include_hashes: bool) -> list[dict[str, Any]]:
    """The header, then every record, in a fixed order."""
    has_password = "password_hash" in AuthUser.__table__.columns
    async with session_factory() as session:
        tenants = (await session.execute(sa.select(AuthTenant).order_by(AuthTenant.id))).scalars()
        users = (
            await session.execute(sa.select(AuthUser).order_by(AuthUser.created_at, AuthUser.id))
        ).scalars().all()
        identities = (
            await session.execute(
                sa.select(AuthIdentity).order_by(AuthIdentity.issuer, AuthIdentity.subject)
            )
        ).scalars()
        header: dict[str, Any] = {
            "format": FORMAT,
            "provider": config.PROVIDER,
            "issuer": config.current_issuer(),
            "exported_at": dt.datetime.now(dt.UTC).isoformat(),
            "hash_alg": "scrypt" if include_hashes and has_password else None,
            "includes_credentials": bool(include_hashes and has_password),
        }
        records: list[dict[str, Any]] = [header]
        records += [{"type": "tenant", **_row(AuthTenant, t)} for t in tenants]
        for user in users:
            records.append({"type": "user", **_row(AuthUser, user, skip=("password_hash",))})
            if include_hashes and has_password:
                credential = _credential(str(user.id), user.password_hash)  # type: ignore[attr-defined]
                if credential is not None:
                    records.append(credential)
        records += [{"type": "identity", **_row(AuthIdentity, i)} for i in identities]
        return records


def write_records(records: list[dict[str, Any]], out: TextIO) -> None:
    for record in records:
        out.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


async def import_records(lines: Iterable[str]) -> dict[str, int]:
    """Load an identity-v1 file. Existing rows are left alone; counts say what was added."""
    counts = {"tenant": 0, "user": 0, "identity": 0, "skipped": 0}
    rows = [json.loads(line) for line in lines if line.strip()]
    if not rows or rows[0].get("format") != FORMAT:
        raise ValueError(f"not an {FORMAT} file")
    hashes = {r["user_id"]: _stored_hash(r) for r in rows if r.get("type") == "credential"}
    async with session_factory() as session:
        for record in rows[1:]:
            kind = record.get("type")
            body = {k: v for k, v in record.items() if k != "type"}
            if kind == "tenant":
                model: Any = AuthTenant
            elif kind == "user":
                model = AuthUser
                if "password_hash" in AuthUser.__table__.columns:
                    body["password_hash"] = hashes.get(body["id"], _NO_PASSWORD)
            elif kind == "identity":
                model = AuthIdentity
            elif kind == "credential":
                continue
            else:
                raise ValueError(f"unknown record type {kind!r}")
            columns = model.__table__.columns
            values = {k: _coerce(columns[k], v) for k, v in body.items() if k in columns}
            result = await session.execute(
                insert(model).values(**values).on_conflict_do_nothing()
            )
            counts[kind if result.rowcount else "skipped"] += 1  # type: ignore[attr-defined]
        await session.commit()
    return counts


async def _relink(old: str, new: str, copy: bool = False) -> int:
    async with session_factory() as session:
        if copy:
            return await identity.copy_issuer(session, old, new)
        return await identity.relink_issuer(session, old, new)


# --- read-only analysis over identity-v1 records (no database writes, no hashes) -------------

_SECRET_KEYS = frozenset({"hash", "password_hash", "salt", "password", "credentials"})
_ROLE_LIMIT = 200


def load_records(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Parse an identity-v1 (or hub) NDJSON file for analysis. Credential records and any
    secret-looking key are dropped here, so nothing downstream can ever print a hash."""
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict) or record.get("type") == "credential":
            continue
        records.append({k: v for k, v in record.items() if k not in _SECRET_KEYS})
    return records


def _norm(email: Any) -> str | None:
    if not isinstance(email, str) or not email.strip():
        return None
    return email.strip().casefold()


class _Person:
    """One account of one side, reduced to what the analysis needs."""

    def __init__(self, user: dict[str, Any], idents: list[dict[str, Any]]) -> None:
        self.raw = user
        self.id = str(user.get("id", ""))
        self.email = _norm(user.get("email"))
        self.roles = sorted(r for r in (user.get("roles") or []) if isinstance(r, str))[:_ROLE_LIMIT]
        self.tenant_id = user.get("tenant_id")
        self.active = user.get("is_active", True) is not False and not user.get("deleted_at")
        # Verified means the account (or an identity linked to it) proved control of THIS address.
        proven = bool(user.get("email_verified_at")) or user.get("email_verified") is True
        for ident in idents:
            if ident.get("email_verified") is True and _norm(ident.get("email_at_link")) in (None, self.email):
                proven = True
        self.verified = bool(self.email) and proven


def _people(records: list[dict[str, Any]]) -> list[_Person]:
    by_user: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("type") == "identity":
            by_user.setdefault(str(record.get("user_id")), []).append(record)
    users = [r for r in records if r.get("type") in (None, "user") and "format" not in r]
    return sorted(
        (_Person(u, by_user.get(str(u.get("id")), [])) for u in users), key=lambda p: p.id
    )


def _tenants(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(r["id"]): r for r in records if r.get("type") == "tenant" and "id" in r}


def _by_email(people: list[_Person], *, verified: bool) -> dict[str, list[_Person]]:
    groups: dict[str, list[_Person]] = {}
    for person in people:
        if person.email and person.verified is verified:
            groups.setdefault(person.email, []).append(person)
    return groups


def overlap_report(mine: list[dict[str, Any]], other: list[dict[str, Any]]) -> dict[str, Any]:
    """Dry run for merging two apps (identity path c): who exists on both sides.

    Matches ONLY on an e-mail address that is verified on BOTH sides. Unverified accounts are
    listed separately and are never matched. Nothing is modified; the report holds no hashes."""
    a, b = _people(mine), _people(other)
    a_ok, b_ok = _by_email(a, verified=True), _by_email(b, verified=True)
    collisions: list[dict[str, Any]] = []
    role_conflicts: list[dict[str, Any]] = []
    for email in sorted(a_ok.keys() & b_ok.keys()):
        left, right = a_ok[email], b_ok[email]
        entry = {
            "email": email,
            "mine": [p.id for p in left],
            "other": [p.id for p in right],
            "many_to_one": len(left) > 1 or len(right) > 1,
        }
        collisions.append(entry)
        mine_roles = sorted({r for p in left for r in p.roles})
        other_roles = sorted({r for p in right for r in p.roles})
        if mine_roles != other_roles:
            role_conflicts.append(
                {
                    "email": email,
                    "mine": mine_roles,
                    "other": other_roles,
                    "only_mine": sorted(set(mine_roles) - set(other_roles)),
                    "only_other": sorted(set(other_roles) - set(mine_roles)),
                }
            )
    a_bad, b_bad = _by_email(a, verified=False), _by_email(b, verified=False)
    a_unverified = [p for group in a_bad.values() for p in group]
    b_unverified = [p for group in b_bad.values() for p in group]
    ta, tb = _tenants(mine), _tenants(other)

    def slug(t: dict[str, Any]) -> str:
        return str(t.get("external_ref") or t.get("name") or "").strip().casefold()

    tenant_overlaps = sorted(
        {slug(t) for t in ta.values()} & {slug(t) for t in tb.values()} - {""}
    )
    return {
        "analysis": "overlap",
        "modified": False,
        "match_rule": "e-mail, verified on both sides; unverified accounts are never matched",
        "mine": {"accounts": len(a), "verified": sum(p.verified for p in a)},
        "other": {"accounts": len(b), "verified": sum(p.verified for p in b)},
        "collisions": collisions,
        "role_conflicts": role_conflicts,
        "tenant_slug_overlaps": tenant_overlaps,
        "unverified": {
            "mine": sorted(p.id for p in a_unverified),
            "other": sorted(p.id for p in b_unverified),
            "same_address_on_both_sides": sorted(a_bad.keys() & b_bad.keys()),
            "note": "listed only: an unverified address proves nothing and is never matched",
        },
    }


def impact_report(mine: list[dict[str, Any]], hub: list[dict[str, Any]]) -> dict[str, Any]:
    """What moving these accounts under a hub would touch (identity path b), from the app's
    export and the hub's user list. Read-only; no hashes."""
    people, hub_people = _people(mine), _people(hub)
    live = [p for p in people if p.active]
    verified = _by_email(live, verified=True)
    hub_verified = _by_email(hub_people, verified=True)
    duplicates = sorted(verified.keys() & hub_verified.keys())
    unverified = [p for p in live if not p.verified]
    hub_any = {p.email for p in hub_people if p.email}
    roles: dict[str, int] = {}
    for person in live:
        for role in person.roles:
            roles[role] = roles.get(role, 0) + 1
    tenants = _tenants(mine)
    tenant_users: dict[str, int] = {}
    for person in live:
        if person.tenant_id is not None:
            tenant_users[str(person.tenant_id)] = tenant_users.get(str(person.tenant_id), 0) + 1
    return {
        "analysis": "impact",
        "modified": False,
        "users": len(people),
        "active_users": len(live),
        "verified_email": sum(p.verified for p in live),
        "unverified": {
            "count": len(unverified),
            "user_ids": sorted(p.id for p in unverified),
            "note": "they get VERIFY_EMAIL in the Keycloak import and are never matched to hub accounts",
        },
        "verified_duplicates_with_hub": {"count": len(duplicates), "emails": duplicates},
        "unverified_with_a_hub_account": sorted(
            {p.email for p in unverified if p.email and p.email in hub_any}
        ),
        "roles": dict(sorted(roles.items())),
        "tenants": [
            {"id": tid, "name": t.get("name"), "users": tenant_users.get(tid, 0)}
            for tid, t in sorted(tenants.items())
        ],
        "secrets_in_output": False,
    }


def keycloak_import_file(
    records: list[dict[str, Any]], client_id: str, tenant_attribute: str = "bb_tenant"
) -> dict[str, Any]:
    """A Keycloak partial-import document: users WITHOUT credentials. Every user must set a
    password (UPDATE_PASSWORD); an unverified address also gets VERIFY_EMAIL. The Keycloak user id
    is this app's user id, so a hub token's subject lines up with the local user."""
    tenants = _tenants(records)
    users: list[dict[str, Any]] = []
    for person in _people(records):
        raw = person.raw
        if raw.get("deleted_at"):
            continue
        actions = ["UPDATE_PASSWORD"] + ([] if person.verified or not person.email else ["VERIFY_EMAIL"])
        user: dict[str, Any] = {
            "id": person.id,
            "username": person.email or person.id,
            "enabled": person.active,
            "emailVerified": person.verified,
            "requiredActions": actions,
        }
        if person.email:
            user["email"] = person.email
        if isinstance(raw.get("name"), str) and raw["name"]:
            user["firstName"] = raw["name"][:255]
        if person.roles:
            user["clientRoles"] = {client_id: person.roles}
        tenant = tenants.get(str(person.tenant_id)) if person.tenant_id is not None else None
        if tenant is not None:
            user["attributes"] = {tenant_attribute: [str(tenant.get("name"))]}
        users.append(user)
    return {"ifResourceExists": "SKIP", "users": users}


def _client_id_default() -> str:
    issuer = config.current_issuer()
    return issuer.removeprefix("builtin:") if issuer.startswith("builtin:") else issuer.rsplit("/", 1)[-1]


def _write_json(document: Mapping[str, Any], target: str) -> None:
    text = json.dumps(document, sort_keys=True, indent=2) + "\n"
    if target == "-":
        sys.stdout.write(text)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    with os.fdopen(os.open(target, flags, 0o600), "w", encoding="utf-8") as handle:
        handle.write(text)


def _read(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return load_records(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth.export", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    out = sub.add_parser("export")
    out.add_argument("--format", default=FORMAT, choices=[FORMAT])
    out.add_argument("--out", default="-", help="file to write, or - for stdout")
    out.add_argument("--include-hashes", action="store_true", help="also write password hashes")
    load = sub.add_parser("import")
    load.add_argument("file")
    relink = sub.add_parser("relink")
    relink.add_argument("--from", dest="old", required=True)
    relink.add_argument("--to", dest="new", required=True)
    relink.add_argument("--copy", action="store_true", help="add the new identities, keep the old")
    kc = sub.add_parser("keycloak-import")
    kc.add_argument("--out", default="-")
    kc.add_argument("--client-id", default=None, help="Keycloak client the roles belong to")
    kc.add_argument("--file", default=None, help="identity-v1 file instead of this app's database")
    imp = sub.add_parser("impact")
    imp.add_argument("--hub-users", required=True, help="NDJSON of the hub's users")
    imp.add_argument("--out", default="-")
    imp.add_argument("--file", default=None, help="identity-v1 file instead of this app's database")
    ov = sub.add_parser("overlap")
    ov.add_argument("--other", required=True, help="identity-v1 file of the other app")
    ov.add_argument("--out", default="-")
    ov.add_argument("--file", default=None, help="identity-v1 file instead of this app's database")
    args = parser.parse_args(argv)

    if args.command == "export":
        records = asyncio.run(export_records(include_hashes=args.include_hashes))
        if args.out == "-":
            write_records(records, sys.stdout)
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            with os.fdopen(os.open(args.out, flags, 0o600), "w", encoding="utf-8") as handle:
                write_records(records, handle)
    elif args.command == "import":
        with open(args.file, encoding="utf-8") as handle:
            print(json.dumps(asyncio.run(import_records(handle)), sort_keys=True))
    elif args.command == "relink":
        print(json.dumps({"relinked": asyncio.run(_relink(args.old, args.new, args.copy))}))
    else:
        mine = _read(args.file) if args.file else load_records(
            json.dumps(r) for r in asyncio.run(export_records(include_hashes=False))
        )
        if args.command == "keycloak-import":
            _write_json(keycloak_import_file(mine, args.client_id or _client_id_default()), args.out)
        elif args.command == "impact":
            _write_json(impact_report(mine, _read(args.hub_users)), args.out)
        else:
            _write_json(overlap_report(mine, _read(args.other)), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
