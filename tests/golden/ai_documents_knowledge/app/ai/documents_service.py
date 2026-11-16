"""Document AI service (generated). The rules, in one place.

* A document is registered with its TEXT and a kind (a set of fields from the spec). Extraction runs inside the request
  through the gateway (`app.ai.service.complete`, stage `documents.STAGE`, response_format json), so it is budgeted,
  idempotent and in the cost ledger; the document keeps the ledger call id.
* The model answers {"fields": {name: {value, confidence_bp, start, end, quote}}}. An anchor is accepted only when
  `quote == content[start:end]`; otherwise the field keeps the model's value but gets confidence 0, no anchor and
  needs review. The page of an anchor is computed here (1 + form feeds before `start`), never taken from the model.
* The VALUE must appear in the anchored quote (whitespace, commas and currency signs ignored, case ignored); a value the
  quote does not support is treated like a failed anchor (confidence 0, no anchor, needs review).
* A field needs review when its confidence is below REVIEW_BELOW_BP, its anchor failed, or its value is missing. A
  document is `needs_review` when a required field is missing or any present field needs review, else `extracted`.
* approve refuses (409 review_pending) while a flagged field with a value is neither corrected nor named in the request's
  `acknowledge` list. correct clears the anchor (the quote no longer describes the value). The creator of a document cannot
  correct / approve / reject it unless the spec sets allow_self_review (403 self_review_forbidden).
* approve / reject are final and decided under a row lock (FOR UPDATE): of parallel decisions exactly one wins, the
  others get 409 document_closed. Approve refuses while a required field has no value (422 missing_required_fields).
* Reads: reviewers (and readers) see the tenant's documents; a caller who may only upload sees only their own.
"""

import asyncio
import hashlib
import hmac
import json
import re
import typing as _t
import uuid as _uuid
from datetime import UTC, datetime

import sqlalchemy as _sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import documents_config as _config
from app.ai import documents_schemas as _s
from app.ai import providers as _providers
from app.ai import schemas as _gw
from app.ai import service as _gateway
from app.ai.documents_models import AiDocument, AiDocumentField
from app.auth.config import get_auth_settings
from app.core.errors import AppError

SEGMENT_CHARS = 19_000  # one gateway message per segment (a message holds at most 20_000 characters)
MAX_SEGMENTS = 20  # 380_000 characters: inside the gateway's total size cap (config.MAX_TOTAL_CHARS)
FINAL = ("approved", "rejected")


def _now() -> datetime:
    return datetime.now(UTC)


def _scoped(stmt: _t.Any, model: _t.Any, tenant: _uuid.UUID | None) -> _t.Any:
    return stmt.where(model.tenant_id == tenant) if tenant is not None else stmt


def _fingerprint(*parts: object) -> str:
    """Salted (HMAC with the project secret): the stored request hash cannot be used to guess a document."""
    key = get_auth_settings().jwt_key.encode()
    return hmac.new(key, json.dumps(parts, separators=(",", ":"), default=str).encode(), hashlib.sha256).hexdigest()


_STRIP = re.compile(r"[\s,$\u20ac\u00a3]")


def _normal(text: str) -> str:
    return _STRIP.sub("", text).lower()


def _required(kind: str) -> set[str]:
    return {name for name, required in _config.KINDS.get(kind, []) if required}


def parse_field(raw: _t.Any, text: str) -> tuple[str | None, int, tuple[int, int, int, str] | None]:
    """(value, confidence_bp, anchor (page, start, end, quote) | None) of one model answer, checked against the text."""
    if not isinstance(raw, dict):
        return None, 0, None
    value = raw.get("value")
    if not isinstance(value, str) or value == "":
        return None, 0, None
    conf = raw.get("confidence_bp")
    confidence = conf if isinstance(conf, int) and not isinstance(conf, bool) and 0 <= conf <= 10_000 else 0
    start, end, quote = raw.get("start"), raw.get("end"), raw.get("quote")
    ints = all(isinstance(n, int) and not isinstance(n, bool) for n in (start, end))
    if not ints or not isinstance(quote, str) or not quote:
        return value, 0, None
    assert isinstance(start, int) and isinstance(end, int)
    if not 0 <= start < end <= len(text) or text[start:end] != quote:
        return value, 0, None
    if not _normal(value) or _normal(value) not in _normal(quote):  # the value must be supported by the text it points at
        return value, 0, None
    return value, confidence, (1 + text.count("\f", 0, start), start, end, quote)


