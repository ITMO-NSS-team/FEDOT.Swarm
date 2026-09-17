"""A Code-Dev slice of PaperBench, run through the same swarm the topic-debate benchmark
uses (`packages/fedotmas-meta/src/fedotmas_meta/presets/_swarm.py`'s `SwarmPreset`) rather
than a bespoke pipeline: a cast of personas posts to one shared feed over several rounds,
`ActivitySample` decides who speaks each round, an optional queen recasts mid-run, and an
optional meta-agent (`compose()`) writes the cast instead of a handwritten one — all of it
unmodified from the swarm benchmark. The only thing that differs from
`benchmarks/swarm/run.py` is what the room is for: the "topic" a persona reads is a fixed
paper's rubric branch instead of free text, its conduct is "write code", not "post a
one-line argument", and after the run each persona's last post is scored against the
branch's requirements by a judge, which keeps the best.

Every LLM call — personas, queen, compose, judge — goes through one of two backends,
picked by `--backend`. The default, `ClaudeCodeLLM` below, is an adapter for fedotmas_llm's
one-method `LLM` protocol (`packages/fedotmas-llm/src/fedotmas_llm/_llm.py`) backed by the
harness's `claude-code` provider: it drives your own logged-in Claude Code CLI rather than
a metered API key, so the whole swarm runs on your existing subscription. `claude-code`
does not forward custom tools to the CLI session (see `_tools` in its Rust source), so a
structured `Call.returns` (used by `compose()` and the preset's own queen) is asked for as
JSON in the prompt and validated with a `TypeAdapter` rather than through tool-backed
structured output. `--backend openrouter` swaps in `fedotmas_llm.adapters.pydantic_ai.
PydanticAI` instead — the same metered backend `benchmarks/swarm/run.py` runs on — and
with it, `--usd`/`--tokens`/`--requests` cap the run's spend the way they do there; those
caps do nothing under `claude-code`, which has no per-token cost to cap.

Usage:
.venv/bin/python benchmarks/paperbench/run.py --paper stochastic-interpolants
.venv/bin/python benchmarks/paperbench/run.py --paper stochastic-interpolants --personas 3 --rounds 4 --compose

The swarm reads `data/<paper>/paper.md` when present (produced from the paper's LaTeX
source by `parse_tex.py`), falling back to the hand-written `paper_summary.md`.
.venv/bin/python benchmarks/paperbench/parse_tex.py --paper stochastic-interpolants --source <file-or-dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fedotmas.atoms import action
from fedotmas.engine import PluginDispatcher, SqliteStore
from fedotmas.engine.contract import View
from fedotmas.engine.plugin import Plugin
from fedotmas.engine.report import StepReport
from fedotmas.ext.plugins import ConcurrencyLimit, Retry
from fedotmas_llm import Call, Price, SpendLimit, Usage
from fedotmas_llm.adapters.pydantic_ai import PydanticAI
from fedotmas_meta import AgentSpec, Catalog, SystemSpec, assemble, compose
from fedotmas_meta.presets import SwarmPreset, by_interest
from markov_sdk import Agent, Provider
from pydantic import BaseModel, TypeAdapter
from pydantic_ai.exceptions import ModelHTTPError

from parse_tex import convert as convert_tex

DATA = Path(__file__).parent / "data"
FEED_WIDTH = 12

# Every structured call here — compose(), the preset's own queen, and the openrouter judge
# — asks pydantic-ai for a typed `output_type`, which it gets via a forced `tool_choice`.
# Some OpenRouter models (qwen3.8-flash over Alibaba, seen in practice) reject that combo
# outright once their own "thinking mode" is on: "tool_choice ... does not support being
# set to required or object in thinking mode" (HTTP 400). Reasoning off avoids it; unlike
# free-topic's swarm, where only compose()/queen calls are structured and everything else
# is a plain string post, paperbench's judge is *always* structured, so this is not an
# opt-in flag here the way free-topic's `--no-reasoning` is — it is the only setting that
# reliably works across the models this backend is likely to see.
OPENROUTER_SETTINGS = {"extra_body": {"reasoning": {"enabled": False}}}

# Real OpenRouter catalog prices (USD per 1M tokens) for the two models `web/lib/types.ts`'s
# `models` list currently offers, so `--usd`/`--tokens` are checked against what the run
# actually costs rather than one guessed number for every model. Update this table (and
# `--price-in`/`--price-out` below) whenever that list changes. `--price-in`/`--price-out`
# still override a table entry, or fill in for a model not in it.
OPENROUTER_PRICES: dict[str, Price] = {
    "openrouter:qwen/qwen3.7-flash": Price(0.03, 0.13),
    "openrouter:qwen/qwen3.8-flash": Price(0.15, 0.47),
}

CODE_CONDUCT = (
    "You are writing one shared Python implementation with the others in this room, over "
    "several rounds. Read the feed (the code posted so far, including your own last post) "
    "and post your next revision: the full current state of the file you are responsible "
    "for, not a diff and not commentary. No prose outside code, no markdown fences unless "
    "the whole post is one fenced block."
)


def leaves_of(node: dict[str, Any]) -> list[dict[str, Any]]:
    if not node.get("sub_tasks"):
        return [node]
    out: list[dict[str, Any]] = []
    for sub in node["sub_tasks"]:
        out.extend(leaves_of(sub))
    return out


def load_branch(data: Any) -> tuple[str, list[dict[str, Any]]]:
    """Branch requirements plus leaves, or an error naming what is wrong with them."""
    if not isinstance(data, dict):
        raise TypeError("rubric branch must be a JSON object")
    requirements = data.get("requirements")
    if not isinstance(requirements, str) or not requirements.strip():
        raise ValueError("rubric branch needs a non-empty 'requirements' string")
    leaves = leaves_of(data)
    if not leaves:
        raise ValueError("rubric branch has no leaves to grade")
    for leaf in leaves:
        if not isinstance(leaf.get("id"), str) or not leaf["id"].strip():
            raise ValueError("every rubric leaf needs a non-empty string 'id'")
        if (
            not isinstance(leaf.get("requirements"), str)
            or not leaf["requirements"].strip()
        ):
            raise ValueError(
                f"rubric leaf {leaf.get('id')!r} needs non-empty 'requirements'"
            )
        weight = leaf.get("weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or weight < 0
        ):
            raise ValueError(
                f"rubric leaf {leaf['id']!r} needs a non-negative 'weight'"
            )
    return requirements, leaves


def parse_tex_text(source: Path, workdir: Path) -> tuple[str, str]:
    """Clean an uploaded .tex file or directory of them once, beside the run's own
    workdir."""
    out_md = workdir / "paper.md"
    convert_tex(source, out_md)
    return out_md.read_text(), source.name


def load_paper_text(paper_dir: Path) -> tuple[str, str]:
    """Full parsed paper when `parse_tex.py` has run, else the hand-written summary."""
    full = paper_dir / "paper.md"
    if full.exists():
        return full.read_text(), "paper.md"
    return (paper_dir / "paper_summary.md").read_text(), "paper_summary.md"


def paper_topic(
    summary: str, blacklist: list[str], leaves: list[dict[str, Any]]
) -> str:
    checks = "\n".join(f"- {leaf['requirements']}" for leaf in leaves)
    off_limits = ", ".join(blacklist) if blacklist else "the paper's own repository"
    return (
        f"{summary}\n\n"
        f"Write, in Python, the training step described above, refining it across as many "
        f"rounds as it takes. Do not run training, do not download any dataset or "
        f"pretrained weights, and do not access {off_limits}: work only from the "
        f"description above.\n\n"
        f"Your final post must satisfy every requirement below:\n{checks}"
    )


def handwritten_cast(n: int) -> SystemSpec:
    """The hand-built cast, both the default and what compose() falls back to: coders, not
    debaters, distinguished only enough that identical prompts do not converge on identical
    code."""
    fill = {
        f"coder_{i}": AgentSpec(
            prompt=f"You are implementer {i} of {n} working this problem independently."
        )
        for i in range(n)
    }
    return SystemSpec(preset="swarm", fill={"personas": fill})


def parse_json_block(text: str) -> str:
    """Extracts just the first complete JSON value from a reply: strips a wrapping fenced
    code block if there is one (models reach for one out of habit even when told plain
    JSON), then trims anything left over after the closing brace — a model asked for
    "only JSON, no other text" does not reliably stop there, and the plain
    `model_validate_json` this feeds used to choke on that trailing text as a whole."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else body
        body = body.rsplit("```", 1)[0]
    body = body.strip()
    start = next((i for i, c in enumerate(body) if c in "{["), 0)
    _, end = json.JSONDecoder().raw_decode(body, start)
    return body[start:end]


