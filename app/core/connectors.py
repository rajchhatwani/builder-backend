"""Connector framework skeleton (B4-1, C16).

A connector pulls records for ONE entity from somewhere and hands them to the import pipeline in
pages. Only the file (CSV) connector is implemented; pull connectors (REST, database, SaaS) are an
interface only: implement `Connector`, add it to `REGISTRY`, and the cursor semantics below apply.

Cursor modes
  backfill     read everything from the start, page by page, until `done`
  incremental  read only what changed after `position` (the connector decides what position means)
  reconcile    read the full current listing so the caller can compare it with what it holds and
               tombstone what vanished (see `missing_keys`)
`tombstones=True` means the source can report deletions: such a record has `deleted=True` and the
caller removes (or flags) the matching stored record instead of upserting it.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from app.core import data_import as di
from app.core.spec_models import SpecEntity

Mode = Literal["backfill", "incremental", "reconcile"]


@dataclass(frozen=True)
class CursorState:
    mode: Mode = "backfill"
    position: str | None = None  # opaque to the caller; None = start
    tombstones: bool = False
    done: bool = False


@dataclass(frozen=True)
class ConnectorRecord:
    key: str  # the source's own stable id for the record
    data: dict[str, Any]
    deleted: bool = False  # tombstone


class Connector(Protocol):
    kind: str

    def fetch(self, cursor: CursorState) -> tuple[list[ConnectorRecord], CursorState]:
        """One page of records and the cursor to continue from (`done=True` when exhausted)."""
        ...


def missing_keys(known: set[str], listing: list[ConnectorRecord]) -> set[str]:
    """Reconcile: keys we hold that the source no longer lists (candidates for a tombstone)."""
    return known - {r.key for r in listing if not r.deleted}


@dataclass
class FileConnector:
    """CSV bytes -> validated records. `data` of a record is the typed record, `key` its row number."""

    entity: SpecEntity
    mapping: dict[str, str]
    content: bytes
    page_size: int = 500
    kind: str = field(default="file", init=False)

    def fetch(self, cursor: CursorState) -> tuple[list[ConnectorRecord], CursorState]:
        parsed = di.parse_csv(self.content)
        start = int(cursor.position or 0)
        results = di.validate_rows(parsed.rows[start : start + self.page_size], self.mapping, self.entity)
        records = [
            ConnectorRecord(key=str(start + r.row_no), data=r.record) for r in results if r.record
        ]
        end = start + self.page_size
        done = end >= len(parsed.rows)
        return records, replace(cursor, position=str(min(end, len(parsed.rows))), done=done)


REGISTRY: dict[str, Callable[..., Connector]] = {"file": FileConnector}


def drain(connector: Connector, cursor: CursorState | None = None) -> tuple[list[ConnectorRecord], CursorState]:
    """Fetch until the connector reports done (used by tests and small sources)."""
    state = cursor or CursorState()
    out: list[ConnectorRecord] = []
    for _ in range(10_000):  # a connector that never finishes must not hang the caller
        page, state = connector.fetch(state)
        out.extend(page)
        if state.done:
            return out, state
    raise RuntimeError("connector did not finish")
