"""Response models of the eval harness API (generated, pack ai.evals). Scores are integer basis points (0..10000)."""

import datetime as dt
import uuid

from pydantic import BaseModel


class LatestOut(BaseModel):
    id: uuid.UUID
    passed: bool
    score_bp: int
    created_at: dt.datetime


class SuiteOut(BaseModel):
    name: str
    agent: str
    pass_bp: int
    case_count: int
    latest: LatestOut | None


class CaseResultOut(BaseModel):
    case: str
    passed: bool
    proposed: list[str]
    error_code: str | None


class EvalRunOut(BaseModel):
    id: uuid.UUID
    suite: str
    agent: str
    score_bp: int
    passed: bool
    total: int
    passed_count: int
    results: list[CaseResultOut]
    created_by: uuid.UUID | None
    created_at: dt.datetime
