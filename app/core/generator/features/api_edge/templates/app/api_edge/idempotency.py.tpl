"""Idempotency keys (generated).

The claim is inserted in the request's own transaction, the response is stored in that same
transaction, and the middleware commits both together with the business write. So:
  * a second request with the same key waits on the unique row until the first has committed (then it
    replays) or rolled back (then it runs); if it waits longer than LOCK_WAIT it gets 409;
  * a crash or a rolled-back write leaves no stored success, and a stored success always has its write;
  * only 2xx responses are stored. Keys are scoped to tenant and caller, so nobody replays another's.

Known limit (tracked for Cycle 3): a replay is served BEFORE the route's own authorization runs
again. A user whose role was revoked can therefore replay THEIR OWN earlier response (never anyone
else's) until its TTL ends. The spec caps `idempotency.ttl_hours` at 168 (7 days) to bound that."""

import datetime as dt
import hashlib
import re
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_edge import definitions
from app.api_edge.caller import Caller
from app.api_edge.models import COMPLETED, IN_PROGRESS, ApiIdempotency
from app.api_edge.state import Replay
from app.core.errors import AppError
from app.models._base import utcnow

KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{8,128}$")
LOCK_WAIT = "2000ms"
MAX_REQUEST_BYTES = 1_048_576
KEPT_HEADERS = ("content-type", "location")  # never Authorization, never Set-Cookie
KEPT_HEADERS_RAW = tuple(name.encode() for name in KEPT_HEADERS)
_LOCK_NOT_AVAILABLE = "55P03"


def now() -> dt.datetime:
    return utcnow()  # tests replace this


def parse_key(raw: str) -> str:
    if KEY_RE.fullmatch(raw) is None:
        raise AppError(
            "invalid_idempotency_key",
            "Idempotency-Key must be 8 to 128 characters: letters, digits and _ - . :",
            400,
        )
    return raw


def request_hash(method: str, target: str, content_type: str, body: bytes) -> str:
    """What makes two requests 'the same': method, path with query, content type and the exact body."""
    digest = hashlib.sha256()
    for part in (method.upper().encode(), target.encode(), content_type.lower().encode(), body):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def _lock_timeout(exc: DBAPIError) -> bool:
    orig = exc.orig
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == _LOCK_NOT_AVAILABLE or "lock timeout" in str(exc).lower()


async def claim(
    session: AsyncSession, caller: Caller, key: str, method: str, path: str, req_hash: str
) -> uuid.UUID | Replay:
    """The id of the new claim (the caller owns the key), or the stored response to replay. Raises 409 while the
    first request is still running and 422 when the key was used for a different request."""
    cfg = definitions.IDEMPOTENCY
    assert cfg is not None
    at = now()
    scope = (
        ApiIdempotency.tenant_key == caller.tenant_key,
        ApiIdempotency.principal_key == caller.principal_key,
        ApiIdempotency.key == key,
    )
    previous = (await session.execute(sa.text("SELECT current_setting('lock_timeout')"))).scalar_one()
    await session.execute(sa.text("SELECT set_config('lock_timeout', :v, true)"), {"v": LOCK_WAIT})
    try:
        await session.execute(sa.delete(ApiIdempotency).where(*scope, ApiIdempotency.expires_at <= at))
        inserted = (
            await session.execute(
                pg_insert(ApiIdempotency)
                .values(
                    id=uuid.uuid4(),
                    tenant_key=caller.tenant_key,
                    principal_key=caller.principal_key,
                    key=key,
                    method=method,
                    path=path[:500],
                    request_hash=req_hash,
                    status=IN_PROGRESS,
                    created_at=at,
                    expires_at=at + dt.timedelta(hours=cfg["ttl_hours"]),
                )
                .on_conflict_do_nothing(constraint="uq_api_idempotency_scope_key")
                .returning(ApiIdempotency.id)
            )
        ).scalar_one_or_none()
    except DBAPIError as exc:
        await session.rollback()
        if _lock_timeout(exc):
            raise AppError(
                "idempotency_in_progress", "A request with this Idempotency-Key is still being processed", 409
            ) from None
        raise
    await session.execute(sa.text("SELECT set_config('lock_timeout', :v, true)"), {"v": previous})
    if inserted is not None:
        return inserted
    stored = (await session.execute(sa.select(ApiIdempotency).where(*scope))).scalar_one_or_none()
    if stored is None:  # vanished between the two statements (expired and purged): never guess
        raise AppError("idempotency_in_progress", "Retry the request", 409)
    if stored.request_hash != req_hash:
        raise AppError(
            "idempotency_key_reused", "This Idempotency-Key was already used for a different request", 422
        )
    if stored.status != COMPLETED or stored.response_status is None or stored.response_body is None:
        raise AppError(
            "idempotency_in_progress", "A request with this Idempotency-Key is still being processed", 409
        )
    headers = [(str(n), str(v)) for n, v in (stored.response_headers or [])]
    return Replay(status=stored.response_status, headers=headers, body=stored.response_body)


async def finalize(
    session: AsyncSession, claim_id: uuid.UUID, status: int, headers: list[tuple[str, str]], body: bytes
) -> bool:
    """Store the response on the claim (same transaction). False if the claim is no longer there."""
    kept = [[n, v] for n, v in headers if n.lower() in KEPT_HEADERS]
    result = await session.execute(
        sa.update(ApiIdempotency)
        .where(ApiIdempotency.id == claim_id, ApiIdempotency.status == IN_PROGRESS)
        .values(status=COMPLETED, response_status=status, response_headers=kept, response_body=body)
    )
    return getattr(result, "rowcount", 0) == 1


async def purge(session: AsyncSession) -> int:
    """Delete expired keys. Returns how many."""
    result = await session.execute(sa.delete(ApiIdempotency).where(ApiIdempotency.expires_at <= now()))
    return int(getattr(result, "rowcount", 0) or 0)
