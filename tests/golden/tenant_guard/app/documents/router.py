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
from app.auth import field_access as _fx
from app.auth.deps import CurrentUser, require_roles
from app.auth.ratelimit import RateLimiter
from app.auth.service import effective_roles
from app.core.errors import AppError
from app.crud.employees import EmployeeRepository
from app.db import SessionDep
from app.documents import engine
from app.documents.data import TEMPLATES
from app.routers import employees as employees_routes
from app.schemas.employees import EmployeeRead

logger = structlog.get_logger()
router = APIRouter(prefix="/documents", tags=["documents"])
_limit = RateLimiter("documents", '600/minute')

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
    "/employee_card/records/{record_id}",
    dependencies=[Depends(_limit), Depends(require_roles(*TEMPLATES["employee_card"]["roles"]))],
    response_class=Response,
    responses=PDF,
    summary="Render Employee card for one Employee",
)
async def render_employee_card_record(
    record_id: uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(employees_routes._ACCESS["get"])],
    body: RecordBody | None = None,
) -> Response:
    item = await EmployeeRepository(session, **access.repo_kwargs).get(record_id)
    row = _fx.shape("Employee", access.user, EmployeeRead.model_validate(item)).model_dump(
        mode="json", exclude_unset=True
    )
    # The record's own values are `row`; caller-supplied `extra` can never replace them.
    data = {"row": row, "extra": body.extra if body else {}, "now": datetime.date.today().isoformat()}
    return await _respond("employee_card", data)