def _schema_hint(returns: Any) -> str:
    try:
        return json.dumps(TypeAdapter(returns).json_schema())
    except (TypeError, ValueError):
        return getattr(returns, "__name__", str(returns))


class _NoView:
    """A `View` good for nothing but satisfying the type: the openrouter judge calls a
    backend's `complete()` directly, outside the blackboard the swarm runs on, so there is
    no store behind it to read."""

    def get(self, tag: str) -> Any:
        return None

    def value(self, tag: str) -> Any:
        return None

    def query(self, pattern: str) -> list[Any]:
        return []

    def exists(self, pattern: str) -> bool:
        return False

    def count(self, pattern: str) -> int:
        return 0


NO_VIEW = _NoView()


class TimeoutLLM:
    """Wraps a backend so no single call outruns `timeout`, the way `ClaudeCodeLLM` already
    bounds its own CLI sessions via `Agent(..., timeout=...)`. `PydanticAI`'s OpenRouter
    calls have no timeout of their own otherwise, so a slow or stuck provider response
    would hang the whole run rather than fail that one call the way a stuck claude-code
    session already does — the failure is then just one more entry in `RunState.errors`,
    the same as any other persona-call exception, since `SwarmPreset` already tolerates
    (`halt_on_error=False`) one voice failing without ending the round for the others."""

    def __init__(self, inner: Any, timeout: float) -> None:
        self._inner = inner
        self._timeout = timeout

    @property
    def usage(self) -> Usage:
        return self._inner.usage

    async def complete(self, call: Call, view: View) -> Any:
        return await asyncio.wait_for(self._inner.complete(call, view), self._timeout)


