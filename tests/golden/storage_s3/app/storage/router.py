"""HTTP routes of the file API (generated).

Everything here is deny-by-default: a role list that is empty in the settings means nobody may call
the route, and a file the caller may not see is reported exactly like a file that does not exist.
"""

import ipaddress
import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.datastructures import UploadFile

from app.auth.deps import CurrentUser
from app.core.errors import AppError
from app.core.pagination import Page, PageParams, page_params
from app.db import SessionDep
from app.storage import access, clamav, config, service
from app.storage.backend import BackendUnavailable, get_backend
from app.storage.schemas import (
    AuditEntryRead,
    AuditTrailRead,
    BackendStatus,
    FileRead,
    QuarantineRequest,
    ScannerStatus,
    StorageStatus,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/files", tags=["files"])
_PAGE = Depends(page_params(20, 100))

_UPLOAD_DOC = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "shared": {
                            "type": "string",
                            "enum": ["true", "false"],
                            "description": "true makes the file readable by everyone who may read files",
                        },
                    },
                }
            }
        },
    }
}


def request_info(request: Request) -> service.RequestInfo:
    """Where the request came from, for the audit trail (None when the project does not log IPs).

    X-Forwarded-For is only believed for as many proxies as STORAGE_TRUSTED_PROXIES says: anyone
    can send that header, so the address is taken from the right (the part our own proxy added)."""
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if not config.AUDIT_IP:
        return service.RequestInfo(ip=None, request_id=request_id)
    candidate = request.client.host if request.client else None
    proxies = config.get_storage_settings().storage_trusted_proxies
    if proxies:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= proxies:
            candidate = hops[-proxies]
    try:
        ip = str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        ip = None
    return service.RequestInfo(ip=ip, request_id=request_id)


def _file_required() -> AppError:
    return AppError(
        "file_required", "send exactly one file in a multipart form field named 'file'", 422
    )


@router.post(
    "",
    response_model=FileRead,
    status_code=201,
    summary="Upload a file",
    openapi_extra=_UPLOAD_DOC,
)
async def upload_file(request: Request, session: SessionDep, user: CurrentUser) -> FileRead:
    """Send a multipart form with one `file` part (and optionally `shared=true`). The file is checked,
    scanned for malware and only then stored; the response says what it was found to be."""
    info = request_info(request)
    async with request.form(max_files=1, max_fields=3, max_part_size=1024) as form:
        files = form.getlist("file")
        stray = [key for key, value in form.multi_items() if isinstance(value, UploadFile) and key != "file"]
        if len(files) != 1 or stray or not isinstance(files[0], UploadFile):
            raise _file_required()
        flag = str(form.get("shared", "false")).lower()
        if flag not in ("true", "false"):
            raise AppError("validation_error", "shared must be true or false", 422)
        upload = files[0]
        row = await service.upload(
            session,
            user,
            upload.file,
            filename=upload.filename,
            declared_type=upload.content_type,
            shared=flag == "true",
            info=info,
        )
    return FileRead.from_row(row)


@router.get("", response_model=Page[FileRead], summary="List the files you may see")
async def list_files(
    session: SessionDep,
    user: CurrentUser,
    page: Annotated[PageParams, _PAGE],
    mine: Annotated[bool, Query(description="only files you uploaded")] = False,
) -> Page[FileRead]:
    rows, total = await service.list_files(session, user, page, mine=mine)
    return Page[FileRead](
        items=[FileRead.from_row(r) for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/status", response_model=StorageStatus, summary="Scanner and bucket health")
async def storage_status(session: SessionDep, user: CurrentUser) -> StorageStatus:
    access.require_role(user, "operate")
    settings = config.get_storage_settings()
    host, port = settings.clamd_host, settings.clamd_port
    try:
        scanner_ok = await clamav.ping(host, port)
    except clamav.ScannerUnavailable:
        scanner_ok = False
    engine = await clamav.engine_version(host, port) if scanner_ok else None
    try:
        await get_backend().check()
        bucket_ok = True
    except BackendUnavailable:
        bucket_ok = False
    return StorageStatus(
        scanner=ScannerStatus(ok=scanner_ok, engine=engine),
        bucket=BackendStatus(ok=bucket_ok),
        max_file_bytes=config.MAX_FILE_BYTES,
        allowed_types=list(config.ALLOWED_TYPES),
        download_mode=config.DOWNLOAD_MODE,
    )


@router.get("/{file_id}", response_model=FileRead, summary="Get a file's details")
async def get_file(file_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> FileRead:
    return FileRead.from_row(await service.get_visible(session, user, file_id))


@router.get(
    "/{file_id}/download",
    summary="Download a file",
    responses={200: {"content": {"application/octet-stream": {}}}, 307: {"description": "presigned link"}},
    response_class=Response,
)
async def download_file(
    request: Request,
    file_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    inline: Annotated[bool, Query(description="show an image in the browser (if enabled)")] = False,
) -> Response:
    result = await service.prepare_download(
        session, user, file_id, inline=inline, info=request_info(request)
    )
    if result.redirect_url is not None:
        return RedirectResponse(result.redirect_url, status_code=307, headers=result.headers)
    assert result.stream is not None
    return StreamingResponse(result.stream, headers=result.headers)


@router.delete("/{file_id}", status_code=204, summary="Delete a file for good")
async def delete_file(
    request: Request, file_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Response:
    await service.delete_file(session, user, file_id, request_info(request))
    return Response(status_code=204)


@router.get("/{file_id}/audit", response_model=AuditTrailRead, summary="Audit trail of a file")
async def file_audit(file_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> AuditTrailRead:
    ok, bad, entries = await service.audit_trail(session, user, file_id)
    return AuditTrailRead(
        file_id=file_id,
        chain_ok=ok,
        first_bad_seq=bad,
        entries=[AuditEntryRead.model_validate(e) for e in entries],
    )


@router.post("/{file_id}/quarantine", response_model=FileRead, summary="Block a file")
async def quarantine_file(
    request: Request,
    file_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    body: QuarantineRequest | None = None,
) -> FileRead:
    row = await service.quarantine(
        session, user, file_id, (body.reason if body else "manual"), request_info(request)
    )
    return FileRead.from_row(row)


@router.post("/{file_id}/release", response_model=FileRead, summary="Unblock a file after a fresh scan")
async def release_file(
    request: Request, file_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> FileRead:
    row = await service.release(session, user, file_id, request_info(request))
    return FileRead.from_row(row)

