"""PDF document templates of a project: settings, the library, and the live preview."""

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core import doc_engine as engine
from app.core import doc_library
from app.core.spec_models import SpecDocTemplate, SpecDocuments
from app.exceptions import AppError
from app.models.documents_config import ProjectDocuments
from app.models.project import Project
from app.schemas.documents import (
    DocumentsRead,
    DocumentsWrite,
    LibraryItem,
    PreviewRequest,
)


def config_to_spec(row: ProjectDocuments) -> SpecDocuments:
    return SpecDocuments.model_validate({**row.settings, "enabled": row.enabled})


def apply_spec(row: ProjectDocuments, spec: SpecDocuments) -> None:
    row.enabled = spec.enabled
    row.settings = spec.model_dump(mode="json", exclude={"enabled"})


def library() -> list[LibraryItem]:
    return [
        LibraryItem(
            id=key,
            title=entry["title"],
            industries=entry["industries"],
            why=entry["why"],
            compute=entry["compute"],
            template=entry["template"],
            sample=entry["sample"],
        )
        for key, entry in doc_library.LIBRARY.items()
    ]


MAX_PREVIEW_CELLS = 20_000  # table cells (columns x rows, summed over blocks) per preview
_PREVIEW_SLOTS = asyncio.Semaphore(2)  # at most two renders at once per worker


def _preview_cells(template: dict[str, Any], data: dict[str, Any]) -> int:
    """Upper bound of the table cells the build would lay out, without building anything."""
    blocks = template.get("blocks")
    if not isinstance(blocks, list):
        return 0
    total = 0
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "table":
            continue
        cols = block.get("columns")
        source = block.get("source")
        rows = lookup_rows(data, source) if isinstance(source, str) else 0
        total += (len(cols) if isinstance(cols, list) else 0) * max(rows, 1)
    return total


def lookup_rows(data: dict[str, Any], path: str) -> int:
    value = engine.lookup(data, path)
    return len(value) if isinstance(value, list) else 0


async def render_preview_async(body: PreviewRequest) -> bytes:
    """render_preview off the event loop, with a concurrency limit."""
    async with _PREVIEW_SLOTS:
        return await run_in_threadpool(render_preview, body)


def render_preview(body: PreviewRequest) -> bytes:
    """The PDF the generated API would produce for this template and data."""
    if _preview_cells(body.template, body.data) > MAX_PREVIEW_CELLS:
        raise AppError(
            code="validation_error",
            message=f"the preview would lay out more than {MAX_PREVIEW_CELLS} table cells",
            status_code=422,
        )
    try:
        return engine.render_pdf(body.template, body.data, compute=body.compute)
    except engine.DocumentError as exc:
        raise AppError(code="validation_error", message=str(exc), status_code=422) from exc


class DocumentsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _row(self, project_id: uuid.UUID, *, lock: bool = False) -> ProjectDocuments | None:
        query = select(ProjectDocuments).where(ProjectDocuments.project_id == project_id)
        if lock:  # serialise concurrent saves so the expected_version check cannot be raced
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def get(self, project_id: uuid.UUID) -> DocumentsRead:
        await self._project(project_id)
        row = await self._row(project_id)
        if row is None:
            return DocumentsRead(
                project_id=project_id,
                version=0,
                enabled=False,
                templates=[],
                rate_limit="30/minute",
            )
        spec = config_to_spec(row)
        return DocumentsRead(
            project_id=project_id,
            version=row.version,
            updated_at=row.updated_at,
            **spec.model_dump(mode="json"),
        )

    async def put(self, project_id: uuid.UUID, data: DocumentsWrite) -> DocumentsRead:
        await self._project(project_id)
        row = await self._row(project_id, lock=True)
        current = row.version if row is not None else 0
        if data.expected_version is not None and data.expected_version != current:
            raise AppError(
                code="conflict",
                message="the document settings changed since you opened them; reload and apply "
                "your edit again",
                status_code=409,
            )
        ids = [t.id for t in data.templates]
        if len(ids) != len(set(ids)):
            raise AppError(
                code="validation_error", message="template ids must be unique", status_code=422
            )
        spec = SpecDocuments.model_validate(data.model_dump(exclude={"expected_version"}))
        if row is None:
            row = ProjectDocuments(project_id=project_id, version=1)
            self.session.add(row)
        else:
            row.version = current + 1
        apply_spec(row, spec)
        try:
            await self.session.commit()
        except IntegrityError as exc:  # two first saves raced
            await self.session.rollback()
            raise AppError(
                code="conflict",
                message="the settings were saved by someone else just now; reload and retry",
                status_code=409,
            ) from exc
        return await self.get(project_id)

    @staticmethod
    def template_from_library(template_id: str) -> SpecDocTemplate:
        entry = doc_library.get(template_id)
        return SpecDocTemplate(
            id=template_id,
            title=entry["title"],
            kind=template_id,
            compute=entry["compute"],
            template=entry["template"],
        )