class Tape(Plugin):
    """Appends what the swarm phase has spent so far after every superstep, the same
    JSONL-per-line shape `benchmarks/swarm/run.py`'s own `Tape` writes — so the web UI's
    existing spend meter (`SwarmView`, which already reads exactly this shape for the
    free-topic swarm) works for a paperbench run too, live, without a change on that side
    beyond pointing it at this file. Only meaningful under `--backend openrouter`; nothing
    calls this for claude-code, which has no per-token cost to tape."""

    def __init__(self, path: Path, backend: Any, price: Price) -> None:
        self._path = path
        self._backend = backend
        self._price = price
        path.write_text("")

    async def after_step(self, report: StepReport) -> None:
        usage = self._backend.usage
        line = json.dumps(
            {
                "index": report.index,
                "fired": len(report.fired),
                "requests": usage.requests,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "usd": round(self._price.of(usage), 8),
                "at": round(time.time(), 3),
            }
        )
        with self._path.open("a") as handle:
            handle.write(line + "\n")


class ClaudeCodeLLM:
    """Implements fedotmas_llm's `LLM` protocol — `async complete(call, view) -> Any` — over
    the harness's `claude-code` provider. Every call is a fresh, tool-less coding-agent
    session in its own scratch directory: personas, the preset's own queen, and compose()
    all reach the same subscription-backed model through this one seam."""

    def __init__(self, model: str, scratch: Path, timeout: float) -> None:
        self._model = model
        self._scratch = scratch
        self._timeout = timeout
        self._calls = 0

    @property
    def usage(self) -> Usage:
        return Usage(requests=self._calls)

    async def complete(self, call: Call, view: View) -> Any:
        self._calls += 1
        session_dir = self._scratch / f"call-{self._calls}"
        session_dir.mkdir(parents=True, exist_ok=True)
        content = call.input if isinstance(call.input, str) else json.dumps(call.input)
        prompt = f"{call.prompt}\n\n{content}"
        if call.returns is not str:
            prompt += (
                "\n\nAnswer with only a JSON object, no other text, matching this shape: "
                f"{_schema_hint(call.returns)}"
            )
        async with Agent(
            model=self._model,
            provider=Provider("claude-code"),
            cwd=str(session_dir),
            timeout=self._timeout,
        ) as agent:
            result = await agent.run(prompt)
        if call.returns is str:
            return result.output
        return TypeAdapter(call.returns).validate_json(parse_json_block(result.output))


