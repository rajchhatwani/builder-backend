"""Deterministic provider for tests: no network, same input gives same output and usage."""

import hashlib
import json
from collections.abc import AsyncIterator

from app.services.ai.base import (
    Completion,
    CompletionRequest,
    ModelProvider,
    StreamEvent,
    ToolCall,
    Usage,
    prefix_digest,
)


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeProvider(ModelProvider):
    name = "fake"

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, CompletionRequest]] = []
        self.fail_with = fail_with
        self._seen_prefixes: set[str] = set()

    async def complete(self, model: str, request: CompletionRequest) -> Completion:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((model, request))
        body = json.dumps([[m.role, m.content] for m in request.messages], sort_keys=True)
        digest = hashlib.sha256(f"{model}|{request.system}|{body}".encode()).hexdigest()[:12]
        text = f"fake:{digest}"
        tool_calls: list[ToolCall] = []
        if request.tools:
            tool = sorted(request.tools, key=lambda t: t.name)[0]
            tool_calls = [ToolCall(id=f"toolu_{digest}", name=tool.name, input={})]
        prefix = prefix_digest(request.system, request.tools)
        prefix_tokens = _tokens(request.system) + sum(
            _tokens(json.dumps(t.input_schema)) for t in request.tools
        )
        cache_read = cache_write = 0
        rest = _tokens(body)
        if request.cache_prefix:
            if prefix in self._seen_prefixes:
                cache_read = prefix_tokens
            else:
                cache_write = prefix_tokens
                self._seen_prefixes.add(prefix)
        else:
            rest += prefix_tokens
        usage = Usage(
            input_tokens=rest,
            output_tokens=_tokens(text),
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
        return Completion(
            model=model,
            text=text,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    async def stream(self, model: str, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        result = await self.complete(model, request)
        mid = len(result.text) // 2
        yield StreamEvent(kind="text", text=result.text[:mid])
        yield StreamEvent(kind="text", text=result.text[mid:])
        for call in result.tool_calls:
            yield StreamEvent(kind="tool_call", tool_call=call)
        yield StreamEvent(kind="done", completion=result)
