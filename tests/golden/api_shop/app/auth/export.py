"""Move accounts in and out of this app: `identity-v1` export / import, and issuer relinking (generated).

    python -m app.auth.export export --out users.ndjson            # no password hashes
    python -m app.auth.export export --out users.ndjson --include-hashes   # SENSITIVE file
    python -m app.auth.export import users.ndjson
    python -m app.auth.export relink --from https://old/realms/x --to https://new/realms/x

The file is NDJSON: a header line, then one record per line (`tenant`, `user`, `identity`,
`credential`), sorted so the same data always produces the same file. Password hashes are
written only with --include-hashes; treat such a file like a password database. Importing
skips what already exists, so running it twice changes nothing.
"""

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import uuid
from collections.abc import Iterable
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


async def _relink(old: str, new: str) -> int:
    async with session_factory() as session:
        return await identity.relink_issuer(session, old, new)


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
    else:
        print(json.dumps({"relinked": asyncio.run(_relink(args.old, args.new))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