def write_status(path: Path, step: str, percent: int) -> None:
    path.write_text(json.dumps({"step": step, "percent": percent}))


def code_files(workdir: Path) -> list[Path]:
    return sorted(workdir.rglob("*.py"))


def file_summaries(files: list[Path], workdir: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(workdir)),
            "absPath": str(path),
            "lines": path.read_text().count("\n") + 1,
        }
        for path in files
    ]


class Verdict(BaseModel):
    id: str
    passed: bool
    reason: str


class JudgeReport(BaseModel):
    verdicts: list[Verdict]


def judge_prompt(leaves: list[dict[str, Any]], code: str) -> str:
    checks = "\n".join(f"- [{leaf['id']}] {leaf['requirements']}" for leaf in leaves)
    return (
        f"You are reviewing code against a grading rubric, by reading it, not running it. "
        f"The code is already given in full below, so there is nothing to read or run: "
        f"do not inspect the working directory or execute anything, just answer from "
        f"what is here.\n\n"
        f"Code:\n```python\n{code}\n```\n\n"
        f"For each requirement, say whether the code satisfies it and why:\n{checks}\n\n"
        f"Answer with only a JSON object, no other text: "
        f'{{"verdicts": [{{"id": "...", "passed": true or false, "reason": "..."}}, ...]}}, '
        f"one entry per requirement above, in the same order."
    )


def parse_judge_output(text: str) -> JudgeReport:
    return JudgeReport.model_validate_json(parse_json_block(text))


def score(leaves: list[dict[str, Any]], report: JudgeReport) -> dict[str, Any]:
    verdict_by_id = {v.id: v for v in report.verdicts}
    total = sum(leaf["weight"] for leaf in leaves)
    passed = sum(
        leaf["weight"]
        for leaf in leaves
        if (v := verdict_by_id.get(leaf["id"])) and v.passed
    )
    return {
        "score": passed / total if total else 0.0,
        "leaves": [
            {
                "id": leaf["id"],
                "requirements": leaf["requirements"],
                "weight": leaf["weight"],
                "passed": bool(v.passed)
                if (v := verdict_by_id.get(leaf["id"]))
                else False,
                "reason": v.reason
                if (v := verdict_by_id.get(leaf["id"]))
                else "not graded",
            }
            for leaf in leaves
        ],
    }


@dataclass
class RunState:
    """The one fact this pipeline threads through both nodes: everything the swarm needs to
    run, plus everything the judge needs once it is done. A node reads it, returns a new one
    (dataclasses.replace, not mutation) — the usual shape for an action() atom that is not
    just an isolated side effect."""

    leaves: list[dict[str, Any]]
    summary: str
    blacklist: list[str]
    branch: str
    workdir: Path
    model: str
    timeout: float
    status_path: Path
    personas: int
    rounds: int
    ranked: bool
    seats: int
    compose: bool
    concurrency: int
    seed: int
    cast: list[Any] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)
    code: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    swarm_seconds: float = 0.0
    judge_seconds: float = 0.0
    compose_attempts: int = 0
    compose_fell_back: bool = False
    rounds_run: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    scored: dict[str, Any] = field(default_factory=dict)
    backend: str = "claude-code"
    usd: float = 0.0
    tokens: int = 0
    requests: int = 0
    price_in: float = 0.03
    price_out: float = 0.13
    retries: int = 3
    max_tokens: int = 4000
    usage: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)


