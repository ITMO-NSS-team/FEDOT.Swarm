"""OpenCode as a worker backend: a coding agent with a shell and a file system, driven over
the HTTP API of one `opencode serve` process. A run starts one server, opens a session per
call in the worker's own directory (`?directory=`), and reads tokens and cost back off the
assistant message, so a `SpendLimit` can meter these workers next to the prompt ones.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

import httpx

from fedotmas_llm._llm import Usage


@dataclass(frozen=True)
class Reply:
    """What one session turn produced: the final assistant text plus the meters OpenCode
    reports for it. `timed_out` marks a turn that was aborted before it finished."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0
    tool_calls: dict[str, int] = field(default_factory=dict)
    finish: str | None = None
    error: str | None = None
    seconds: float = 0.0
    timed_out: bool = False
    session_id: str = ""

    @property
    def usage(self) -> Usage:
        """Reasoning is billed as output. Cache reads are left out: providers bill them at a
        fraction of the input price, so counting them as input would overstate the spend a
        cap is checked against; `cost` carries what OpenCode says the turn really cost."""
        return Usage(self.input_tokens, self.output_tokens + self.reasoning_tokens, 1)


def parse_reply(
    messages: list[Mapping[str, Any]],
    *,
    session_id: str = "",
    seconds: float = 0.0,
    timed_out: bool = False,
) -> Reply:
    """Folds a session's messages into one `Reply`. OpenCode opens a new assistant message
    per step of its tool loop and meters each on its own, so tokens, cost and tool calls are
    summed over every assistant message and the text is the last one's."""
    calls: dict[str, int] = {}
    tokens = {"input": 0, "output": 0, "reasoning": 0, "read": 0, "write": 0}
    cost = 0.0
    text, finish, error = "", None, None
    for message in messages:
        info = message.get("info") or {}
        if info.get("role") != "assistant":
            continue
        counted = info.get("tokens") or {}
        cache = counted.get("cache") or {}
        for key in ("input", "output", "reasoning"):
            tokens[key] += int(counted.get(key) or 0)
        tokens["read"] += int(cache.get("read") or 0)
        tokens["write"] += int(cache.get("write") or 0)
        cost += float(info.get("cost") or 0.0)
        texts: list[str] = []
        for part in message.get("parts") or []:
            match part.get("type"):
                case "tool":
                    name = str(part.get("tool", "?"))
                    calls[name] = calls.get(name, 0) + 1
                case "text":
                    texts.append(str(part.get("text", "")))
        if any(t.strip() for t in texts):
            text = "\n".join(t for t in texts if t).strip()
        finish = info.get("finish") or finish
        session_id = str(info.get("sessionID") or session_id)
        failure = info.get("error")
        if isinstance(failure, dict):
            data = failure.get("data") or {}
            error = str(data.get("message") or failure.get("name") or failure)
    return Reply(
        text=text,
        input_tokens=tokens["input"],
        output_tokens=tokens["output"],
        reasoning_tokens=tokens["reasoning"],
        cache_read=tokens["read"],
        cache_write=tokens["write"],
        cost=cost,
        tool_calls=calls,
        finish=finish,
        error=error,
        seconds=seconds,
        timed_out=timed_out,
        session_id=session_id,
    )


class OpenCodeMeter:
    """Sums what the sessions of one run spent, in the shape `SpendLimit` reads."""

    def __init__(self) -> None:
        self._usage = Usage()
        self.cost = 0.0
        self.replies = 0

    @property
    def usage(self) -> Usage:
        return self._usage

    def record(self, reply: Reply) -> None:
        self._usage += reply.usage
        self.cost += reply.cost
        self.replies += 1


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class OpenCodeServer:
    """One `opencode serve` process on a free localhost port, started in its own process
    group so `stop()` also reaps whatever its bash tool spawned. Config comes in through the
    environment (`OPENCODE_CONFIG_CONTENT`), never through a file the workers could edit."""

    def __init__(
        self,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        binary: str = "opencode",
        ready_timeout: float = 30.0,
    ) -> None:
        self.cwd = cwd
        self.env = dict(env or {})
        self.binary = binary
        self.ready_timeout = ready_timeout
        self.port = 0
        self._proc: subprocess.Popen[bytes] | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("OpenCode server is not started")
        return self._client

    async def start(self) -> None:
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        log = (self.cwd / "opencode.log").open("ab")
        self._proc = subprocess.Popen(  # noqa: ASYNC220
            [
                self.binary,
                "serve",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=self.cwd,
            env={**os.environ, **self.env},
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        log.close()
        self._client = httpx.AsyncClient(base_url=self.url, timeout=None)
        deadline = time.monotonic() + self.ready_timeout
        while True:
            if self._proc.poll() is not None:
                raise RuntimeError(
                    f"opencode serve exited with {self._proc.returncode}, "
                    f"see {self.cwd / 'opencode.log'}"
                )
            try:
                r = await self._client.get("/session", timeout=2.0)
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                await self.stop()
                raise TimeoutError(f"opencode serve did not answer on {self.url}")
            await asyncio.sleep(0.25)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        _signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.to_thread(proc.wait, 5.0)
        except subprocess.TimeoutExpired:
            _signal_group(proc, signal.SIGKILL)
            await asyncio.to_thread(proc.wait, 5.0)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()


def _signal_group(proc: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except ProcessLookupError:
        pass


class OpenCodeSession:
    """One OpenCode session rooted in `directory`. `send` runs a whole agent turn (tools
    included) and waits for the final message; past `timeout` it aborts the turn and returns
    what had landed by then, so a slow worker costs a round, not the run."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        directory: Path,
        model: tuple[str, str],
        agent: str = "voice",
    ) -> None:
        self.client = client
        self.directory = directory
        self.provider, self.model = model
        self.agent = agent
        self.id = ""

    @property
    def _query(self) -> dict[str, str]:
        return {"directory": str(self.directory)}

    async def open(self, title: str) -> str:
        r = await self.client.post(
            "/session", params=self._query, json={"title": title}, timeout=30.0
        )
        r.raise_for_status()
        self.id = str(r.json()["id"])
        return self.id

    async def send(self, system: str, text: str, timeout: float) -> Reply:
        if not self.id:
            raise RuntimeError("open() the session before send()")
        body = {
            "model": {"providerID": self.provider, "modelID": self.model},
            "agent": self.agent,
            "system": system,
            "parts": [{"type": "text", "text": text}],
        }
        started = time.monotonic()
        timed_out = False
        try:
            r = await asyncio.wait_for(
                self.client.post(
                    f"/session/{self.id}/message", params=self._query, json=body
                ),
                timeout,
            )
            r.raise_for_status()
        except TimeoutError:
            timed_out = True
            await self.abort()
        messages = await self.messages()
        return parse_reply(
            messages,
            session_id=self.id,
            seconds=time.monotonic() - started,
            timed_out=timed_out,
        )

    async def messages(self) -> list[Mapping[str, Any]]:
        r = await self.client.get(
            f"/session/{self.id}/message", params=self._query, timeout=30.0
        )
        r.raise_for_status()
        return list(r.json())

    async def abort(self) -> None:
        try:
            await self.client.post(
                f"/session/{self.id}/abort", params=self._query, timeout=10.0
            )
        except httpx.HTTPError:
            pass