def _messages(kind: str, text: str) -> list[_gw.Message]:
    names = ",".join(name for name, _ in _config.KINDS[kind])
    instruction = (
        f"{_providers.EXTRACT_PREFIX}{names}\n"
        "Extract these fields from the document that follows (segments marked SEGMENT <offset>). Answer one JSON object "
        '{"fields": {"<name>": {"value": str, "confidence_bp": int 0..10000, "start": int, "end": int, "quote": str}}} where '
        "start and end are character offsets into the whole document (end exclusive) and quote is the exact text at those "
        "offsets. Leave out a field you cannot find."
    )
    out = [_gw.Message(role="system", content=instruction)]
    for offset in range(0, len(text), SEGMENT_CHARS):
        out.append(_gw.Message(role="user", content=f"SEGMENT {offset}\n{text[offset : offset + SEGMENT_CHARS]}"))
    return out


# --- reads ---------------------------------------------------------------------------------------------------


def _field_out(f: AiDocumentField) -> _s.FieldOut:
    anchor = (
        _s.AnchorOut(page=f.anchor_page, start=f.anchor_start, end=f.anchor_end, quote=f.anchor_quote)
        if f.anchor_page is not None and f.anchor_start is not None and f.anchor_end is not None and f.anchor_quote is not None
        else None
    )
    return _s.FieldOut(
        name=f.name,
        value=f.value,
        confidence_bp=f.confidence_bp,
        anchor=anchor,
        corrected=f.corrected,
        original_value=f.original_value,
        review_required=f.review_required,
    )