async def swarm_node(state: RunState) -> RunState:
    state.workdir.mkdir(parents=True, exist_ok=True)
    scratch = state.workdir / "sessions"
    scratch.mkdir(parents=True, exist_ok=True)
    backend: Any = (
        TimeoutLLM(
            PydanticAI(
                model=state.model,
                model_settings={
                    "max_tokens": state.max_tokens,
                    "temperature": 0.9,
                    **OPENROUTER_SETTINGS,
                },
            ),
            state.timeout,
        )
        if state.backend == "openrouter"
        else ClaudeCodeLLM(state.model, scratch, state.timeout)
    )
    rng = random.Random(state.seed)
    preset = SwarmPreset(
        feed_width=FEED_WIDTH,
        min_active=min(2, state.personas),
        max_active=state.personas,
        ranker=by_interest if state.ranked else None,
        casting=state.seats > 0,
        seats=state.seats,
        rng=rng,
        conduct=CODE_CONDUCT,
    )
    topic = paper_topic(state.summary, state.blacklist, state.leaves)
    fallback = handwritten_cast(state.personas)

    write_status(state.status_path, "swarm", 5)
    started = time.monotonic()

    compose_attempts = 0
    compose_fell_back = False
    spec = fallback
    if state.compose:
        composed = await compose(
            topic, preset, llm=backend, count=state.personas, fallback=fallback
        )
        spec = composed.spec
        compose_attempts = composed.attempts
        compose_fell_back = composed.fell_back

    personas = spec.fill["personas"]
    assert isinstance(personas, dict)
    cast = sorted(personas)
    board = assemble(spec, Catalog(preset))
    db_path = state.workdir / "swarm.db"
    price = Price(state.price_in, state.price_out)
    # a spend cap only makes sense against a metered backend: claude-code runs on the
    # subscription, not per-token, so there is nothing here for it to check
    limit = None
    if state.backend == "openrouter" and (state.usd or state.tokens or state.requests):
        limit = SpendLimit(
            backend,
            usd=state.usd or None,
            tokens=state.tokens or None,
            requests=state.requests or None,
            price=price,
        )
    plugins = PluginDispatcher(
        # same ordering benchmarks/swarm/run.py uses and for the same reason: only HTTP
        # failures are worth another attempt (a 429 or a 5xx clears, a bad prompt or a
        # blown token budget just repeats), so Retry sits outside ConcurrencyLimit, and
        # SpendLimit sits under it so it checks the cap where the call actually leaves.
        # claude-code raises its own exceptions, never `ModelHTTPError`, so Retry would be
        # a pure no-op there — left out rather than added as dead weight.
        [
            *(
                [Retry(state.retries, on=ModelHTTPError)]
                if state.backend == "openrouter"
                else []
            ),
            ConcurrencyLimit(max(1, state.concurrency)),
            *(
                [Tape(Path(f"{db_path}.usage.jsonl"), backend, price)]
                if state.backend == "openrouter"
                else []
            ),
            *([limit] if limit else []),
        ]
    )
    system = board.system(bind={"llm": backend}, plugins=plugins)
    # written before the run, not after, the same way benchmarks/swarm/run.py does: a
    # reader watching the store mid-run otherwise has the posts but not the cast that
    # produced them, and the web UI's influence graph reads this file by convention
    Path(f"{db_path}.spec.json").write_text(spec.model_dump_json(indent=2))
    store = SqliteStore(str(db_path))

    run = await system.run(
        preset.seed(topic, cast),
        goal="__never__",  # nothing writes this tag: only the round budget ends the run
        budget=state.rounds,
        plugins=plugins,
        store=store,
    )
    swarm_seconds = time.monotonic() - started
    write_status(state.status_path, "swarm", 55)

    store_view = store.snapshot()
    posts = store_view.query("post")
    store.close()

    # halt_on_error=False (SwarmPreset's own setting) means one persona's failed call
    # never kills the round for the others, but it also means a failure is otherwise
    # invisible: run.errors is the only record of it, so it is carried into the report
    # rather than dropped along with the swallowed exception.
    errors = [
        {"producer": e.producer, "step": e.step, "error": str(e.value)}
        for e in run.errors
    ]

    last_post: dict[str, str] = {}
    for post in posts:
        if post.producer in cast:
            last_post[post.producer] = str(post.value)

    variants = [
        {"id": name, "angle": "", "code": code, "files": []}
        for name, code in last_post.items()
    ]

    usage = state.usage
    if state.backend == "openrouter":
        u: Usage = backend.usage
        usage = {
            **usage,
            "swarm": {
                "requests": u.requests,
                "inputTokens": u.input_tokens,
                "outputTokens": u.output_tokens,
            },
        }

    return replace(
        state,
        cast=cast,
        variants=variants,
        swarm_seconds=swarm_seconds,
        compose_attempts=compose_attempts,
        compose_fell_back=compose_fell_back,
        rounds_run=len(run.steps),
        errors=errors,
        usage=usage,
        budget=limit.report() if limit else {},
    )


