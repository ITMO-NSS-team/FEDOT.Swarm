"""OpenCode voices for the swarm: each persona is a coding agent with its own git workspace,
opened as a fresh OpenCode session every round. What it posts to the feed is a short report;
what it makes is files, committed per round, which the judge reads at the end."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fedotmas import Rule
from fedotmas.engine.contract import View
from fedotmas.ext import render
from fedotmas_llm.adapters.opencode import (
    OpenCodeMeter,
    OpenCodeServer,
    OpenCodeSession,
)
from fedotmas_meta._assemble import Agent
from fedotmas_meta.presets import PersonaFactory, post_text

WORKSPACE_CONDUCT = (
    "You work in your own git repository, the current directory. paper.md is the paper, "
    "paper_outline.md its table of contents with line numbers, and rubric.md the grading "
    "rubric; all three are read-only. The paper is long: read the sections you need by "
    "offset, never the whole file. Implement the paper's code as real files here, refining "
    "them round after round; every round has a few minutes, so write code from the first "
    "round on and read as you go. Run cheap checks only (py_compile, tiny unit tests on "
    "synthetic data): never train, never download datasets or weights, and never touch the "
    "paper's own repository. The feed shows what the other voices reported; borrow what "
    "helps, disagree where they are wrong. End every round with a report of at most 200 "
    "words as your final message: what you changed, which rubric leaves it covers, what is "
    "still missing. The report is all the others will see."
)

REFERENCE_FILES = ("paper.md", "paper_outline.md", "rubric.md", "README.md")
SKIP_DIRS = frozenset({".git", ".fedotmas", ".venv", "node_modules", "__pycache__"})
GIT = ("git", "-c", "user.name=fedotmas", "-c", "user.email=fedotmas@localhost")


def outline(markdown: str) -> str:
    """The paper's headings with their line numbers, so a voice can seek instead of read."""
    lines = ["# Contents of paper.md (line: heading)", ""]
    for number, line in enumerate(markdown.split("\n"), start=1):
        if line.startswith("#"):
            lines.append(f"{number}: {line.strip()}")
    return "\n".join(lines) + "\n"


def _git(ws: Path, *args: str) -> str:
    done = subprocess.run(
        [*GIT, *args], cwd=ws, capture_output=True, text=True, check=True
    )
    return done.stdout


@dataclass
class Workspaces:
    """One git repository per voice under `root`, seeded with the paper, the rubric, and a
    README that says what the repository is for."""

    root: Path
    paper_md: str
    rubric_md: str
    brief: str

    def path(self, voice: str) -> Path:
        return self.root / voice

    def ensure(self, voice: str) -> Path:
        ws = self.path(voice)
        if (ws / ".git").exists():
            return ws
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "paper.md").write_text(self.paper_md)
        (ws / "paper_outline.md").write_text(outline(self.paper_md))
        (ws / "rubric.md").write_text(self.rubric_md)
        (ws / "README.md").write_text(
            f"# Workspace of {voice}\n\n{self.brief}\n\n"
            "paper.md, paper_outline.md and rubric.md are read-only inputs; everything "
            "else is yours.\n"
        )
        (ws / ".gitignore").write_text(
            ".fedotmas/\n.venv/\n__pycache__/\n*.pyc\nnode_modules/\n"
        )
        _git(ws, "init", "-q")
        _git(ws, "add", "-A")
        _git(ws, "commit", "-q", "-m", "seed")
        return ws

    def changed(self, voice: str, tick: int) -> list[str]:
        """Commits the round and names every file it touched."""
        ws = self.path(voice)
        _git(ws, "add", "-A")
        staged = _git(ws, "diff", "--cached", "--name-only")
        _git(ws, "commit", "-q", "--allow-empty", "-m", f"round {tick}")
        return sorted(line.strip() for line in staged.splitlines() if line.strip())

    def files(self, voice: str) -> list[dict[str, Any]]:
        ws = self.path(voice)
        out = []
        for name in _git(ws, "ls-files").split("\n"):
            if not name or name in REFERENCE_FILES or name == ".gitignore":
                continue
            path = ws / name
            if not path.is_file():
                continue
            try:
                lines = path.read_text().count("\n") + 1
            except UnicodeDecodeError:
                lines = 0
            out.append({"path": name, "lines": lines})
        return out


def judge_code(ws: Path, max_total: int = 120_000, max_file: int = 40_000) -> str:
    """The workspace as one document for the judge: every text file it made, fenced, with
    long files cut and the cut marked."""
    sections: list[str] = []
    total = 0
    for path in sorted(p for p in ws.rglob("*") if p.is_file()):
        rel = path.relative_to(ws)
        if rel.parts[0] in SKIP_DIRS or str(rel) in REFERENCE_FILES:
            continue
        if rel.name == ".gitignore":
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if len(text) > max_file:
            text = text[:max_file] + f"\n... [cut, {len(text) - max_file} more chars]"
        if total + len(text) > max_total:
            sections.append(f"### {rel}\n[omitted, repository too long]")
            continue
        total += len(text)
        sections.append(f"### {rel}\n```\n{text}\n```")
    return "\n\n".join(sections) or "(no files)"


