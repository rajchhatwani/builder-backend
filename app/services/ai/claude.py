"""Claude provider: a thin httpx client for the Messages API (no SDK dependency).

The API key is held in memory only for the life of the object. It is sent in the `x-api-key`
header and appears in no log line, exception message or repr.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.ai.base import (
    Completion,
    CompletionRequest,
    ModelProvider,
    ProviderError,
    StreamEvent,
    ToolCall,
    Usage,
    stable_tools,
)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
_CACHE = {"type": "ephemeral"}


def build_payload(model: str, request: CompletionRequest, stream: bool) -> dict[str, Any]:
    """The request body. System and tools come first and are byte-stable; the cache marker sits
    on the last tool and on the system block, so the whole prefix is cacheable."""
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": request.max_tokens,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
    }
    system_block: dict[str, Any] = {"type": "text", "text": request.system}
    if request.cache_prefix:
        system_block["cache_control"] = _CACHE
    payload["system"] = [system_block]
    tools = stable_tools(request.tools)
    if tools:
        if request.cache_prefix:
            tools[-1]["cache_control"] = _CACHE
        payload["tools"] = tools
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if stream:
        payload["stream"] = True
    return payload


def _usage(raw: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cache_read_tokens=int(raw.get("cache_read_input_tokens") or 0),
        cache_write_tokens=int(raw.get("cache_creation_input_tokens") or 0),
    )


def _parse(body: dict[str, Any]) -> Completion:
    text = ""
    calls: list[ToolCall] = []
    for block in body.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
        elif block.get("type") == "tool_use":
            calls.append(ToolCall(block["id"], block["name"], block.get("input", {})))
    return Completion(
        model=str(body.get("model", "")),
        text=text,
        tool_calls=calls,
        usage=_usage(body.get("usage", {})),
        stop_reason=str(body.get("stop_reason") or "end_turn"),
    )


def _error(status: int, body: bytes) -> ProviderError:
    message = f"provider returned HTTP {status}"
    try:
        detail = json.loads(body).get("error", {}).get("message")
        if isinstance(detail, str):
            message += f": {detail[:200]}"
    except (ValueError, AttributeError):
        pass
    return ProviderError(message, status)


class ClaudeProvider(ModelProvider):
    name = "claude"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
        url: str = API_URL,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport
        self._url = url

    def __repr__(self) -> str:
        return "ClaudeProvider(api_key=<hidden>)"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    async def complete(self, model: str, request: CompletionRequest) -> Completion:
        payload = build_payload(model, request, stream=False)
        try:
            async with self._client() as client:
                response = await client.post(self._url, headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider unreachable ({type(exc).__name__})") from None
        if response.status_code >= 400:
            raise _error(response.status_code, response.content)
        return _parse(response.json())

    async def stream(self, model: str, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        payload = build_payload(model, request, stream=True)
        text = ""
        calls: list[ToolCall] = []
        partial: dict[int, dict[str, Any]] = {}
        usage_in: dict[str, Any] = {}
        usage_out: dict[str, Any] = {}
        stop = "end_turn"
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", self._url, headers=self._headers(), json=payload
                ) as response:
                    if response.status_code >= 400:
                        raise _error(response.status_code, await response.aread())
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        event = json.loads(line[5:].strip())
                        kind = event.get("type")
                        if kind == "message_start":
                            usage_in = event["message"].get("usage", {})
                        elif kind == "content_block_start":
                            block = event["content_block"]
                            if block.get("type") == "tool_use":
                                partial[event["index"]] = {
                                    "id": block["id"],
                                    "name": block["name"],
                                    "json": "",
                                }
                        elif kind == "content_block_delta":
                            delta = event["delta"]
                            if delta.get("type") == "text_delta":
                                text += delta["text"]
                                yield StreamEvent(kind="text", text=delta["text"])
                            elif delta.get("type") == "input_json_delta":
                                partial[event["index"]]["json"] += delta.get("partial_json", "")
                        elif kind == "content_block_stop" and event["index"] in partial:
                            p = partial.pop(event["index"])
                            call = ToolCall(p["id"], p["name"], json.loads(p["json"] or "{}"))
                            calls.append(call)
                            yield StreamEvent(kind="tool_call", tool_call=call)
                        elif kind == "message_delta":
                            usage_out = event.get("usage", {})
                            stop = event.get("delta", {}).get("stop_reason") or stop
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider unreachable ({type(exc).__name__})") from None
        merged = {**usage_in, **usage_out}
        done = Completion(model, text, calls, _usage(merged), stop)
        yield StreamEvent(kind="done", completion=done)