async def judge_variant(
    state: RunState, variant: dict[str, Any], provider: Provider
) -> dict[str, Any]:
    # claude-code does not support switching mode after the session opens (mode="chat" is
    # rejected), so the judge gets its own empty directory instead: nothing there for it to
    # read or write even if it reaches for a tool the prompt never asks it to use.
    judge_dir = state.workdir / "judge" / variant["id"]
    judge_dir.mkdir(parents=True, exist_ok=True)
    async with Agent(
        model=state.model,
        provider=provider,
        cwd=str(judge_dir),
        timeout=state.timeout,
    ) as judge:
        result = await judge.run(judge_prompt(state.leaves, variant["code"]))
    verdicts = parse_judge_output(result.output)
    return score(state.leaves, verdicts)


async def judge_variant_openrouter(
    state: RunState, variant: dict[str, Any], backend: Any
) -> dict[str, Any]:
    """The openrouter judge skips markov_sdk's `Agent`/`Provider` session entirely — that
    seam is a claude-code coding-agent session with tools and a cwd, and a plain chat
    completion has no use for either. `PydanticAI.complete` validates its reply against
    `call.returns` itself, so unlike `judge_variant` there is no JSON to parse by hand."""
    call = Call(
        prompt=judge_prompt(state.leaves, variant["code"]),
        input="",
        returns=JudgeReport,
    )
    report = await backend.complete(call, NO_VIEW)
    return score(state.leaves, report)


