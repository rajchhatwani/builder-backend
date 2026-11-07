"""Draft-workspace file API (E2): list, read and edit custom-zone files."""

from pydantic import BaseModel, ConfigDict, Field

MAX_FILE_BYTES = 256 * 1024
MAX_LIST_ENTRIES = 2000


class WorkspaceFileEntry(BaseModel):
    path: str
    zone: str
    size: int
    editable: bool


class WorkspaceFileRead(BaseModel):
    path: str
    zone: str
    content: str
    editable: bool
    sha256: str


class WorkspaceFileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=MAX_FILE_BYTES)
    expected_sha256: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
