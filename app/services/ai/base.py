"""Provider-neutral types and the `ModelProvider` interface."""

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskClass(StrEnum):
    route = "route"
    classify = "classify"
    summarize = "summarize"
    plan = "plan"
    code = "code"
    repair = "repair"
    verify = "verify"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant"
    content: str | list[dict[str, Any]]


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    messages: list[Message]
    tools: list[ToolDefinition] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float | None = None
    # Mark the system prompt + tool definitions as a cacheable prefix.
    cache_prefix: bool = True


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class Completion:
    model: str
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str = "end_turn"


@dataclass(frozen=True)
class StreamEvent:
    kind: str  # "text" | "tool_call" | "done"
    text: str = ""
    tool_call: ToolCall | None = None
    completion: Completion | None = None  # set on "done"


class ProviderError(Exception):
    """A provider failure. The message never contains the API key or request headers."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def stable_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Tool definitions in a fixed order with fixed key order: the same bytes every call, so the
    provider's prompt cache keeps hitting. Sorted by name, schemas key-sorted."""
    out = []
    for t in sorted(tools, key=lambda x: x.name):
        schema = json.loads(json.dumps(t.input_schema, sort_keys=True))
        out.append({"name": t.name, "description": t.description, "input_schema": schema})
    return out


def prefix_digest(system: str, tools: list[ToolDefinition]) -> str:
    """Hash of the cacheable prefix (system + tools); equal digests = byte-stable prefix."""
    blob = json.dumps(
        {"system": system, "tools": stable_tools(tools)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class ModelProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, model: str, request: CompletionRequest) -> Completion: ...

    @abstractmethod
    def stream(self, model: str, request: CompletionRequest) -> AsyncIterator[StreamEvent]: ...