async def judge_node(state: RunState) -> RunState:
    if not state.variants:
        # nobody posted in the round budget given (too few rounds for this many personas)
        return replace(state, scored=score(state.leaves, JudgeReport(verdicts=[])))

    write_status(state.status_path, "judge", 60)
    started = time.monotonic()
    semaphore = asyncio.Semaphore(max(1, state.concurrency))
    judge_backend: Any = None

    if state.backend == "openrouter":
        judge_backend = TimeoutLLM(
            PydanticAI(
                model=state.model,
                model_settings={
                    "max_tokens": state.max_tokens,
                    "temperature": 0.1,
                    **OPENROUTER_SETTINGS,
                },
            ),
            state.timeout,
        )

        async def bounded(variant: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await judge_variant_openrouter(state, variant, judge_backend)
    else:
        provider = Provider("claude-code")

        async def bounded(variant: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await judge_variant(state, variant, provider)

    scored = list(await asyncio.gather(*(bounded(v) for v in state.variants)))
    judge_seconds = time.monotonic() - started
    write_status(state.status_path, "judge", 95)

    best = max(range(len(scored)), key=lambda i: scored[i]["score"])
    winner = state.variants[best]
    solution = state.workdir / "solution.py"
    solution.write_text(winner["code"])
    cast = [
        {"id": v["id"], "angle": v["angle"], "score": s["score"]}
        for v, s in zip(state.variants, scored)
    ]
    usage = state.usage
    if judge_backend is not None:
        u: Usage = judge_backend.usage
        usage = {
            **usage,
            "judge": {
                "requests": u.requests,
                "inputTokens": u.input_tokens,
                "outputTokens": u.output_tokens,
            },
        }
    return replace(
        state,
        judge_seconds=judge_seconds,
        code=winner["code"],
        files=file_summaries([solution], state.workdir),
        scored=scored[best],
        cast=cast,
        usage=usage,
    )


# Sequence composition over the engine: the swarm's output state is the judge's input,
# checked at compose time, not just at call time. Unlike the earlier version of this
# script, the swarm stage here is not a bespoke pipeline node — it is the same
# SwarmPreset/blackboard the topic-debate benchmark runs, just seeded with a paper's rubric
# branch as its "topic" and a code-writing conduct instead of a debate one.
pipeline = action(swarm_node, name="swarm") + action(judge_node, name="judge")


async def main(args: argparse.Namespace) -> dict[str, Any]:
    paper_dir = DATA / args.paper
    if args.paper_md and args.paper_tex:
        raise ValueError("pass one of --paper-md or --paper-tex, not both")
    workdir = Path(args.workdir)
    if args.paper_md:
        md = Path(args.paper_md)
        summary, paper_source = md.read_text(), md.name
    elif args.paper_tex:
        write_status(Path(args.status), "parsing", 2)
        summary, paper_source = parse_tex_text(Path(args.paper_tex), workdir)
    else:
        summary, paper_source = load_paper_text(paper_dir)
    if args.rubric:
        branch_data = json.loads(Path(args.rubric).read_text())
    else:
        branch_data = json.loads((paper_dir / "rubric_branch.json").read_text())
    branch_requirements, leaves = load_branch(branch_data)
    print(f"--- paper text ({paper_source}, {len(summary)} chars) ---", flush=True)
    print(summary, flush=True)
    print("--- rubric branch ---", flush=True)
    print(json.dumps(branch_data, indent=2, ensure_ascii=False), flush=True)
    if args.blacklist:
        blacklist = Path(args.blacklist).read_text().split()
    else:
        blacklist_path = paper_dir / "blacklist.txt"
        blacklist = (
            blacklist_path.read_text().split()
            if not (args.paper_md or args.paper_tex or args.rubric)
            and blacklist_path.exists()
            else []
        )

    default_price = OPENROUTER_PRICES.get(args.model, Price(0.03, 0.13))
    price_in = args.price_in if args.price_in is not None else default_price.input
    price_out = args.price_out if args.price_out is not None else default_price.output

    state = RunState(
        leaves=leaves,
        summary=summary,
        blacklist=blacklist,
        branch=branch_requirements,
        workdir=Path(args.workdir),
        model=args.model,
        timeout=args.timeout,
        status_path=Path(args.status),
        personas=args.personas,
        rounds=args.rounds,
        ranked=args.ranked,
        seats=args.seats,
        compose=args.compose,
        concurrency=args.concurrency,
        seed=args.seed,
        backend=args.backend,
        usd=args.usd,
        tokens=args.tokens,
        requests=args.requests,
        price_in=price_in,
        price_out=price_out,
        retries=args.retries,
        max_tokens=args.max_tokens,
    )
    result = (await pipeline.run(state)).unwrap()

    return {
        "branch": result.branch,
        "paperSource": paper_source,
        "code": result.code,
        "files": result.files,
        "workdir": str(result.workdir),
        "personas": len(result.cast),
        "roundsRun": result.rounds_run,
        "cast": result.cast,
        "compose": {
            "attempts": result.compose_attempts,
            "fellBack": result.compose_fell_back,
        }
        if args.compose
        else None,
        "swarmSeconds": round(result.swarm_seconds, 1),
        "judgeSeconds": round(result.judge_seconds, 1),
        "backend": args.backend,
        "usage": result.usage,
        "budget": result.budget,
        **result.scored,
    }


def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--paper", default="stochastic-interpolants")
    p.add_argument(
        "--paper-md",
        default=None,
        help="parsed paper markdown; skips data/<paper>/paper.md",
    )
    p.add_argument(
        "--paper-tex",
        default=None,
        help="paper LaTeX source (a .tex file or a directory of them), cleaned at "
        "startup; needs nothing beyond the standard library",
    )
    p.add_argument(
        "--rubric",
        default=None,
        help="rubric branch JSON; defaults to data/<paper>/rubric_branch.json",
    )
    p.add_argument(
        "--blacklist",
        default=None,
        help="defaults to data/<paper>/blacklist.txt when only --paper is given",
    )
    p.add_argument(
        "--backend",
        choices=["claude-code", "openrouter"],
        default="claude-code",
        help="claude-code (default) drives your own claude CLI subscription; openrouter "
        "is a metered API call and needs OPENROUTER_API_KEY in .env",
    )
    p.add_argument(
        "--model",
        default="haiku",
        help="for --backend claude-code, a claude CLI model alias (haiku, sonnet, opus, "
        "fable), which track that family's latest version; for --backend openrouter, an "
        "OpenRouter model id (e.g. openrouter:qwen/qwen3.7-flash)",
    )
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--workdir", default=str(Path(__file__).parent / "out" / "workdir"))
    p.add_argument(
        "--report", default=str(Path(__file__).parent / "out" / "report.json")
    )
    p.add_argument(
        "--status", default=str(Path(__file__).parent / "out" / "status.json")
    )
    p.add_argument(
        "--personas",
        type=int,
        default=3,
        help="voices in the swarm; each one's last post is scored as its code",
    )
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument(
        "--ranked", action="store_true", help="give each persona its own ranked feed"
    )
    p.add_argument(
        "--seats", type=int, default=0, help="free seats a queen may fill mid-run"
    )
    p.add_argument(
        "--compose", action="store_true", help="let a meta-agent write the cast"
    )
    p.add_argument(
        "--concurrency", type=int, default=2, help="claude CLI sessions at once"
    )
    p.add_argument(
        "--usd",
        type=float,
        default=0.0,
        help="stop the run once it costs this (openrouter backend only)",
    )
    p.add_argument(
        "--tokens",
        type=int,
        default=0,
        help="stop after this many tokens (openrouter backend only)",
    )
    p.add_argument(
        "--requests",
        type=int,
        default=0,
        help="stop after this many requests (openrouter backend only)",
    )
    p.add_argument(
        "--price-in",
        type=float,
        default=None,
        help="USD per 1M input tokens; defaults to --model's own price in "
        "OPENROUTER_PRICES when known, else qwen3.7-flash's",
    )
    p.add_argument(
        "--price-out",
        type=float,
        default=None,
        help="USD per 1M output; see --price-in",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=3,
        help="attempts per call on a transient HTTP error (openrouter backend only)",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="response length cap per call (openrouter backend only); a persona writes "
        "a whole file each post, not a one-line argument the way free-topic's does, so "
        "this defaults far above free-topic's own --max-tokens 800",
    )
    p.add_argument("--seed", type=int, default=7)
    return p.parse_args()


if __name__ == "__main__":
    args = cli()
    load_dotenv(Path(__file__).parents[2] / ".env")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    report = json.dumps(asyncio.run(main(args)), indent=2, ensure_ascii=False)
    Path(args.report).write_text(report)
    print(report)
