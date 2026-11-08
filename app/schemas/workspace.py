"""Schemas for draft workspaces (B3-4). The preview DB URL is never returned."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(default="draft", min_length=1, max_length=100)


class CheckpointCreate(BaseModel):
    label: str = Field(default="checkpoint", min_length=1, max_length=100)


class RollbackRequest(BaseModel):
    checkpoint_id: uuid.UUID


class CheckpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    label: str
    git_sha: str
    spec_seq: int
    spec_hash: str
    has_data_snapshot: bool
    created_at: datetime


class WorkspaceRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    state: str
    base_spec_seq: int
    spec_seq: int
    branch: str
    created_at: datetime
    updated_at: datetime
    checkpoints: list[CheckpointRead] = []
    # True when a discard could not remove everything; repeat DELETE to retry.
    cleanup_incomplete: bool = False
