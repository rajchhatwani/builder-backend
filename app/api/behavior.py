"""Routes for the declarative behaviour of a project (state machines, settings, sequences, lists)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation_behavior import check_expression, expr_schema
from app.db import get_session
from app.exceptions import AppError
from app.schemas.behavior import (
    BehaviorIssues,
    ExpressionCheckBody,
    ExpressionCheckRead,
    ExpressionError,
    ExpressionField,
    HistoryRead,
    HistoryWrite,
    HooksRead,
    HooksWrite,
    ListsRead,
    ListsWrite,
    SeedRead,
    SeedWrite,
    SequencesRead,
    SequencesWrite,
    SettingsRead,
    SettingsWrite,
    StateMachinesRead,
    StateMachinesWrite,
)
from app.services.behavior_service import SECTIONS, BehaviorService
from app.services.spec_service import SpecService

router = APIRouter(prefix="/projects/{project_id}/behavior", tags=["behavior"])


@router.get(
    "/state-machines",
    response_model=StateMachinesRead,
    summary="Get the state machines (empty when never saved)",
)
async def get_state_machines(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> StateMachinesRead:
    return await BehaviorService(session).get_state_machines(project_id)


@router.put(
    "/state-machines", response_model=StateMachinesRead, summary="Replace every state machine"
)
async def put_state_machines(
    project_id: uuid.UUID,
    body: StateMachinesWrite,
    session: AsyncSession = Depends(get_session),
) -> StateMachinesRead:
    return await BehaviorService(session).put_state_machines(project_id, body)


@router.get("/settings", response_model=SettingsRead, summary="Get the runtime settings")
async def get_settings(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> SettingsRead:
    return await BehaviorService(session).get_settings(project_id)


@router.put("/settings", response_model=SettingsRead, summary="Replace every runtime setting")
async def put_settings(
    project_id: uuid.UUID, body: SettingsWrite, session: AsyncSession = Depends(get_session)
) -> SettingsRead:
    return await BehaviorService(session).put_settings(project_id, body)


@router.get("/sequences", response_model=SequencesRead, summary="Get the gapless sequences")
async def get_sequences(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> SequencesRead:
    return await BehaviorService(session).get_sequences(project_id)


@router.put("/sequences", response_model=SequencesRead, summary="Replace every sequence")
async def put_sequences(
    project_id: uuid.UUID, body: SequencesWrite, session: AsyncSession = Depends(get_session)
) -> SequencesRead:
    return await BehaviorService(session).put_sequences(project_id, body)


@router.get("/lists", response_model=ListsRead, summary="Get the tenant-editable lists")
async def get_lists(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> ListsRead:
    return await BehaviorService(session).get_lists(project_id)


@router.put("/lists", response_model=ListsRead, summary="Replace every list")
async def put_lists(
    project_id: uuid.UUID, body: ListsWrite, session: AsyncSession = Depends(get_session)
) -> ListsRead:
    return await BehaviorService(session).put_lists(project_id, body)


@router.get("/history", response_model=HistoryRead, summary="Get the change-history settings")
async def get_history(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> HistoryRead:
    return await BehaviorService(session).get_history(project_id)


@router.put("/history", response_model=HistoryRead, summary="Replace every change-history config")
async def put_history(
    project_id: uuid.UUID, body: HistoryWrite, session: AsyncSession = Depends(get_session)
) -> HistoryRead:
    return await BehaviorService(session).put_history(project_id, body)


@router.get("/hooks", response_model=HooksRead, summary="Get the declared custom hooks")
async def get_hooks(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> HooksRead:
    return await BehaviorService(session).get_hooks(project_id)


@router.put("/hooks", response_model=HooksRead, summary="Replace every hook declaration")
async def put_hooks(
    project_id: uuid.UUID, body: HooksWrite, session: AsyncSession = Depends(get_session)
) -> HooksRead:
    return await BehaviorService(session).put_hooks(project_id, body)


@router.get("/seed", response_model=SeedRead, summary="Get the seed profiles (the seed plan)")
async def get_seed(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> SeedRead:
    return await BehaviorService(session).get_seed(project_id)


@router.put("/seed", response_model=SeedRead, summary="Replace every seed profile")
async def put_seed(
    project_id: uuid.UUID, body: SeedWrite, session: AsyncSession = Depends(get_session)
) -> SeedRead:
    return await BehaviorService(session).put_seed(project_id, body)


@router.get(
    "/issues",
    response_model=BehaviorIssues,
    summary="Problems with the behaviour sections (no side effects)",
)
async def behavior_issues(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> BehaviorIssues:
    await BehaviorService(session).get_state_machines(project_id)  # 404 for an unknown project
    found = await SpecService(session).validate(project_id)
    return BehaviorIssues(
        issues=[i.model_dump() for i in found if i.path.startswith(SECTIONS)]
    )


@router.post(
    "/expressions/check",
    response_model=ExpressionCheckRead,
    summary="Check an expression against an entity's current fields (no side effects)",
)
async def check_expression_route(
    project_id: uuid.UUID, body: ExpressionCheckBody, session: AsyncSession = Depends(get_session)
) -> ExpressionCheckRead:
    """Same judge as the validation report (`validation_behavior.check_expression`), so the error
    text is identical. Nothing is evaluated or saved; `fields` is what the expression may read."""
    spec = await SpecService(session).assemble(project_id)  # 404 for an unknown project
    entity = next((e for e in spec.entities if e.name == body.entity), None)
    if entity is None:
        raise AppError(code="not_found", message="entity not found", status_code=404)
    schema = expr_schema(entity)
    verdict = check_expression(body.expression, schema, body.expect)
    return ExpressionCheckRead(
        ok=verdict.ok,
        type=verdict.type,
        error=None
        if verdict.ok
        else ExpressionError(message=verdict.message or "", pos=verdict.pos),
        fields=[ExpressionField(name=n, type=t, nullable=nl) for n, (t, nl) in schema.items()],
    )
