"""An OpenCode voice is a git workspace plus a session per round: what the workspace is
seeded with, what a round commits, what the judge is shown, and what lands on the feed."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, cast

import httpx
from fedotmas import Board
from fedotmas_llm.adapters.opencode import OpenCodeMeter
from fedotmas_meta import AgentSpec, Catalog, SystemSpec, assemble
from fedotmas_meta.presets import SwarmPreset
from workers import (
    WORKSPACE_CONDUCT,
    LiveBoard,
    Voice,
    Workspaces,
    judge_code,
    opencode_config,
)
from workers import opencode_voice as make_factory


def _workspaces(tmp_path: Path) -> Workspaces:
    return Workspaces(tmp_path / "ws", "# Paper\n\nbody", "# Rubric\n", "brief")


def test_a_workspace_is_seeded_once_and_committed(tmp_path: Path):
    spaces = _workspaces(tmp_path)
    ws = spaces.ensure("hawk")
    (ws / "model.py").write_text("x = 1\n")
    assert spaces.ensure("hawk") == ws
    assert (ws / "model.py").exists()
    assert (ws / "paper.md").read_text() == "# Paper\n\nbody"
    assert "Workspace of hawk" in (ws / "README.md").read_text()

    changed = spaces.changed("hawk", 0)
    assert changed == ["model.py"]
    assert spaces.changed("hawk", 1) == []
    assert spaces.files("hawk") == [{"path": "model.py", "lines": 2}]


def test_judge_code_shows_only_what_the_voice_made(tmp_path: Path):
    spaces = _workspaces(tmp_path)
    ws = spaces.ensure("hawk")
    (ws / "src").mkdir()
    (ws / "src" / "a.py").write_text("print(1)\n")
    (ws / ".fedotmas").mkdir()
    (ws / ".fedotmas" / "round-0.json").write_text("{}")
    (ws / "big.txt").write_text("x" * 100)

    doc = judge_code(ws, max_total=1000, max_file=40)
    assert "### src/a.py" in doc
    assert "paper.md" not in doc and "round-0" not in doc
    assert "[cut, 60 more chars]" in doc


def test_the_config_never_asks_and_denies_the_network():
    cfg = opencode_config("openrouter/qwen/qwen3.8-flash", 12)
    assert cfg["model"] == "openrouter/qwen/qwen3.8-flash"
    assert cfg["share"] == "disabled" and cfg["autoupdate"] is False
    assert cfg["permission"]["webfetch"] == "deny"
    assert cfg["permission"]["bash"]["curl*"] == "deny"
    assert cfg["agent"]["voice"]["steps"] == 12
    assert '"ask"' not in json.dumps(cfg)


class FakeOpenCode:
    """The message route of `opencode serve`, editing a file in the session's directory the
    way a real turn would, so the round's commit has something to record."""

    def __init__(self) -> None:
        self.prompts: list[dict[str, Any]] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        directory = Path(request.url.params["directory"])
        match (request.method, request.url.path):
            case ("POST", "/session"):
                return httpx.Response(200, json={"id": f"ses_{directory.name}"})
            case ("POST", path) if path.endswith("/message"):
                body = json.loads(request.content)
                self.prompts.append(body)
                (directory / "train.py").write_text("def step(): ...\n")
                return httpx.Response(200, json={})
            case ("GET", path) if path.endswith("/message"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "info": {
                                "role": "assistant",
                                "sessionID": f"ses_{directory.name}",
                                "cost": 0.002,
                                "tokens": {
                                    "input": 100,
                                    "output": 20,
                                    "reasoning": 0,
                                    "cache": {"read": 0, "write": 0},
                                },
                                "finish": "stop",
                            },
                            "parts": [
                                {"type": "tool", "tool": "write"},
                                {
                                    "type": "text",
                                    "text": f"{directory.name} wrote train.py",
                                },
                            ],
                        }
                    ],
                )
        return httpx.Response(404)


class _Server:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client


async def test_a_voice_round_commits_and_posts_a_structured_report(tmp_path: Path):
    fake = FakeOpenCode()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(fake.handle), base_url="http://oc"
    )
    spaces = _workspaces(tmp_path)
    voice = Voice(
        server=cast(Any, _Server(client)),
        workspaces=spaces,
        model=("openrouter", "qwen/qwen3.8-flash"),
        round_seconds=5,
        meter=OpenCodeMeter(),
        live=LiveBoard(tmp_path / "live.json"),
    )
    preset = SwarmPreset(
        min_active=0,
        max_active=None,
        activity=(1.0, 1.0),
        rng=random.Random(1),
        conduct=WORKSPACE_CONDUCT,
        persona_factory=make_factory(voice),
    )
    spec = SystemSpec(
        preset="swarm",
        fill={"personas": {"hawk": AgentSpec(prompt="You are the hawk.")}},
    )
    board = assemble(spec, Catalog(preset))
    assert isinstance(board, Board)

    run = await board.run(preset.seed("brief"), goal="__never__", budget=2)

    assert not run.errors
    posts = [f.value for f in run.view.query("post")]
    assert len(posts) == 2
    first = posts[0]
    assert first["voice"] == "hawk" and first["round"] == 0
    assert first["report"] == "hawk wrote train.py"
    assert first["files"] == ["train.py"]
    assert first["toolCalls"] == {"write": 1}
    assert first["cost"] == 0.002 and first["sessionId"] == "ses_hawk"
    assert posts[1]["files"] == []
    assert fake.prompts[0]["system"] == f"You are the hawk.\n{WORKSPACE_CONDUCT}"
    assert (
        "Your own last report:\nhawk wrote train.py"
        in fake.prompts[1]["parts"][0]["text"]
    )
    assert voice.meter.replies == 2 and voice.meter.cost == 0.004
    assert (spaces.path("hawk") / ".fedotmas" / "round-1.json").exists()
    assert json.loads((tmp_path / "live.json").read_text())["hawk"]["state"] == "idle"
