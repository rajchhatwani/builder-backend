"""Platform-side data import (B4-1, C16): preview, mapping, review queue, idempotent commit.

Nothing reaches `imported_records` before `commit`. The unique constraint on
(project, entity, dedupe_key) is the arbiter between concurrent commits; the batch row lock only
makes the second caller wait and then read the stored result.
"""

import csv
import hashlib
import io
import json
import uuid
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import data_import as di
from app.core.access_layers import readable_fields
from app.core.spec_models import SpecEntity
from app.exceptions import AppError
from app.models.data_import import ImportBatch, ImportedRecord, ImportRow
from app.models.mixins import _utcnow
from app.models.project import Project
from app.schemas.data_import import (
    BatchPage,
    BatchRead,
    CommitResult,
    ImportCounts,
    ImportPreview,
    RecordPage,
    RecordRead,
    RowPage,
    RowRead,
)
from app.services.realtime_service import publish as publish_event
from app.services.spec_service import SpecService
from app.services.usage_service import consume_import_rows

_CHUNK = 1000
ROW_STATUSES = ("accepted", "rejected", "fixed", "duplicate")
PREVIEW_REJECTED_MAX = 100  # the review queue pages the rest (GET .../rows?offset=)
EXPORT_MAX_ROWS = 10_000
DUP_AFTER_FIX = "import_duplicate_after_fix"