class LiveBoard:
    """Who is working right now, for the front end: one json file, rewritten on change."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.state: dict[str, dict[str, Any]] = {}

    def set(self, voice: str, state: str, tick: int) -> None:
        self.state[voice] = {"state": state, "round": tick, "since": time.time()}
        self.path.write_text(json.dumps(self.state))


def opencode_config(model_id: str, steps: int) -> dict[str, Any]:
    """The whole OpenCode configuration for a run, handed over as
    `OPENCODE_CONFIG_CONTENT`: nothing is ever `ask`, so a session never waits on a
    permission, and the deny list keeps a worker inside its workspace and off the network.
    Reasoning is off for the worker model: a round is minutes long and thinking tokens buy
    little on file edits."""
    provider, _, model = model_id.partition("/")
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": model_id,
        "share": "disabled",
        "autoupdate": False,
        "provider": {
            provider: {
                "options": {"apiKey": "{env:OPENROUTER_API_KEY}"},
                "models": {model: {"options": {"reasoning": {"enabled": False}}}},
            },
        },
        "permission": {
            "*": "allow",
            "webfetch": "deny",
            "websearch": "deny",
            "external_directory": "deny",
            "bash": {
                "*": "allow",
                "rm -rf /*": "deny",
                "git push*": "deny",
                "git clone*": "deny",
                "sudo*": "deny",
                "curl*": "deny",
                "wget*": "deny",
                "pip install*": "deny",
                "uv add*": "deny",
            },
        },
        "agent": {
            "voice": {
                "mode": "primary",
                "description": "one voice of a paper-reproduction swarm",
                "steps": steps,
                "tools": {
                    "task": False,
                    "todowrite": False,
                    "todoread": False,
                    "webfetch": False,
                    "websearch": False,
                },
            }
        },
    }


@dataclass
class Voice:
    """What one OpenCode voice needs beyond its persona."""

    server: OpenCodeServer
    workspaces: Workspaces
    model: tuple[str, str]
    round_seconds: float
    meter: OpenCodeMeter
    live: LiveBoard
    posts: list[dict[str, Any]] = field(default_factory=list)


def opencode_voice(voice: Voice) -> PersonaFactory:
    """Builds the persona factory `SwarmPreset` calls per voice: the same prompt, template
    and activity it would give a `PromptRule`, run as an OpenCode session instead."""

    def factory(
        agent: Agent,
        prompt: str,
        template: str,
        when: Callable[[View], bool],
        meta: dict[str, Any],
    ) -> Rule:
        async def body(tick: int, view: View) -> dict[str, Any]:
            ws = await asyncio.to_thread(voice.workspaces.ensure, agent.name)
            text = render(template, tick, view, agent.name)
            own = [f for f in view.query("post") if f.producer == agent.name]
            if own:
                text += f"\n\nYour own last report:\n{post_text(own[-1].value)}"
            session = OpenCodeSession(voice.server.client, ws, voice.model)
            await session.open(f"{agent.name} round {tick}")
            voice.live.set(agent.name, "working", tick)
            try:
                reply = await session.send(prompt, text, timeout=voice.round_seconds)
            finally:
                voice.live.set(agent.name, "idle", tick)
            voice.meter.record(reply)
            changed = await asyncio.to_thread(
                voice.workspaces.changed, agent.name, tick
            )
            files = await asyncio.to_thread(voice.workspaces.files, agent.name)
            post = {
                "voice": agent.name,
                "round": tick,
                "report": reply.text or reply.error or "(no report)",
                "files": changed,
                "fileCount": len(files),
                "tokens": {
                    "input": reply.input_tokens,
                    "output": reply.output_tokens,
                    "reasoning": reply.reasoning_tokens,
                    "cacheRead": reply.cache_read,
                    "cacheWrite": reply.cache_write,
                },
                "cost": reply.cost,
                "toolCalls": reply.tool_calls,
                "seconds": round(reply.seconds, 1),
                "timedOut": reply.timed_out,
                "sessionId": reply.session_id,
                "finish": reply.finish,
                "error": reply.error,
            }
            notes = ws / ".fedotmas"
            notes.mkdir(exist_ok=True)
            (notes / f"round-{tick}.json").write_text(json.dumps(post, indent=2))
            voice.posts.append(post)
            return post

        return Rule(
            name=agent.name,
            fn=body,
            reads="tick",
            writes="post",
            when=when,
            meta=meta,
        )

    return factory
