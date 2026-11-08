"""Routes for a project's authorization model and policies, the simulator and coverage."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.authorization import (
    AuthorizationIssues,
    AuthorizationRead,
    AuthorizationWrite,
    CoverageResponse,
    RecommendRequest,
    RecommendResponse,
    SimulateRequest,
    SimulateResponse,
)
from app.services.authorization_service import AuthorizationService, recommend

router = APIRouter(tags=["authorization"])


@router.get(
    "/projects/{project_id}/authorization",
    response_model=AuthorizationRead,
    summary="Get the authorization model and policies (rbac with no policies when never saved)",
)
async def get_authorization(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AuthorizationRead:
    return await AuthorizationService(session).get(project_id)


@router.put(
    "/projects/{project_id}/authorization",
    response_model=AuthorizationRead,
    summary="Replace the authorization model and policies",
)
async def put_authorization(
    project_id: uuid.UUID,
    body: AuthorizationWrite,
    session: AsyncSession = Depends(get_session),
) -> AuthorizationRead:
    return await AuthorizationService(session).put(project_id, body)


@router.get(
    "/projects/{project_id}/authorization/issues",
    response_model=AuthorizationIssues,
    summary="Problems with the policies (no side effects)",
)
async def authorization_issues(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AuthorizationIssues:
    return AuthorizationIssues(issues=await AuthorizationService(session).issues(project_id))


@router.post(
    "/projects/{project_id}/authorization/simulate",
    response_model=SimulateResponse,
    summary="Decide one request against the saved policies and show why",
)
async def simulate_authorization(
    project_id: uuid.UUID,
    body: SimulateRequest,
    session: AsyncSession = Depends(get_session),
) -> SimulateResponse:
    return await AuthorizationService(session).simulate(project_id, body)


@router.get(
    "/projects/{project_id}/authorization/coverage",
    response_model=CoverageResponse,
    summary="Which policies can allow or deny each operation of each entity",
)
async def authorization_coverage(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> CoverageResponse:
    return await AuthorizationService(session).coverage(project_id)


@router.get(
    "/projects/{project_id}/authorization/recommendation",
    response_model=RecommendResponse,
    summary="Recommend a model from what the project already says",
)
async def recommend_for_project(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> RecommendResponse:
    return await AuthorizationService(session).recommend_for_project(project_id)


@router.post(
    "/projects/{project_id}/authorization/recommend",
    response_model=RecommendResponse,
    summary="Recommend an authorization model from questionnaire answers",
)
async def recommend_model(project_id: uuid.UUID, body: RecommendRequest) -> RecommendResponse:
    return recommend(body)