def _doc_out(d: AiDocument, fields: list[AiDocumentField], with_content: bool = True) -> _s.DocumentOut:
    return _s.DocumentOut(
        id=d.id,
        kind=d.kind,
        title=d.title,
        status=_t.cast(_s.DocumentStatus, d.status),
        content=d.content if with_content else None,
        call_id=d.call_id,
        fields=[_field_out(f) for f in sorted(fields, key=lambda f: f.position)],
        reject_reason=d.reject_reason,
        reviewed_by=d.reviewed_by,
        reviewed_at=d.reviewed_at,
        created_by=d.created_by,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


async def _fields_of(session: AsyncSession, ids: list[_uuid.UUID]) -> dict[_uuid.UUID, list[AiDocumentField]]:
    found: dict[_uuid.UUID, list[AiDocumentField]] = {i: [] for i in ids}
    if ids:
        stmt = _sa.select(AiDocumentField).where(AiDocumentField.document_id.in_(ids)).execution_options(populate_existing=True)
        for f in (await session.execute(stmt)).scalars():
            found[f.document_id].append(f)
    return found


def _sees_all(user: _t.Any) -> bool:
    # an empty role list grants NOBODY the all-documents view (has_role treats empty as "everyone"): the default is own documents only
    return bool(_config.READ_ROLES and _gateway.has_role(user, _config.READ_ROLES)) or bool(
        _config.REVIEW_ROLES and _gateway.has_role(user, _config.REVIEW_ROLES)
    )


async def _load_out(session: AsyncSession, tenant: _uuid.UUID | None, document_id: _uuid.UUID) -> _s.DocumentOut:
    stmt = _scoped(_sa.select(AiDocument).where(AiDocument.id == document_id), AiDocument, tenant)
    doc = (await session.execute(stmt.execution_options(populate_existing=True))).scalar_one()
    return _doc_out(doc, (await _fields_of(session, [doc.id]))[doc.id])


async def get(session: AsyncSession, user: _t.Any, document_id: _uuid.UUID) -> _s.DocumentOut:
    tenant = _gateway.tenant_of(user)
    stmt = _scoped(_sa.select(AiDocument).where(AiDocument.id == document_id), AiDocument, tenant)
    if not _sees_all(user):
        stmt = stmt.where(AiDocument.created_by == user.id)
    doc = (await session.execute(stmt)).scalar_one_or_none()
    if doc is None:
        raise AppError("not_found", "document not found", 404)
    return _doc_out(doc, (await _fields_of(session, [doc.id]))[doc.id])


async def list_documents(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, status: str | None, kind: str | None
) -> tuple[list[_s.DocumentOut], int]:
    tenant = _gateway.tenant_of(user)
    conditions: list[_t.Any] = []
    if status is not None:
        conditions.append(AiDocument.status == status)
    if kind is not None:
        conditions.append(AiDocument.kind == kind)
    if not _sees_all(user):
        conditions.append(AiDocument.created_by == user.id)
    total = await session.scalar(_scoped(_sa.select(_sa.func.count()).select_from(AiDocument).where(*conditions), AiDocument, tenant))
    docs = list(
        (
            await session.execute(
                _scoped(_sa.select(AiDocument).where(*conditions), AiDocument, tenant)
                .order_by(AiDocument.created_at.desc(), AiDocument.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )
    fields = await _fields_of(session, [d.id for d in docs])
    return [_doc_out(d, fields[d.id], with_content=False) for d in docs], total or 0


# --- create (extraction) ------------------------------------------------------------------------------------


async def _existing(
    session: AsyncSession, tenant: _uuid.UUID | None, caller: _uuid.UUID | None, key: str, request_hash: str
) -> _s.DocumentOut | None:
    stmt = _scoped(
        _sa.select(AiDocument).where(AiDocument.created_by == caller, AiDocument.idempotency_key == key), AiDocument, tenant
    )
    found = (await session.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()
    if found is None:
        return None
    if found.request_hash != request_hash:
        raise AppError("idempotency_conflict", "this idempotency_key was already used for a different document", 409)
    return _doc_out(found, (await _fields_of(session, [found.id]))[found.id])


async def create(session: AsyncSession, user: _t.Any, body: _s.DocumentIn) -> tuple[_s.DocumentOut, bool]:
    tenant = _gateway.tenant_of(user)
    caller: _uuid.UUID | None = getattr(user, "id", None)
    if body.kind not in _config.KINDS:
        raise AppError("unknown_kind", f"there is no document kind {body.kind!r}", 422)
    if len(body.content) > _config.MAX_TEXT_CHARS or len(body.content) > SEGMENT_CHARS * MAX_SEGMENTS:
        raise AppError("content_too_large", f"the text is longer than {min(_config.MAX_TEXT_CHARS, SEGMENT_CHARS * MAX_SEGMENTS)} characters", 422)
    request_hash = _fingerprint(body.kind, body.title, body.content)
    key = body.idempotency_key
    if key is not None:
        replay = await _existing(session, tenant, caller, key, request_hash)
        if replay is not None:
            await session.commit()
            return replay, True
    text = body.content
    # the extraction call: budgeted, idempotent and in the ledger like any gateway call (it commits the session)
    result = await _gateway.complete(
        session,
        user,
        _gw.CompleteIn(
            stage=_config.STAGE,
            messages=_messages(body.kind, text),
            idempotency_key=f"doc:{_fingerprint('doc-call', key)}" if key is not None else None,  # salted: no collision with caller keys
            response_format="json",
        ),
        retain=False,  # the document text lives in ai_documents only, never in the call ledger
    )
    if result.replayed and result.output_json is None:
        # a parallel or earlier request ran this extraction; its text is not kept, so wait for ITS document instead
        for _ in range(60):
            assert key is not None
            replay = await _existing(session, tenant, caller, key, request_hash)
            await session.commit()
            if replay is not None:
                return replay, True
            await asyncio.sleep(0.05)
        raise AppError("retry_with_new_key", "the first attempt with this idempotency_key did not finish: retry with a new key", 409)
    answer = result.output_json.get("fields") if isinstance(result.output_json, dict) else None
    answer = answer if isinstance(answer, dict) else {}
    threshold = _config.REVIEW_BELOW_BP
    document_id = _uuid.uuid4()
    now = _now()
    doc = AiDocument(
        id=document_id,
        kind=body.kind,
        title=body.title,
        content=text,
        status="extracted",
        call_id=result.call_id,
        created_by=caller,
        idempotency_key=key,
        request_hash=request_hash,
        created_at=now,
        updated_at=now,
    )
    if tenant is not None:
        doc.tenant_id = tenant
    rows: list[AiDocumentField] = []
    needs_review = False
    for position, (name, required) in enumerate(_config.KINDS[body.kind]):
        value, confidence, anchor = parse_field(answer.get(name), text)
        flagged = value is None or anchor is None or confidence < threshold
        if (required and value is None) or (value is not None and flagged):
            needs_review = True
        field = AiDocumentField(
            id=_uuid.uuid4(),
            document_id=document_id,
            name=name,
            position=position,
            value=value,
            confidence_bp=confidence if value is not None else 0,
            anchor_page=anchor[0] if anchor else None,
            anchor_start=anchor[1] if anchor else None,
            anchor_end=anchor[2] if anchor else None,
            anchor_quote=anchor[3] if anchor else None,
            corrected=False,
            review_required=flagged,
        )
        if tenant is not None:
            field.tenant_id = tenant
        rows.append(field)
    doc.status = "needs_review" if needs_review else "extracted"
    out = _doc_out(doc, rows)
    session.add(doc)
    try:
        await session.flush()  # the document row first: the fields reference it
        session.add_all(rows)
        await session.commit()
    except IntegrityError:  # the same idempotency key won the race: return that document
        await session.rollback()
        if key is None:
            raise
        replay = await _existing(session, tenant, caller, key, request_hash)
        if replay is None:
            raise
        await session.commit()
        return replay, True
    return out, False


# --- review -------------------------------------------------------------------------------------------------


async def _lock(session: AsyncSession, tenant: _uuid.UUID | None, document_id: _uuid.UUID) -> AiDocument:
    stmt = _scoped(_sa.select(AiDocument).where(AiDocument.id == document_id), AiDocument, tenant)
    doc = (await session.execute(stmt.with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if doc is None:
        await session.rollback()
        raise AppError("not_found", "document not found", 404)
    return doc


async def _no_self_review(session: AsyncSession, user: _t.Any, doc: AiDocument) -> None:
    if not _config.ALLOW_SELF_REVIEW and doc.created_by is not None and doc.created_by == user.id:
        await session.rollback()
        raise AppError("self_review_forbidden", "the person who uploaded a document cannot review it", 403)


async def _closed(session: AsyncSession) -> AppError:
    await session.rollback()
    return AppError("document_closed", "this document is already approved or rejected", 409)


async def correct(session: AsyncSession, user: _t.Any, document_id: _uuid.UUID, name: str, value: str | None) -> _s.DocumentOut:
    tenant = _gateway.tenant_of(user)
    doc = await _lock(session, tenant, document_id)
    if doc.status in FINAL:
        raise await _closed(session)
    await _no_self_review(session, user, doc)
    field = (
        await session.execute(
            _sa.select(AiDocumentField)
            .where(AiDocumentField.document_id == document_id, AiDocumentField.name == name)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if field is None:
        await session.rollback()
        raise AppError("unknown_field", f"this document has no field {name!r}", 404)
    new_value = value if value not in (None, "") else None
    if not field.corrected:
        field.original_value = field.value
    field.value = new_value
    field.corrected = True
    field.confidence_bp = 10_000
    field.review_required = new_value is None
    field.anchor_page = field.anchor_start = field.anchor_end = field.anchor_quote = None  # the quote no longer describes the value
    doc.updated_at = _now()
    await session.commit()
    return await _load_out(session, tenant, document_id)


async def approve(
    session: AsyncSession, user: _t.Any, document_id: _uuid.UUID, acknowledge: list[str] | None = None
) -> _s.DocumentOut:
    tenant = _gateway.tenant_of(user)
    reviewer: _uuid.UUID | None = getattr(user, "id", None)
    doc = await _lock(session, tenant, document_id)
    if doc.status in FINAL:
        raise await _closed(session)
    await _no_self_review(session, user, doc)
    fields = (await _fields_of(session, [document_id]))[document_id]
    required = _required(doc.kind)
    missing = sorted(f.name for f in fields if f.name in required and (f.value is None or not f.value.strip()))
    if missing:
        await session.rollback()
        raise AppError(
            "missing_required_fields", "required fields have no value: correct them first", 422, [{"name": n} for n in missing]
        )
    names = {f.name for f in fields}
    acknowledged = set(acknowledge or [])
    if acknowledged - names:
        await session.rollback()
        raise AppError("unknown_field", f"this document has no field {sorted(acknowledged - names)[0][:40]!r}", 404)
    pending = sorted(f.name for f in fields if f.review_required and not f.corrected and f.value is not None and f.name not in acknowledged)
    if pending:
        await session.rollback()
        raise AppError(
            "review_pending",
            "flagged fields must be corrected or acknowledged (acknowledge: [names]) before approval",
            409,
            [{"name": n} for n in pending],
        )
    now = _now()
    doc.status, doc.reviewed_by, doc.reviewed_at, doc.updated_at = "approved", reviewer, now, now
    await session.commit()
    return await _load_out(session, tenant, document_id)


async def reject(session: AsyncSession, user: _t.Any, document_id: _uuid.UUID, reason: str | None) -> _s.DocumentOut:
    tenant = _gateway.tenant_of(user)
    reviewer: _uuid.UUID | None = getattr(user, "id", None)
    doc = await _lock(session, tenant, document_id)
    if doc.status in FINAL:
        raise await _closed(session)
    await _no_self_review(session, user, doc)
    now = _now()
    doc.status, doc.reviewed_by, doc.reviewed_at, doc.updated_at, doc.reject_reason = "rejected", reviewer, now, now, reason
    await session.commit()
    return await _load_out(session, tenant, document_id)

