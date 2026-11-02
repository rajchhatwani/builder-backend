"""B3-7 unit tests: routing, cost maths, fake provider, Claude request shape, key hygiene."""

import json
import logging

import httpx
import pytest

from app.config import Settings
from app.services.ai.base import (
    CompletionRequest,
    Message,
    ProviderError,
    TaskClass,
    ToolDefinition,
    Usage,
    prefix_digest,
)
from app.services.ai.claude import ClaudeProvider, build_payload
from app.services.ai.fake import FakeProvider
from app.services.ai.ledger import budget_exceeded
from app.services.ai.pricing import UnknownModelPrice, cost_micro_usd, price_table
from app.services.ai.routing import route_model

FAKE_KEY = "sk_" "ant_test_0123456789abcdef"


def _req(tools: list[ToolDefinition] | None = None) -> CompletionRequest:
    return CompletionRequest(
        system="You are the builder.", messages=[Message("user", "hi")], tools=tools or []
    )


def _tool(name: str, **props: object) -> ToolDefinition:
    return ToolDefinition(name, "d", {"type": "object", "properties": props})


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        (TaskClass.route, "claude-haiku-5-5"),
        (TaskClass.classify, "claude-haiku-5-5"),
        (TaskClass.summarize, "claude-haiku-5-5"),
        (TaskClass.plan, "claude-sonnet-5-5"),
        (TaskClass.code, "claude-sonnet-5-5"),
        (TaskClass.repair, "claude-sonnet-5-5"),
        (TaskClass.verify, "claude-sonnet-5-5"),
    ],
)
def test_routing_defaults(task: TaskClass, expected: str) -> None:
    assert route_model(task, Settings()) == expected


def test_routing_is_configurable() -> None:
    s = Settings(ai_small_model="s-1", ai_large_model="l-1")
    assert route_model(TaskClass.route, s) == "s-1"
    assert route_model(TaskClass.code, s) == "l-1"


def test_cost_maths_exact_and_rounded_up() -> None:
    table = price_table()
    # sonnet: 3 USD in, 15 USD out per Mtok -> 3 and 15 micro-USD per token
    assert cost_micro_usd("claude-sonnet-5-5", Usage(1000, 100, 0, 0), table) == 3000 + 1500
    # cache read 0.30 USD/Mtok = 0.3 micro per token: 1 token rounds up to 1
    assert cost_micro_usd("claude-sonnet-5-5", Usage(0, 0, 1, 0), table) == 1
    assert cost_micro_usd("claude-sonnet-5-5", Usage(0, 0, 0, 0), table) == 0
    assert cost_micro_usd("claude-haiku-5-5", Usage(1_000_000, 0, 0, 1_000_000), table) == (
        1_000_000 + 1_250_000
    )


def test_price_table_override_and_unknown_model() -> None:
    table = price_table({"claude-sonnet-5-5": {"input": 1_000_000}, "x": {"input": 2_000_000}})
    assert cost_micro_usd("claude-sonnet-5-5", Usage(10, 10, 0, 0), table) == 10 + 150
    assert cost_micro_usd("x", Usage(5, 0, 0, 0), table) == 10
    with pytest.raises(UnknownModelPrice):
        cost_micro_usd("nope", Usage(1, 1, 0, 0), table)


def test_budget_cap() -> None:
    assert not budget_exceeded(10**12, None)
    assert not budget_exceeded(99, 100)
    assert budget_exceeded(100, 100)
    assert budget_exceeded(0, 0)


async def test_fake_provider_is_deterministic_and_caches_the_prefix() -> None:
    a, b = FakeProvider(), FakeProvider()
    tools = [_tool("b"), _tool("a")]
    r1 = await a.complete("claude-haiku-5-5", _req(tools))
    r2 = await b.complete("claude-haiku-5-5", _req(tools))
    assert r1 == r2
    assert r1.tool_calls[0].name == "a"
    assert r1.usage.cache_write_tokens > 0 and r1.usage.cache_read_tokens == 0
    again = await a.complete("claude-haiku-5-5", _req(tools))
    assert again.usage.cache_read_tokens == r1.usage.cache_write_tokens
    assert again.usage.cache_write_tokens == 0


async def test_fake_stream_ends_with_done() -> None:
    events = [e async for e in FakeProvider().stream("m", _req())]
    assert events[-1].kind == "done" and events[-1].completion is not None
    assert "".join(e.text for e in events if e.kind == "text") == events[-1].completion.text


def test_prefix_is_byte_stable_across_tool_and_key_order() -> None:
    t1 = [_tool("a", x={"type": "string"}, y={"type": "integer"}), _tool("b")]
    t2 = [_tool("b"), _tool("a", y={"type": "integer"}, x={"type": "string"})]
    assert prefix_digest("s", t1) == prefix_digest("s", t2)
    p1 = build_payload("m", _req(t1), stream=False)
    p2 = build_payload("m", _req(t2), stream=False)
    dump = lambda p: json.dumps({k: p[k] for k in ("system", "tools")})  # noqa: E731
    assert dump(p1) == dump(p2)


def test_cache_markers_on_system_and_last_tool_only() -> None:
    p = build_payload("m", _req([_tool("a"), _tool("b")]), stream=False)
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in p["tools"][0]
    assert p["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    off = CompletionRequest("s", [Message("user", "x")], [_tool("a")], cache_prefix=False)
    q = build_payload("m", off, stream=False)
    assert "cache_control" not in json.dumps(q)


async def test_claude_complete_via_mock_transport_sends_key_header_only() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["x-api-key"]
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "model": "claude-haiku-5-5",
                "content": [
                    {"type": "text", "text": "ok"},
                    {"type": "tool_use", "id": "t1", "name": "a", "input": {"q": 1}},
                ],
                "stop_reason": "tool_use",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 7,
                    "cache_creation_input_tokens": 3,
                },
            },
        )

    p = ClaudeProvider(FAKE_KEY, transport=httpx.MockTransport(handler))
    out = await p.complete("claude-haiku-5-5", _req([_tool("a")]))
    assert seen["key"] == FAKE_KEY
    assert FAKE_KEY not in str(seen["body"])
    assert out.text == "ok" and out.tool_calls[0].input == {"q": 1}
    assert out.usage == Usage(10, 5, 7, 3)
    assert FAKE_KEY not in repr(p)


async def test_claude_stream_parses_sse() -> None:
    lines = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 4}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "he"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "y"}},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "t", "name": "a"},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"k":'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": "2}"},
        },
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 9}},
    ]
    sse = "".join(f"event: x\ndata: {json.dumps(x)}\n\n" for x in lines)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=sse))
    p = ClaudeProvider(FAKE_KEY, transport=transport)
    events = [e async for e in p.stream("m", _req())]
    done = events[-1].completion
    assert done is not None
    assert done.text == "hey" and done.tool_calls[0].input == {"k": 2}
    assert done.usage == Usage(4, 9, 0, 0) and done.stop_reason == "tool_use"


async def test_provider_error_never_leaks_the_key(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    p = ClaudeProvider(FAKE_KEY, transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as exc:
        await p.complete("m", _req())
    assert exc.value.status_code == 401
    assert FAKE_KEY not in str(exc.value)
    assert FAKE_KEY not in caplog.text

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {FAKE_KEY}")

    q = ClaudeProvider(FAKE_KEY, transport=httpx.MockTransport(boom))
    with pytest.raises(ProviderError) as exc2:
        await q.complete("m", _req())
    assert FAKE_KEY not in str(exc2.value) and exc2.value.__cause__ is None
