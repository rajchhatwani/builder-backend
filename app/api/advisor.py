"""Read-only advice on queue technology and workflow shape (pure functions, no stored state).

Sits under /projects/{id}/ so the request guard applies like any project read (viewer role, `read` scope).
The caller's declared needs ride on the query string; every field has a default and unknown ones are refused.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import queue_advisor, workflow_advisor

router = APIRouter(prefix="/projects/{project_id}", tags=["advisor"])


class AdvisorResult(BaseModel):
    queue: queue_advisor.QueueAdvice
    workflow: workflow_advisor.WorkflowAdvice


class AdvisorNeeds(queue_advisor.QueueRequirements, workflow_advisor.WorkflowNeeds):
    """Both advisors' inputs in one query model (their field names do not overlap)."""


@router.get("/advisor", response_model=AdvisorResult, summary="Queue and workflow advice")
async def get_advice(
    project_id: uuid.UUID,
    needs: Annotated[AdvisorNeeds, Query()],
) -> AdvisorResult:
    queue = queue_advisor.QueueRequirements(**needs.model_dump(include=set(queue_advisor.QueueRequirements.model_fields)))
    flow = workflow_advisor.WorkflowNeeds(**needs.model_dump(include=set(workflow_advisor.WorkflowNeeds.model_fields)))
    return AdvisorResult(queue=queue_advisor.advise(queue), workflow=workflow_advisor.advise(flow))
