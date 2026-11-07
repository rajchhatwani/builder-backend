"""Requirements map (B3-6): quarantined intake of prompts/documents, questions, hand-off to a run.

GET  /projects/{project_id}/requirements                          map (viewer)
POST /projects/{project_id}/requirements/intake                   multipart prompt + files (editor)
POST /projects/{project_id}/requirements/questions/{qid}/answer   {answer?|accept_assumption?} (editor)
PUT  /projects/{project_id}/requirements/items/{item_id}          edit text/status/covered_by (editor)
POST /projects/{project_id}/requirements/start-run                create an agent run from the map (editor)
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_verified_email
from app.db import get_session
from app.exceptions import AppError
from app.schemas.agent_run import RunRead
from app.schemas.requirements import ItemUpdate, QuestionAnswer, RequirementsRead, StartRun
from app.services.access_service import Principal
from app.services.agent.run_service import get_agent_deps
from app.services.requirements import reader as rd
from app.services.requirements.service import ReaderDeps, RequirementsService

router = APIRouter(prefix="/projects/{project_id}/requirements", tags=["requirements"])


def reader_deps() -> ReaderDeps:
    """Overridable: the model-provider factory and settings the reader runs with."""
    try:
        d = get_agent_deps()
    except AppError:
        return ReaderDeps()
    return ReaderDeps(provider_factory=d.provider_factory, settings=d.settings)


@router.get("", response_model=RequirementsRead)
async def get_requirements(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> RequirementsRead:
    return await RequirementsService(db).get(project_id)


@router.post("/intake", response_model=RequirementsRead)
async def intake(
    project_id: uuid.UUID,
    prompt: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    principal: Principal = Depends(require_verified_email),
    deps: ReaderDeps = Depends(reader_deps),
    db: AsyncSession = Depends(get_session),
) -> RequirementsRead:
    if len(files) > rd.MAX_FILES:
        raise AppError("too_many_files", f"at most {rd.MAX_FILES} files per intake", 413)
    loaded: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read(rd.MAX_FILE_BYTES + 1)  # never buffer more than the cap allows
        loaded.append((f.filename or "document", data))
    return await RequirementsService(db).intake(project_id, principal.user.id, prompt, loaded, deps)


@router.post("/questions/{question_id}/answer", response_model=RequirementsRead)
async def answer_question(
    project_id: uuid.UUID,
    question_id: uuid.UUID,
    body: QuestionAnswer,
    db: AsyncSession = Depends(get_session),
) -> RequirementsRead:
    return await RequirementsService(db).answer(
        project_id, question_id, body.answer, body.accept_assumption
    )


@router.put("/items/{item_id}", response_model=RequirementsRead)
async def update_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemUpdate,
    db: AsyncSession = Depends(get_session),
) -> RequirementsRead:
    return await RequirementsService(db).update_item(project_id, item_id, body)


@router.post("/start-run", response_model=RunRead, status_code=201)
async def start_run(
    project_id: uuid.UUID,
    body: StartRun,
    principal: Principal = Depends(require_verified_email),
    db: AsyncSession = Depends(get_session),
) -> RunRead:
    run = await RequirementsService(db).start_run(
        project_id, principal.user.id, body.accept_assumptions, body.phase, body.workspace_id
    )
    return RunRead.model_validate(run)
