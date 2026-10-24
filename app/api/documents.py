"""Routes for the PDF document templates of a project, the library and the live preview."""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.documents import (
    DocumentsIssues,
    DocumentsRead,
    DocumentsWrite,
    LibraryItem,
    PreviewRequest,
)
from app.services.documents_service import DocumentsService, library, render_preview
from app.services.spec_service import SpecService

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])


@router.get("", response_model=DocumentsRead, summary="Get the document templates")
async def get_documents(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> DocumentsRead:
    return await DocumentsService(session).get(project_id)


@router.put("", response_model=DocumentsRead, summary="Create or replace the document templates")
async def put_documents(
    project_id: uuid.UUID,
    body: DocumentsWrite,
    session: AsyncSession = Depends(get_session),
) -> DocumentsRead:
    return await DocumentsService(session).put(project_id, body)


@router.get(
    "/issues",
    response_model=DocumentsIssues,
    summary="Problems with the document templates (no side effects)",
)
async def documents_issues(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> DocumentsIssues:
    await DocumentsService(session).get(project_id)  # 404 for an unknown project
    found = await SpecService(session).validate(project_id)
    return DocumentsIssues(issues=[i.model_dump() for i in found if i.path.startswith("documents")])


@router.get(
    "/library",
    response_model=list[LibraryItem],
    summary="The ten built-in templates, with sample data and why each exists",
)
async def documents_library(project_id: uuid.UUID) -> list[LibraryItem]:
    return library()


@router.post(
    "/preview",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    summary="Render a template with data and return the PDF (nothing is saved)",
)
async def documents_preview(project_id: uuid.UUID, body: PreviewRequest) -> Response:
    pdf = render_preview(body)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="preview.pdf"',
            "Cache-Control": "no-store",
        },
    )
