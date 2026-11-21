"""Move every protected row to the active key (generated).  `python -m app.regulated.reencrypt`

Run it after putting a new key FIRST in the key file (the old one stays below it). It walks every encrypted column and
the token vault in batches, decrypts each value with the ring and rewrites the rows whose key id is not the active one
(searchable fields get their blind index recomputed too). It is idempotent: a second run changes nothing.

Before writing anything it checks that EVERY row can be decrypted; if some cannot (a key was dropped too early, a
value was tampered with) it raises RegulatedError with a count per column, never a value, and writes nothing.
Once it reports that nothing is left, the old key can be removed from the ring."""

import asyncio
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.regulated import crypto, keys, settings, tokens
from app.regulated.errors import RegulatedError

BATCH = 200


def _targets() -> list[tuple[str, str, str, bool]]:
    """(table, column, key column, searchable) of every encrypted column, the vault last."""
    out = [
        (table, column, "id", bool(rule["searchable"]))
        for table, rules in sorted(settings.PROTECTED.items())
        for column, rule in sorted(rules.items())
        if rule["mode"] == "encrypt"
    ]
    if any(rule["mode"] == "tokenise" for rules in settings.PROTECTED.values() for rule in rules.values()):
        out.append((tokens.VAULT_TABLE, "ciphertext", "token", False))
    return out


async def _batches(session: AsyncSession, table: Any, key: str, column: str) -> Any:
    last = None
    while True:
        stmt = sa.select(table.c[key], table.c[column]).where(table.c[column].is_not(None)).order_by(table.c[key]).limit(BATCH)
        if last is not None:
            stmt = stmt.where(table.c[key] > last)
        rows = (await session.execute(stmt)).all()
        if not rows:
            return
        yield rows
        last = rows[-1][0]


def _aad_column(table: str, column: str) -> str:
    return tokens.VAULT_COLUMN if table == tokens.VAULT_TABLE else column


async def reencrypt_all(session: AsyncSession) -> dict[str, int]:
    """Rewrite every row not under the active key. Returns {"<table>.<column>": rows rewritten}."""
    active = keys.get_ring().active_id
    handles = {
        (table, column): sa.table(
            table, sa.column(key, sa.Text() if key == "token" else sa.Uuid()), sa.column(column, sa.Text()),
            *([sa.column(column + "_bidx", sa.String(64))] if searchable else []),
        )
        for table, column, key, searchable in _targets()
    }
    # 1. nothing is written unless every value can be read
    broken: dict[str, int] = {}
    for table, column, key, _searchable in _targets():
        async for rows in _batches(session, handles[(table, column)], key, column):
            for _id, stored in rows:
                try:
                    crypto.decrypt(table, _aad_column(table, column), stored)
                except RegulatedError:
                    broken[f"{table}.{column}"] = broken.get(f"{table}.{column}", 0) + 1
    if broken:
        detail = ", ".join(f"{name}: {count}" for name, count in sorted(broken.items()))
        raise RegulatedError(f"cannot re-encrypt: some values cannot be decrypted ({detail}); nothing was changed")
    # 2. rewrite what is not under the active key
    changed: dict[str, int] = {}
    for table, column, key, searchable in _targets():
        handle = handles[(table, column)]
        count = 0
        async for rows in _batches(session, handle, key, column):
            for row_key, stored in rows:
                if crypto.key_id_of(stored) == active:
                    continue
                aad = _aad_column(table, column)
                plain = crypto.decrypt(table, aad, stored)
                values: dict[str, Any] = {column: crypto.encrypt(table, aad, plain)}
                if searchable:
                    values[column + "_bidx"] = crypto.blind_index(table, column, plain)
                done = await session.execute(
                    sa.update(handle).where(handle.c[key] == row_key, handle.c[column] == stored).values(**values)
                )
                count += int(done.rowcount or 0)  # type: ignore[attr-defined]
            await session.commit()
        changed[f"{table}.{column}"] = count
    return changed


async def remaining(session: AsyncSession) -> dict[str, int]:
    """Rows still not under the active key (a process on the old key, or a write that raced the pass, leaves some)."""
    active = keys.get_ring().active_id
    left: dict[str, int] = {}
    for table, column, key, _searchable in _targets():
        handle = sa.table(table, sa.column(key, sa.Text() if key == "token" else sa.Uuid()), sa.column(column, sa.Text()))
        async for rows in _batches(session, handle, key, column):
            count = sum(1 for _k, stored in rows if crypto.key_id_of(stored) != active)
            if count:
                left[f"{table}.{column}"] = left.get(f"{table}.{column}", 0) + count
    return left


async def main() -> int:
    """Exit code 0 only when nothing is left under an old key AND the provider credential vault is moved too."""
    from app.db import session_factory

    async with session_factory() as session:
        changed = await reencrypt_all(session)
        left = await remaining(session)
        vault_moved = 0
        try:
            from app.providers import vault as provider_vault
        except ImportError:  # the project has no provider vault
            provider_vault = None  # type: ignore[assignment]
        if provider_vault is not None:
            vault_moved = await provider_vault.reencrypt_all(session)
            await session.commit()
    for name, count in sorted(changed.items()):
        print(f"{name}: {count} re-encrypted")
    if provider_vault is not None:
        print(f"provider credentials: {vault_moved} re-encrypted")
    if left:
        detail = ", ".join(f"{name}: {count}" for name, count in sorted(left.items()))
        print(f"NOT DONE: rows still under an old key ({detail}). Restart every API/worker process so it loads the new ring, "
              "run this again, and keep the old key until it reports done.")
        return 1
    print("done: " + ("nothing left to move" if not any(changed.values()) else f"{sum(changed.values())} values moved")
          + "; restart every API/worker process before you remove the old key")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
