"""The OpenCode adapter talks to `opencode serve` over HTTP and never imports it, so a mock
transport is the whole server here: the session routes it hits, the directory it scopes them
to, and how it folds a turn's messages into one metered reply."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fedotmas_llm import Usage
from fedotmas_llm.adapters.opencode import (
    OpenCodeMeter,
    OpenCodeSession,
    Reply,
    parse_reply,
)

WS = Path("/tmp/ws/hawk")


def _assistant(
    text: str = "",
    *,
    tools: tuple[str, ...] = (),
    tokens: tuple[int, int, int, int] = (0, 0, 0, 0),
    cost: float = 0.0,
    error: dict[str, Any] | None = None,
    finish: str | None = "stop",
) -> dict[str, Any]:
    inp, out, reasoning, cached = tokens
    info: dict[str, Any] = {
        "role": "assistant",
        "sessionID": "ses_1",
        "cost": cost,
        "tokens": {
            "input": inp,
            "output": out,
            "reasoning": reasoning,
            "cache": {"read": cached, "write": 0},
        },
    }
    if finish:
        info["finish"] = finish
    if error:
        info["error"] = error
    parts: list[dict[str, Any]] = [{"type": "tool", "tool": t} for t in tools]
    if text:
        parts.append({"type": "text", "text": text})
    return {"info": info, "parts": parts}


USER = {"info": {"role": "user"}, "parts": [{"type": "text", "text": "go"}]}


class FakeServer:
    """Answers the three routes a session uses and records what it was asked."""

    def __init__(self, messages: list[dict[str, Any]], *, hang: bool = False) -> None:
        self.messages = messages
        self.hang = hang
        self.requests: list[httpx.Request] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        match (request.method, request.url.path):
            case ("POST", "/session"):
                return httpx.Response(200, json={"id": "ses_1"})
            case ("POST", "/session/ses_1/message"):
                if self.hang:
                    await asyncio.sleep(10)
                return httpx.Response(200, json=self.messages[-1])
            case ("POST", "/session/ses_1/abort"):
                return httpx.Response(200, json=True)
            case ("GET", "/session/ses_1/message"):
                return httpx.Response(200, json=self.messages)
        return httpx.Response(404)


def _session(server: FakeServer) -> OpenCodeSession:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(server.handle), base_url="http://oc"
    )
    return OpenCodeSession(client, WS, ("openrouter", "qwen/qwen3.8-flash"))


async def test_every_call_is_scoped_to_the_workspace_directory():
    server = FakeServer([USER, _assistant("done")])
    session = _session(server)

    assert await session.open("round 1") == "ses_1"
    reply = await session.send("You are the hawk.", "Round 1", timeout=5)

    assert reply.text == "done"
    assert all(r.url.params["directory"] == str(WS) for r in server.requests)
    sent = json.loads(server.requests[1].content)
    assert sent["model"] == {
        "providerID": "openrouter",
        "modelID": "qwen/qwen3.8-flash",
    }
    assert sent["agent"] == "voice"
    assert sent["system"] == "You are the hawk."
    assert sent["parts"] == [{"type": "text", "text": "Round 1"}]


async def test_a_turn_is_summed_over_all_of_its_assistant_messages():
    server = FakeServer(
        [
            USER,
            _assistant(tools=("read", "bash"), tokens=(100, 10, 5, 50), cost=0.001),
            _assistant("report", tools=("write",), tokens=(200, 40, 0, 0), cost=0.002),
        ]
    )
    session = _session(server)
    await session.open("round 1")

    reply = await session.send("sys", "go", timeout=5)

    assert reply.text == "report"
    assert reply.tool_calls == {"read": 1, "bash": 1, "write": 1}
    assert (reply.input_tokens, reply.output_tokens, reply.reasoning_tokens) == (
        300,
        50,
        5,
    )
    assert reply.cache_read == 50
    assert reply.cost == pytest.approx(0.003)
    assert reply.usage == Usage(300, 55, 1)
    assert reply.session_id == "ses_1"
    assert not reply.timed_out


async def test_a_slow_turn_is_aborted_and_returns_what_landed():
    server = FakeServer([USER, _assistant("partial", tokens=(10, 1, 0, 0))], hang=True)
    session = _session(server)
    await session.open("round 1")

    reply = await session.send("sys", "go", timeout=0.05)

    assert reply.timed_out
    assert reply.text == "partial"
    assert reply.input_tokens == 10
    assert [r.url.path for r in server.requests[-2:]] == [
        "/session/ses_1/abort",
        "/session/ses_1/message",
    ]


def test_a_provider_error_is_carried_on_the_reply():
    reply = parse_reply(
        [
            USER,
            _assistant(
                error={"name": "APIError", "data": {"message": "rate limited"}},
                finish=None,
            ),
        ]
    )
    assert reply.error == "rate limited"
    assert reply.text == ""
    assert reply.finish is None


def test_the_meter_sums_replies_the_way_spendlimit_reads_them():
    meter = OpenCodeMeter()
    meter.record(
        Reply("a", input_tokens=100, output_tokens=10, cache_read=20, cost=0.1)
    )
    meter.record(Reply("b", input_tokens=50, reasoning_tokens=5, cost=0.05))

    assert meter.usage == Usage(150, 15, 2)
    assert meter.cost == pytest.approx(0.15)
    assert meter.replies == 2
