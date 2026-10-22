import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.db import get_session
from app.schemas.common import Page
from app.schemas.generation import GenerationDetail, GenerationSummary, PreviewResponse
from app.services.generation_service import GenerationService

router = APIRouter(tags=["generate"])


@router.post("/projects/{project_id}/generate/preview", response_model=PreviewResponse)
async def preview(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> PreviewResponse:
    return await GenerationService(session).preview(project_id)


@router.get(
    "/projects/{project_id}/generate/download",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def download(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Response:
    content, filename, generation = await GenerationService(session).download(project_id)
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Generation-Id": str(generation.id),
            "X-Spec-Hash": generation.spec_hash,
        },
    )


@router.get("/projects/{project_id}/generations", response_model=Page[GenerationSummary])
async def list_generations(
    project_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[GenerationSummary]:
    items, total = await GenerationService(session).list(project_id, page.limit, page.offset)
    return Page[GenerationSummary](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/generations/{generation_id}", response_model=GenerationDetail)
async def get_generation(
    generation_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> GenerationDetail:
    return await GenerationService(session).get(generation_id)
