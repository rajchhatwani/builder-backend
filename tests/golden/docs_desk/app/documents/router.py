"""PDF documents (generated). See docs/DOCUMENTS.md.

GET  /documents                              the templates the signed-in person may render
POST /documents/<id>/render                  render from the data in the request body
POST /documents/<id>/records/{record_id}     render a stored record (the entity's own access rules apply)

Every route needs sign-in and one of the template's roles, and is rate limited. Rendering runs in a
thread so it never blocks other requests. Nothing about a document (data, text) is logged.
"""

import datetime
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.auth import access as _access
from app.auth.deps import CurrentUser, require_roles
from app.auth.ratelimit import RateLimiter
from app.auth.service import effective_roles
from app.core.errors import AppError
from app.crud.tickets import TicketRepository
from app.db import SessionDep
from app.documents import engine
from app.documents.data import TEMPLATES
from app.routers import tickets as tickets_routes
from app.schemas.tickets import TicketRead

logger = structlog.get_logger()
router = APIRouter(prefix="/documents", tags=["documents"])
_limit = RateLimiter("documents", '60/minute')

PDF = {200: {"content": {"application/pdf": {}}, "description": "The document"}}


class RenderBody(BaseModel):
    """The data the template's placeholders read, for example {"number": "INV-1", "items": [...]}."""

    data: dict[str, Any] = Field(default_factory=dict)


class RecordBody(BaseModel):
    """Optional extra data next to the record (for example line items); the record's own values win."""

    extra: dict[str, Any] = Field(default_factory=dict)


class TemplateInfo(BaseModel):
    id: str
    title: str
    kind: str
    entity: str | None


async def _respond(template_id: str, data: dict[str, Any]) -> Response:
    spec = TEMPLATES[template_id]
    try:
        pdf = await run_in_threadpool(
            engine.render_pdf, spec["template"], data, compute=spec["compute"]
        )
    except engine.DocumentError as exc:
        raise AppError("invalid_document", str(exc), 422) from exc
    logger.info("document_rendered", template=template_id, bytes=len(pdf))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{template_id}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("", response_model=list[TemplateInfo], dependencies=[Depends(_limit)])
async def list_templates(user: CurrentUser) -> list[TemplateInfo]:
    held = effective_roles(user.roles)
    return [
        TemplateInfo(id=t["id"], title=t["title"], kind=t["kind"], entity=t["entity"])
        for t in TEMPLATES.values()
        if held & set(t["roles"])
    ]


@router.post(
    "/ticket_summary/records/{record_id}",
    dependencies=[Depends(_limit), Depends(require_roles(*TEMPLATES["ticket_summary"]["roles"]))],
    response_class=Response,
    responses=PDF,
    summary="Render Ticket summary for one Ticket",
)
async def render_ticket_summary_record(
    record_id: uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(tickets_routes._ACCESS["get"])],
    body: RecordBody | None = None,
) -> Response:
    item = await TicketRepository(session, **access.repo_kwargs).get(record_id)
    row = TicketRead.model_validate(item).model_dump(mode="json")
    # The record's own values are `row`; caller-supplied `extra` can never replace them.
    data = {"row": row, "extra": body.extra if body else {}, "now": datetime.date.today().isoformat()}
    return await _respond("ticket_summary", data)


@router.post(
    "/invoice/render",
    dependencies=[Depends(_limit), Depends(require_roles(*TEMPLATES["invoice"]["roles"]))],
    response_class=Response,
    responses=PDF,
    summary="Render Invoice from the data in the request",
)
async def render_invoice(body: RenderBody) -> Response:
    return await _respond("invoice", body.data)


@router.post(
    "/receipt/render",
    dependencies=[Depends(_limit), Depends(require_roles(*TEMPLATES["receipt"]["roles"]))],
    response_class=Response,
    responses=PDF,
    summary="Render Receipt from the data in the request",
)
async def render_receipt(body: RenderBody) -> Response:
    return await _respond("receipt", body.data)


@router.post(
    "/certificate/render",
    dependencies=[Depends(_limit), Depends(require_roles(*TEMPLATES["certificate"]["roles"]))],
    response_class=Response,
    responses=PDF,
    summary="Render Certificate from the data in the request",
)
async def render_certificate(body: RenderBody) -> Response:
    return await _respond("certificate", body.data)
