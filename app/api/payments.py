"""Routes for a project's payments settings, the derived sizing, and the guarded switch."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.payments import (
    PaymentsConfigRead,
    PaymentsConfigWrite,
    PaymentsImpact,
    PaymentsSizingRead,
    PaymentsSwitchRequest,
)
from app.services.payments_service import PaymentsService, sizing_payload
from app.services.spec_service import SpecService

router = APIRouter(prefix="/projects/{project_id}/payments", tags=["payments"])


@router.get("", response_model=PaymentsConfigRead, summary="Get the payments settings")
async def get_payments(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> PaymentsConfigRead:
    return PaymentsConfigRead.model_validate(await PaymentsService(session).get(project_id))


@router.put(
    "",
    response_model=PaymentsConfigRead,
    summary="Create or replace the payments settings (does not switch payments on or off)",
)
async def put_payments(
    project_id: uuid.UUID,
    body: PaymentsConfigWrite,
    session: AsyncSession = Depends(get_session),
) -> PaymentsConfigRead:
    return PaymentsConfigRead.model_validate(await PaymentsService(session).put(project_id, body))


@router.get(
    "/sizing",
    response_model=PaymentsSizingRead,
    summary="Replicas, pools and workers derived from the expected load (an estimate)",
)
async def payments_sizing(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> PaymentsSizingRead:
    sizing = await PaymentsService(session).sizing(project_id)
    issues = [
        i.model_dump()
        for i in await SpecService(session).validate(project_id)
        if i.path.startswith("payments")
    ]
    return PaymentsSizingRead(sizing=sizing_payload(sizing), issues=issues)


@router.get(
    "/impact", response_model=PaymentsImpact, summary="What turning payments on or off changes"
)
async def payments_impact(
    project_id: uuid.UUID, action: str, session: AsyncSession = Depends(get_session)
) -> PaymentsImpact:
    return await PaymentsService(session).impact(project_id, action)


@router.post("/enable", response_model=PaymentsConfigRead, summary="Turn payments on")
async def enable_payments(
    project_id: uuid.UUID,
    body: PaymentsSwitchRequest,
    session: AsyncSession = Depends(get_session),
) -> PaymentsConfigRead:
    config = await PaymentsService(session).switch(project_id, "enable", confirm=body.confirm)
    return PaymentsConfigRead.model_validate(config)


@router.post("/disable", response_model=PaymentsConfigRead, summary="Turn payments off")
async def disable_payments(
    project_id: uuid.UUID,
    body: PaymentsSwitchRequest,
    session: AsyncSession = Depends(get_session),
) -> PaymentsConfigRead:
    config = await PaymentsService(session).switch(project_id, "disable", confirm=body.confirm)
    return PaymentsConfigRead.model_validate(config)