def _chunks(items: list[Any], n: int = _CHUNK) -> Iterable[list[Any]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def _hidden_fields(spec: Any, entity: SpecEntity, role: str | None) -> set[str]:
    """C7: fields the caller's project role may NOT read per spec.authorization.field_access.
    A role the spec does not define (or no role) fails closed to the non-guarded fields only."""
    guarded = {
        f.field
        for f in (spec.authorization.field_access if spec.authorization else [])
        if f.entity == entity.name and f.read_roles is not None
    }
    known = {r.name for r in spec.auth.roles} if spec.auth is not None else set()
    names = {f.name for f in entity.fields}
    if role is not None and role in known:
        return names - readable_fields(spec, entity.name, [role])
    return names & guarded


def _row_read(r: ImportRow, hidden: set[str], mapping: dict[str, str]) -> RowRead:
    """RowRead with hidden fields removed from the record, errors and the mapped raw columns."""
    out = RowRead.model_validate(r)
    if not hidden:
        return out
    hidden_headers = {mapping[f] for f in hidden if f in mapping}
    out.raw = {k: v for k, v in out.raw.items() if k not in hidden_headers}
    if out.record is not None:
        out.record = {k: v for k, v in out.record.items() if k not in hidden}
    out.errors = [e for e in out.errors if e.get("field") not in hidden]
    return out


def _safe(v: Any) -> Any:
    """Formula-neutralise text, but leave plain numbers (decimals are stored as strings) alone."""
    if isinstance(v, str):
        try:
            if Decimal(v).is_finite():
                return v
        except InvalidOperation:
            pass
    return di.neutralize_formula(v)


def _plain(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def _cell(v: Any) -> Any:
    return "" if v is None else v


def _bad_mapping(exc: di.ImportDataError) -> AppError:
    return AppError(exc.code, exc.message, 400 if exc.code != "import_too_large" else 413)


class ImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # -- lookups ---------------------------------------------------------------------------

    async def _entity(self, project_id: uuid.UUID, name: str) -> SpecEntity:
        spec = await SpecService(self.s).assemble(project_id)  # 404 for an unknown project
        for e in spec.entities:
            if e.name == name:
                return e
        raise AppError("import_unknown_entity", f"the project has no entity {name[:80]!r}", 400)

    async def _batch(self, project_id: uuid.UUID, batch_id: uuid.UUID, lock: bool = False) -> ImportBatch:
        q = select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.project_id == project_id)
        if lock:
            q = q.with_for_update()
        batch = (await self.s.execute(q)).scalar_one_or_none()
        if batch is None:
            raise AppError("not_found", "import not found", 404)
        return batch

    @staticmethod
    def _require_previewed(batch: ImportBatch) -> None:
        if batch.status != "previewed":
            raise AppError(
                "import_not_previewed", f"this import is {batch.status}, not awaiting commit", 409
            )

    # -- validation + storage of rows -------------------------------------------------------

    async def _existing_keys(self, project_id: uuid.UUID, entity: str, keys: list[str]) -> set[str]:
        found: set[str] = set()
        for part in _chunks(keys, 5000):
            rows = await self.s.execute(
                select(ImportedRecord.dedupe_key).where(
                    ImportedRecord.project_id == project_id,
                    ImportedRecord.entity_name == entity,
                    ImportedRecord.dedupe_key.in_(part),
                )
            )
            found.update(rows.scalars())
        return found

    async def _key_taken(
        self, batch: ImportBatch, entity: str, key: str, row_id: uuid.UUID
    ) -> bool:
        if await self._existing_keys(batch.project_id, entity, [key]):
            return True
        other = (
            await self.s.execute(
                select(ImportRow.id)
                .where(
                    ImportRow.batch_id == batch.id,
                    ImportRow.id != row_id,
                    ImportRow.dedupe_key == key,
                    ImportRow.status.in_(("accepted", "fixed")),
                )
                .limit(1)
            )
        ).first()
        return other is not None

    async def _store_rows(
        self,
        batch: ImportBatch,
        entity: SpecEntity,
        raws: list[dict[str, Any]],
        mapping: dict[str, str],
    ) -> None:
        """(Re)validate every raw row against the mapping and replace the batch's rows."""
        results = di.validate_rows(raws, mapping, entity)
        keys = {r.row_no: di.dedupe_key(entity, r.record) for r in results if r.accepted and r.record}
        existing = await self._existing_keys(batch.project_id, entity.name, sorted(set(keys.values())))
        seen: set[str] = set()
        dicts: list[dict[str, Any]] = []
        counts = ImportCounts(total=len(results))
        for r in results:
            key = keys.get(r.row_no)
            if not r.accepted:
                status = "rejected"
            elif key in existing or key in seen:
                status = "duplicate"
            else:
                status = "accepted"
            if key is not None:
                seen.add(key)
            setattr(counts, status, getattr(counts, status) + 1)
            dicts.append(
                {
                    "id": uuid.uuid4(),
                    "project_id": batch.project_id,
                    "batch_id": batch.id,
                    "row_no": r.row_no,
                    "raw": r.raw,
                    "record": r.record,
                    "status": status,
                    "errors": [e.as_dict() for e in r.errors],
                    "dedupe_key": key,
                }
            )
        await self.s.execute(delete(ImportRow).where(ImportRow.batch_id == batch.id))
        for part in _chunks(dicts):
            await self.s.execute(insert(ImportRow), part)
        batch.mapping = dict(mapping)
        batch.counts = counts.model_dump()

    async def _rows(
        self, batch_id: uuid.UUID, status: str | None = None, limit: int | None = None, offset: int = 0
    ) -> list[ImportRow]:
        q = select(ImportRow).where(ImportRow.batch_id == batch_id)
        if status is not None:
            q = q.where(ImportRow.status == status)
        q = q.order_by(ImportRow.row_no).offset(offset)
        if limit is not None:
            q = q.limit(limit)
        return list((await self.s.execute(q)).scalars())

    async def _hidden(self, project_id: uuid.UUID, entity: SpecEntity, role: str | None) -> set[str]:
        return _hidden_fields(await SpecService(self.s).assemble(project_id), entity, role)

    async def _preview(
        self, batch: ImportBatch, entity: SpecEntity, role: str | None = None
    ) -> ImportPreview:
        hidden = await self._hidden(batch.project_id, entity, role)
        mp = dict(batch.mapping)
        return ImportPreview(
            batch_id=batch.id,
            entity=batch.entity_name,
            status=batch.status,
            headers=list(batch.headers),
            mapping=dict(batch.mapping),
            suggested_mapping=di.suggest_mapping(list(batch.headers), entity),
            counts=ImportCounts(**batch.counts),
            sample=[_row_read(r, hidden, mp) for r in await self._rows(batch.id, limit=20)],
            rejected=[_row_read(r, hidden, mp) for r in await self._rows(batch.id, "rejected", limit=PREVIEW_REJECTED_MAX)],
        )

    # -- flows -----------------------------------------------------------------------------

    async def create_preview(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID | None,
        filename: str,
        data: bytes,
        entity_name: str,
        mapping_json: str | None,
        role: str | None = None,
    ) -> ImportPreview:
        entity = await self._entity(project_id, entity_name)
        try:
            parsed = di.parse_csv(data)
            if mapping_json:
                try:
                    given = json.loads(mapping_json)
                except ValueError as exc:
                    raise di.ImportDataError("import_bad_mapping", "mapping is not valid JSON") from exc
                mapping = di.clean_mapping(given, parsed.headers, entity)
            else:
                mapping = di.suggest_mapping(parsed.headers, entity)
        except di.ImportDataError as exc:
            raise _bad_mapping(exc) from exc
        batch = ImportBatch(
            project_id=project_id,
            entity_name=entity.name,
            filename=(filename or "import.csv")[:255],
            content_sha256=hashlib.sha256(data).hexdigest(),
            status="previewed",
            headers=parsed.headers,
            mapping={},
            counts={},
            created_by=user_id,
        )
        self.s.add(batch)
        await self.s.flush()
        await self._store_rows(batch, entity, list(parsed.rows), mapping)
        await self.s.commit()
        return await self._preview(batch, entity, role)

    async def get_preview(
        self, project_id: uuid.UUID, batch_id: uuid.UUID, role: str | None = None
    ) -> ImportPreview:
        batch = await self._batch(project_id, batch_id)
        return await self._preview(batch, await self._entity(project_id, batch.entity_name), role)

    async def set_mapping(
        self,
        project_id: uuid.UUID,
        batch_id: uuid.UUID,
        mapping_in: dict[str, str | None],
        role: str | None = None,
    ) -> ImportPreview:
        batch = await self._batch(project_id, batch_id, lock=True)
        self._require_previewed(batch)
        entity = await self._entity(project_id, batch.entity_name)
        try:
            mapping = di.clean_mapping(mapping_in, list(batch.headers), entity)
        except di.ImportDataError as exc:
            raise _bad_mapping(exc) from exc
        raws = [r.raw for r in await self._rows(batch.id)]
        await self._store_rows(batch, entity, raws, mapping)
        await self.s.commit()
        return await self._preview(batch, entity, role)

    async def list_batches(self, project_id: uuid.UUID, limit: int, offset: int) -> BatchPage:
        total = (
            await self.s.execute(
                select(func.count()).select_from(ImportBatch).where(ImportBatch.project_id == project_id)
            )
        ).scalar_one()
        rows = (
            await self.s.execute(
                select(ImportBatch)
                .where(ImportBatch.project_id == project_id)
                .order_by(ImportBatch.created_at.desc(), ImportBatch.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return BatchPage(items=[self.batch_read(b) for b in rows], total=total, limit=limit, offset=offset)

    @staticmethod
    def batch_read(b: ImportBatch) -> BatchRead:
        return BatchRead(
            id=b.id,
            entity=b.entity_name,
            filename=b.filename,
            content_sha256=b.content_sha256,
            status=b.status,
            mapping=dict(b.mapping),
            counts=dict(b.counts),
            created_at=b.created_at,
            committed_at=b.committed_at,
        )

    async def get_batch(self, project_id: uuid.UUID, batch_id: uuid.UUID) -> BatchRead:
        return self.batch_read(await self._batch(project_id, batch_id))

    async def list_rows(
        self,
        project_id: uuid.UUID,
        batch_id: uuid.UUID,
        status: str | None,
        limit: int,
        offset: int,
        role: str | None = None,
    ) -> RowPage:
        if status is not None and status not in ROW_STATUSES:
            raise AppError("validation_error", "unknown row status", 422)
        batch = await self._batch(project_id, batch_id)
        entity = await self._entity(project_id, batch.entity_name)
        hidden = await self._hidden(project_id, entity, role)
        mp = dict(batch.mapping)
        q = select(func.count()).select_from(ImportRow).where(ImportRow.batch_id == batch_id)
        if status is not None:
            q = q.where(ImportRow.status == status)
        total = (await self.s.execute(q)).scalar_one()
        rows = await self._rows(batch_id, status, limit, offset)
        return RowPage(
            items=[_row_read(r, hidden, mp) for r in rows], total=total, limit=limit, offset=offset
        )

    async def fix_row(
        self,
        project_id: uuid.UUID,
        batch_id: uuid.UUID,
        row_id: uuid.UUID,
        values: dict[str, Any],
        role: str | None = None,
    ) -> RowRead:
        batch = await self._batch(project_id, batch_id, lock=True)
        self._require_previewed(batch)
        entity = await self._entity(project_id, batch.entity_name)
        names = {f.name for f in entity.fields}
        unknown = sorted(set(values) - names)
        if unknown:
            raise AppError("validation_error", f"unknown field {unknown[0][:60]!r}", 422)
        row = (
            await self.s.execute(
                select(ImportRow).where(ImportRow.id == row_id, ImportRow.batch_id == batch_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise AppError("not_found", "row not found", 404)
        # Fixable: rejected, fixed, and a duplicate that a previous fix produced (marked with the
        # `import_duplicate_after_fix` error). A plain accepted/duplicate row is not.
        was_fix_dup = row.status == "duplicate" and any(
            e.get("code") == DUP_AFTER_FIX for e in (row.errors or [])
        )
        if row.status not in ("rejected", "fixed") and not was_fix_dup:
            raise AppError(
                "import_row_not_fixable", "only a rejected or fixed row can be fixed", 409
            )
        merged = di.values_from_raw(row.raw, dict(batch.mapping))
        merged.update(values)
        res = di.validate_values(merged, entity)
        before = row.status
        if res.record is not None:
            key = di.dedupe_key(entity, res.record)
            row.record = res.record
            row.dedupe_key = key
            if await self._key_taken(batch, entity.name, key, row.id):
                row.status = "duplicate"
                row.errors = [
                    {
                        "field": "",
                        "code": DUP_AFTER_FIX,
                        "message": "another record with the same key already exists or is in this import",
                    }
                ]
            else:
                row.status = "fixed"
                row.errors = []
        else:
            row.errors = [e.as_dict() for e in res.errors]
            row.status = "rejected"
            row.record = None
            row.dedupe_key = None
        if before != row.status:
            counts = dict(batch.counts)
            counts[before] = max(0, int(counts.get(before, 0)) - 1)
            counts[row.status] = int(counts.get(row.status, 0)) + 1
            batch.counts = counts
        await self.s.commit()
        return _row_read(row, await self._hidden(project_id, entity, role), dict(batch.mapping))

    async def commit(self, project_id: uuid.UUID, batch_id: uuid.UUID) -> tuple[CommitResult, bool]:
        """Returns (result, newly_committed). A second call returns the stored result."""
        batch = await self._batch(project_id, batch_id, lock=True)
        if batch.status == "committed":
            return self._commit_result(batch), False
        self._require_previewed(batch)
        rows = [r for r in await self._rows(batch.id) if r.status in ("accepted", "fixed")]
        payload = [
            {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "entity_name": batch.entity_name,
                "dedupe_key": r.dedupe_key,
                "data": r.record,
                "batch_id": batch.id,
                "created_at": _utcnow(),
            }
            for r in rows
            if r.dedupe_key is not None and r.record is not None
        ]
        created = 0
        for part in _chunks(payload):
            inserted = await self.s.execute(
                pg_insert(ImportedRecord)
                .values(part)
                .on_conflict_do_nothing(constraint="uq_imported_records_key")
                .returning(ImportedRecord.dedupe_key)
            )
            created += len(inserted.all())
        if created:  # charge only rows actually stored; a fully duplicate batch costs nothing
            org_id = (
                await self.s.execute(select(Project.organization_id).where(Project.id == project_id))
            ).scalar_one_or_none()
            if org_id is not None:
                try:
                    await consume_import_rows(
                        self.s, org_id, project_id, created, idempotency_key=str(batch.id)
                    )
                except AppError:
                    await self.s.rollback()  # nothing stored when the quota refuses
                    raise
        counts = dict(batch.counts)
        counts["commit"] = {
            "created": created,
            "duplicate": len(payload) - created + int(counts.get("duplicate", 0)),
            "rejected": int(counts.get("rejected", 0)),
        }
        batch.counts = counts
        batch.status = "committed"
        batch.committed_at = _utcnow()
        result = self._commit_result(batch)
        await publish_event(  # B4-2: counts and names only, never row data
            self.s, project_id, "imports", "import.committed",
            {"batch_id": str(batch.id), "entity": batch.entity_name, **counts["commit"]},
        )  # fmt: skip
        await self.s.commit()
        return result, True

    @staticmethod
    def _commit_result(batch: ImportBatch) -> CommitResult:
        c = dict(batch.counts.get("commit", {}))
        return CommitResult(
            batch_id=batch.id,
            status=batch.status,
            created=int(c.get("created", 0)),
            duplicate=int(c.get("duplicate", 0)),
            rejected=int(c.get("rejected", 0)),
        )

    async def cancel(self, project_id: uuid.UUID, batch_id: uuid.UUID) -> BatchRead:
        batch = await self._batch(project_id, batch_id, lock=True)
        if batch.status == "cancelled":
            return self.batch_read(batch)
        self._require_previewed(batch)
        batch.status = "cancelled"
        await self.s.commit()
        return self.batch_read(batch)

    async def list_records(
        self, project_id: uuid.UUID, entity: str, limit: int, offset: int, role: str | None = None
    ) -> RecordPage:
        ent = await self._entity(project_id, entity)
        hidden = await self._hidden(project_id, ent, role)
        where = (ImportedRecord.project_id == project_id, ImportedRecord.entity_name == entity)
        total = (
            await self.s.execute(select(func.count()).select_from(ImportedRecord).where(*where))
        ).scalar_one()
        rows = (
            await self.s.execute(
                select(ImportedRecord)
                .where(*where)
                .order_by(ImportedRecord.created_at, ImportedRecord.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return RecordPage(
            items=[
                RecordRead(
                    id=r.id,
                    entity=r.entity_name,
                    data={k: v for k, v in r.data.items() if k not in hidden},
                    batch_id=r.batch_id,
                    created_at=r.created_at,
                )
                for r in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def export_csv(
        self, project_id: uuid.UUID, entity: str, role: str | None = None
    ) -> tuple[str, bool]:
        """CSV of the caller-visible fields (C7), every cell neutralized against formula injection.
        Capped at EXPORT_MAX_ROWS; the bool says it was cut."""
        ent = await self._entity(project_id, entity)
        hidden = await self._hidden(project_id, ent, role)
        columns = [f.name for f in ent.fields if f.name not in hidden]
        rows = (
            await self.s.execute(
                select(ImportedRecord.data)
                .where(ImportedRecord.project_id == project_id, ImportedRecord.entity_name == entity)
                .order_by(ImportedRecord.created_at, ImportedRecord.id)
                .limit(EXPORT_MAX_ROWS + 1)
            )
        ).scalars()
        data = list(rows)
        truncated = len(data) > EXPORT_MAX_ROWS
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([di.neutralize_formula(c) for c in columns])
        for rec in data[:EXPORT_MAX_ROWS]:
            w.writerow([_cell(_safe(_plain(rec.get(c)))) for c in columns])
        return buf.getvalue(), truncated
