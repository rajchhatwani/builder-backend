"""A-013: column-level model-vs-migration drift. Migrates an empty database to head with the real Alembic chain and
asks Alembic (`compare_metadata`, what `alembic check` uses) whether the ORM models describe the same schema:
tables, columns, types, nullability, server defaults, indexes, unique and foreign-key constraints."""

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.models.base import Base
from tests.api.test_migrations import _alembic, fresh_db  # noqa: F401

# Known benign differences: (diff kind, "table.name"), each with the reason it is not a bug. Keep this list empty
# unless a difference is understood and cannot be expressed in the model; every entry needs a reason.
KNOWN_BENIGN: dict[tuple[str, str], str] = {}
# Server defaults are not compared: the models leave database-side defaults to the migrations on purpose, so
# comparing them reports dozens of non-differences.


def _name(diff: Any) -> tuple[str, str]:
    kind = diff[0]
    if kind in ("add_table", "remove_table"):
        return kind, diff[1].name
    if kind in ("add_column", "remove_column"):
        return kind, f"{diff[2]}.{diff[3].name}"
    if kind in ("add_index", "remove_index", "add_constraint", "remove_constraint", "add_fk", "remove_fk"):
        obj = diff[1]
        return kind, f"{getattr(getattr(obj, 'table', None), 'name', '?')}.{obj.name}"
    if isinstance(diff, list):  # modify_* come as a list of tuples
        return _name(diff[0])
    return kind, f"{diff[2]}.{diff[3]}"  # modify_type/nullable/default: (kind, schema, table, column, ...)


def _drift(connection: Connection) -> list[Any]:
    ctx = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": False})
    return compare_metadata(ctx, Base.metadata)


async def test_migrated_schema_matches_the_models_column_for_column(fresh_db: str) -> None:  # noqa: F811
    _alembic(fresh_db, "upgrade", "head")
    engine = create_async_engine(fresh_db)
    try:
        async with engine.connect() as conn:
            diffs = await conn.run_sync(_drift)
    finally:
        await engine.dispose()
    flat = [d[0] if isinstance(d, list) else d for d in diffs]
    stale = [k for k in KNOWN_BENIGN if k not in {_name(d) for d in flat}]
    assert not stale, f"known-benign entries that no longer differ (remove them): {stale}"
    unexplained = [repr(d)[:300] for d in flat if _name(d) not in KNOWN_BENIGN]
    assert not unexplained, "models and migrations disagree:\n" + "\n".join(unexplained)
