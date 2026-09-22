"""A Code Development slice of PaperBench, run through the same swarm the topic-debate
benchmark uses (`SwarmPreset`): a cast of voices on one shared feed over several rounds,
`ActivitySample` deciding who speaks, an optional queen recasting mid-run, an optional
meta-agent (`compose()`) writing the cast. What differs is what a voice is. With
`--workers opencode` (default) every voice is an OpenCode coding agent in its own git
workspace, seeded with the paper and the rubric; each round it works for up to
`--round-minutes`, commits, and posts a short report to the feed. With `--workers prompt`
a voice is one metered prompt per round that posts a whole file, the earlier shape, kept for
cheap tests. After the round budget a judge reads every voice's workspace (never runs it),
grades it leaf by leaf, and the best one is copied to `<workdir>/solution`.

The composer, the queen, the prompt voices and the judge run over `PydanticAI`; the
OpenCode voices report their own tokens and cost through `OpenCodeMeter`. One `SpendLimit`
reads all of them, so `--usd`/`--tokens`/`--requests` cap the whole run, judge included.

Usage:
uv run --extra pydantic-ai --extra opencode --group paperbench \\
  python benchmarks/paperbench/run.py --paper classifier-free-guidance \\
  --paper-pdf benchmarks/paperbench/data/classifier-free-guidance/paper.pdf \\
  --personas 2 --rounds 2 --round-minutes 3 --usd 0.3
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import shlex
import shutil
import signal
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fedotmas.atoms import action
from fedotmas.engine import PluginDispatcher, SqliteStore
from fedotmas.engine.contract import View
from fedotmas.engine.plugin import Plugin
from fedotmas.engine.report import StepReport
from fedotmas.ext.plugins import ConcurrencyLimit, Retry
from fedotmas_llm import Call, Meter, Price, SpendLimit, Usage, billed
from fedotmas_llm.adapters.opencode import OpenCodeMeter, OpenCodeServer
from fedotmas_llm.adapters.pydantic_ai import PydanticAI
from fedotmas_meta import AgentSpec, Catalog, SystemSpec, assemble, compose
from fedotmas_meta.presets import SwarmPreset, by_interest, post_text
from paper import paper_brief, paper_topic, sha256_of
from parse_pdf import ENGINES
from parse_pdf import convert as convert_pdf
from parse_tex import convert as convert_tex
from pydantic_ai.exceptions import ModelHTTPError
from rubric import (
    JudgeReport,
    batches,
    judge_prompt,
    load_branch,
    rubric_markdown,
    score,
)
from workers import (
    WORKSPACE_CONDUCT,
    LiveBoard,
    Voice,
    Workspaces,
    judge_code,
    opencode_config,
    opencode_voice,
)

DATA = Path(__file__).parent / "data"
FEED_WIDTH = 12
# coders, not debaters: a voice that skips most rounds leaves its workspace half done
ACTIVITY = (0.75, 1.0)
JUDGE_BATCH = 20
JUDGE_MIN_TOKENS = 12_000
DEFAULT_MODEL = "openrouter:qwen/qwen3.8-flash"
SOLUTION_IGNORE = shutil.ignore_patterns(
    ".git", ".fedotmas", ".venv", "__pycache__", "node_modules"
)

# Structured calls (compose, the queen, the judge) ask pydantic-ai for a typed output via a
# forced tool_choice, which some OpenRouter models reject while their thinking mode is on
# (HTTP 400 from qwen3.8-flash over Alibaba). Reasoning off is the setting that works.
OPENROUTER_SETTINGS = {"extra_body": {"reasoning": {"enabled": False}}}

# OpenRouter catalog prices, USD per 1M tokens. A model missing here needs --price-in and
# --price-out, since a cap checked against a guessed price is not a cap.
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


class Stopped(Exception):
    """The run was asked to stop (SIGTERM or SIGINT) before the swarm finished."""


class _NoView:
    """A `View` good for nothing but satisfying the type: the judge calls the backend
    outside the blackboard, so there is no store behind it to read."""

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
    """Wraps a backend so no single call outruns `timeout`; a stuck provider response then
    fails one call, recorded as an error fact, instead of hanging the run."""

    def __init__(self, inner: Any, timeout: float) -> None:
        self._inner = inner
        self._timeout = timeout

    @property
    def usage(self) -> Usage:
        return self._inner.usage

    async def complete(self, call: Call, view: View) -> Any:
        return await asyncio.wait_for(self._inner.complete(call, view), self._timeout)


def write_status(path: Path, step: str, percent: int, **extra: Any) -> None:
    path.write_text(
        json.dumps({"step": step, "percent": percent, "at": time.time(), **extra})
    )


class Tape(Plugin):
    """Appends the run's spend after every superstep, one json line each, the shape the web
    UI's spend meter reads, and moves the status file's round counter along with it."""

    def __init__(
        self,
        path: Path,
        meters: list[Meter],
        price: Price,
        workers: OpenCodeMeter | None,
        status: Path,
        rounds: int,
    ) -> None:
        self._path = path
        self._meters = meters
        self._price = price
        self._workers = workers
        self._status = status
        self._rounds = rounds
        path.write_text("")

    async def after_step(self, report: StepReport) -> None:
        usage = Usage()
        for meter in self._meters:
            usage += meter.usage
        line = {
            "index": report.index,
            "fired": len(report.fired),
            "requests": usage.requests,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "usd": round(billed(tuple(self._meters), self._price), 8),
            "workers_usd": round(self._workers.cost, 8) if self._workers else 0.0,
            "at": round(time.time(), 3),
        }
        with self._path.open("a") as handle:
            handle.write(json.dumps(line) + "\n")
        done = report.index + 1
        write_status(
            self._status,
            "swarm",
            5 + int(50 * min(done, self._rounds) / max(1, self._rounds)),
            round=done,
            rounds=self._rounds,
        )


def handwritten_cast(n: int) -> SystemSpec:
    """The default cast and what compose() falls back to: implementers distinguished only
    enough that identical prompts do not converge on identical code."""
    fill = {
        f"coder_{i}": AgentSpec(
            prompt=f"You are implementer {i} of {n} working this problem independently."
        )
        for i in range(n)
    }
    return SystemSpec(preset="swarm", fill={"personas": fill})


def file_summaries(root: Path) -> list[dict[str, Any]]:
    out = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if rel.parts[0] in {".git", ".fedotmas", "__pycache__"}:
            continue
        try:
            lines = path.read_text().count("\n") + 1
        except UnicodeDecodeError:
            lines = 0
        out.append({"path": str(rel), "absPath": str(path), "lines": lines})
    return out


@dataclass
class RunState:
    """Everything the swarm needs to run and everything the judge needs once it is done,
    threaded through the two nodes; a node returns a new one, it does not mutate."""

    leaves: list[dict[str, Any]]
    summary: str
    blacklist: list[str]
    branch: str
    workdir: Path
    model: str
    worker_model: str
    workers: str
    timeout: float
    status_path: Path
    personas: int
    rounds: int
    ranked: bool
    seats: int
    compose: bool
    concurrency: int
    seed: int
    round_minutes: float
    steps: int
    opencode_bin: str
    judge: Any
    stop: asyncio.Event
    price: Price
    usd: float = 0.0
    tokens: int = 0
    requests: int = 0
    retries: int = 3
    max_tokens: int = 4000
    cast: list[Any] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)
    limit: SpendLimit | None = None
    code: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    kept: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    swarm_seconds: float = 0.0
    judge_seconds: float = 0.0
    compose_attempts: int = 0
    compose_fell_back: bool = False
    rounds_run: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    scored: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)


def _usage_dict(u: Usage) -> dict[str, int]:
    return {
        "requests": u.requests,
        "inputTokens": u.input_tokens,
        "outputTokens": u.output_tokens,
    }


def _trace(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """Per voice: how many rounds it worked and what they cost."""
    out: dict[str, Any] = {}
    for post in posts:
        row = out.setdefault(
            post["voice"],
            {
                "rounds": 0,
                "tokens": 0,
                "cost": 0.0,
                "filesChanged": 0,
                "toolCalls": 0,
                "timedOut": 0,
            },
        )
        row["rounds"] += 1
        row["tokens"] += sum(post["tokens"].values())
        row["cost"] += post["cost"]
        row["filesChanged"] += len(post["files"])
        row["toolCalls"] += sum(post["toolCalls"].values())
        row["timedOut"] += int(post["timedOut"])
    for row in out.values():
        row["cost"] = round(row["cost"], 6)
    return out


async def swarm_node(state: RunState) -> RunState:
    state.workdir.mkdir(parents=True, exist_ok=True)
    backend = TimeoutLLM(
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
    server: OpenCodeServer | None = None
    voice: Voice | None = None
    extra: dict[str, Any] = {"conduct": CODE_CONDUCT}
    topic = paper_topic(state.summary, state.blacklist, state.leaves)
    if state.workers == "opencode":
        brief = paper_brief(state.summary, state.blacklist, state.branch, state.leaves)
        provider, _, model_id = state.worker_model.partition("/")
        ws_root = state.workdir / "ws"
        server = OpenCodeServer(
            ws_root,
            env={
                "OPENCODE_CONFIG_CONTENT": json.dumps(
                    opencode_config(state.worker_model, state.steps)
                ),
                "OPENCODE_DISABLE_AUTOUPDATE": "1",
            },
            binary=state.opencode_bin,
        )
        voice = Voice(
            server=server,
            workspaces=Workspaces(
                ws_root,
                state.summary,
                rubric_markdown(state.branch, state.leaves),
                brief,
            ),
            model=(provider, model_id),
            round_seconds=state.round_minutes * 60,
            meter=OpenCodeMeter(),
            live=LiveBoard(state.workdir / "live.json"),
        )
        extra = {"conduct": WORKSPACE_CONDUCT, "persona_factory": opencode_voice(voice)}
        topic = brief
    rng = random.Random(state.seed)
    preset = SwarmPreset(
        feed_width=FEED_WIDTH,
        min_active=min(2, state.personas),
        max_active=state.personas,
        activity=ACTIVITY,
        ranker=by_interest if state.ranked else None,
        casting=state.seats > 0,
        seats=state.seats,
        rng=rng,
        **extra,
    )
    fallback = handwritten_cast(state.personas)

    started = time.monotonic()
    if state.compose:
        write_status(state.status_path, "swarm", 3, stage="compose")

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
    meters: list[Meter] = [backend, state.judge]
    if voice is not None:
        meters.insert(1, voice.meter)
    limit = None
    if state.usd or state.tokens or state.requests:
        limit = SpendLimit(
            *meters,
            usd=state.usd or None,
            tokens=state.tokens or None,
            requests=state.requests or None,
            price=state.price,
        )
    plugins = PluginDispatcher(
        # Retry only catches provider HTTP errors, so in practice it covers the pydantic-ai
        # nodes; an OpenCode voice reports its own failures on its post. SpendLimit sits
        # under ConcurrencyLimit so it checks the cap where the call actually leaves.
        [
            Retry(state.retries, on=ModelHTTPError),
            ConcurrencyLimit(max(1, state.concurrency)),
            Tape(
                Path(f"{db_path}.usage.jsonl"),
                meters,
                state.price,
                voice.meter if voice else None,
                state.status_path,
                state.rounds,
            ),
            *([limit] if limit else []),
        ]
    )
    system = board.system(bind={"llm": backend}, plugins=plugins)
    # written before the run so a reader watching the store mid-run has the cast too
    Path(f"{db_path}.spec.json").write_text(spec.model_dump_json(indent=2))
    store = SqliteStore(str(db_path))

    if server is not None:
        await server.start()
    write_status(state.status_path, "swarm", 5, round=0, rounds=state.rounds)
    try:
        running = asyncio.create_task(
            system.run(
                preset.seed(topic, cast),
                goal="__never__",  # nothing writes this tag: the round budget ends the run
                budget=state.rounds,
                plugins=plugins,
                store=store,
            )
        )
        stopping = asyncio.create_task(state.stop.wait())
        await asyncio.wait({running, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if not running.done():
            running.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await running
            store.close()
            raise Stopped()
        stopping.cancel()
        run = running.result()
    finally:
        if server is not None:
            await server.stop()
    swarm_seconds = time.monotonic() - started
    write_status(
        state.status_path, "swarm", 55, round=len(run.steps), rounds=state.rounds
    )

    posts = store.snapshot().query("post")
    store.close()

    # halt_on_error=False means one voice's failure never kills the round for the others,
    # so run.errors is the only record of it and is carried into the report
    errors = [
        {"producer": e.producer, "step": e.step, "error": str(e.value)}
        for e in run.errors
    ]

    variants: list[dict[str, Any]] = []
    if voice is not None:
        by_voice: dict[str, list[dict[str, Any]]] = {}
        for post in posts:
            if post.producer in cast and isinstance(post.value, dict):
                by_voice.setdefault(post.producer, []).append(post.value)
        for name in cast:
            ws = voice.workspaces.path(name)
            if not ws.exists():
                continue
            rounds = by_voice.get(name, [])
            variants.append(
                {
                    "id": name,
                    "workspace": str(ws),
                    "rounds": len(rounds),
                    "lastReport": post_text(rounds[-1]) if rounds else "",
                    "tokens": sum(sum(r["tokens"].values()) for r in rounds),
                    "cost": round(sum(r["cost"] for r in rounds), 6),
                    "files": voice.workspaces.files(name),
                }
            )
        trace = _trace([p for rs in by_voice.values() for p in rs])
    else:
        last_post: dict[str, str] = {}
        for post in posts:
            if post.producer in cast:
                last_post[post.producer] = post_text(post.value)
        variants = [
            {"id": name, "code": code, "rounds": 0, "cost": 0.0, "files": []}
            for name, code in last_post.items()
        ]
        trace = {}

    usage = {**state.usage, "swarm": _usage_dict(backend.usage)}
    if voice is not None:
        usage["workers"] = {**_usage_dict(voice.meter.usage), "usd": voice.meter.cost}

    return replace(
        state,
        cast=cast,
        variants=variants,
        limit=limit,
        trace=trace,
        swarm_seconds=swarm_seconds,
        compose_attempts=compose_attempts,
        compose_fell_back=compose_fell_back,
        rounds_run=len(run.steps),
        errors=errors,
        usage=usage,
    )


async def judge_variant(state: RunState, code: str) -> dict[str, Any]:
    """One structured call per slice of the rubric, merged into one report;
    `PydanticAI.complete` validates each reply against `JudgeReport` itself."""
    verdicts = []
    for part in batches(state.leaves, JUDGE_BATCH):
        call = Call(prompt=judge_prompt(part, code), input="", returns=JudgeReport)
        report = await state.judge.complete(call, NO_VIEW)
        verdicts.extend(report.verdicts)
    return score(state.leaves, JudgeReport(verdicts=verdicts))


def _variant_code(variant: dict[str, Any]) -> str:
    if "workspace" in variant:
        return judge_code(Path(variant["workspace"]))
    return str(variant.get("code", ""))


async def judge_node(state: RunState) -> RunState:
    if not state.variants:
        return replace(state, scored=score(state.leaves, JudgeReport(verdicts=[])))

    write_status(state.status_path, "judge", 60)
    started = time.monotonic()
    semaphore = asyncio.Semaphore(max(1, state.concurrency))
    codes = [_variant_code(v) for v in state.variants]

    async def bounded(code: str) -> dict[str, Any]:
        async with semaphore:
            if state.limit is not None and state.limit.over():
                graded = score(state.leaves, JudgeReport(verdicts=[]))
                for leaf in graded["leaves"]:
                    leaf["reason"] = "not graded (budget)"
                return graded | {"skipped": True}
            return await judge_variant(state, code)

    scored = list(await asyncio.gather(*(bounded(c) for c in codes)))
    judge_seconds = time.monotonic() - started
    write_status(state.status_path, "judge", 95)

    best = max(range(len(scored)), key=lambda i: scored[i]["score"])
    winner = state.variants[best]
    solution = state.workdir / "solution"
    if solution.exists():
        shutil.rmtree(solution)
    if "workspace" in winner:
        shutil.copytree(winner["workspace"], solution, ignore=SOLUTION_IGNORE)
        code = codes[best]
    else:
        solution.mkdir(parents=True)
        (solution / "solution.py").write_text(winner["code"])
        code = winner["code"]
    cast = [
        {
            "id": v["id"],
            "score": s["score"],
            "rounds": v.get("rounds", 0),
            "cost": v.get("cost", 0.0),
            "filesChanged": state.trace.get(v["id"], {}).get("filesChanged", 0),
            "graded": not s.get("skipped", False),
        }
        for v, s in zip(state.variants, scored)
    ]
    usage = {**state.usage, "judge": _usage_dict(state.judge.usage)}
    return replace(
        state,
        judge_seconds=judge_seconds,
        code=code,
        files=file_summaries(solution),
        kept={"voice": winner["id"], "dir": str(solution)},
        scored={k: v for k, v in scored[best].items() if k != "skipped"},
        cast=cast,
        usage=usage,
        budget=state.limit.report() if state.limit else {},
    )


# The swarm's output state is the judge's input, checked at compose time.
pipeline = action(swarm_node, name="swarm") + action(judge_node, name="judge")


def worker_model_of(args: argparse.Namespace) -> str:
    """`openrouter:qwen/x` for pydantic-ai is `openrouter/qwen/x` for OpenCode."""
    if args.worker_model:
        return args.worker_model
    provider, sep, model = args.model.partition(":")
    return f"{provider}/{model}" if sep else args.model


def price_of(args: argparse.Namespace) -> Price:
    known = OPENROUTER_PRICES.get(args.model)
    if known is None and (args.price_in is None or args.price_out is None):
        raise SystemExit(
            f"no catalog price for {args.model}: pass --price-in and --price-out "
            "(USD per 1M tokens)"
        )
    known = known or Price()
    return Price(
        args.price_in if args.price_in is not None else known.input,
        args.price_out if args.price_out is not None else known.output,
    )


def load_inputs(
    args: argparse.Namespace, workdir: Path, status: Path
) -> tuple[str, dict[str, Any], list[str], dict[str, Any]]:
    """The paper text, the rubric branch, the blacklist, and a digest of where they came
    from, so a run can be told apart from another and reproduced."""
    paper_dir = DATA / args.paper
    sources = [s for s in (args.paper_md, args.paper_tex, args.paper_pdf) if s]
    if len(sources) > 1:
        raise ValueError("pass at most one of --paper-md, --paper-tex or --paper-pdf")
    inputs: dict[str, Any] = {"paper": args.paper}
    if args.paper_md:
        source = Path(args.paper_md)
        summary = source.read_text()
    elif args.paper_tex:
        source = Path(args.paper_tex)
        write_status(status, "parsing", 2, engine="tex")
        convert_tex(source, workdir / "paper.md")
        summary = (workdir / "paper.md").read_text()
        inputs["engine"] = "tex"
    elif args.paper_pdf:
        source = Path(args.paper_pdf)
        write_status(status, "parsing", 2, engine=args.pdf_engine)
        meta = convert_pdf(source, workdir / "paper.md", args.pdf_engine)
        summary = (workdir / "paper.md").read_text()
        inputs["engine"] = meta["engine"]
        if "fallbackFrom" in meta:
            inputs["fallbackFrom"] = meta["fallbackFrom"]
            inputs["fallbackReason"] = meta["reason"]
    else:
        source = paper_dir / "paper.md"
        if not source.exists():
            source = paper_dir / "paper_summary.md"
        summary = source.read_text()
    inputs["paperSource"] = source.name
    if source.is_file():
        inputs["paperSha256"] = sha256_of(source)
    inputs["paperChars"] = len(summary)
    rubric_path = Path(args.rubric) if args.rubric else paper_dir / "rubric_branch.json"
    branch_data = json.loads(rubric_path.read_text())
    inputs["rubricSource"] = rubric_path.name
    inputs["rubricSha256"] = sha256_of(rubric_path)
    if args.blacklist:
        blacklist = Path(args.blacklist).read_text().split()
    else:
        blacklist_path = paper_dir / "blacklist.txt"
        blacklist = (
            blacklist_path.read_text().split()
            if not sources and not args.rubric and blacklist_path.exists()
            else []
        )
    return summary, branch_data, blacklist, inputs


async def main(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    workdir = Path(args.workdir)
    status = Path(args.status)
    workdir.mkdir(parents=True, exist_ok=True)
    summary, branch_data, blacklist, inputs = load_inputs(args, workdir, status)
    branch_requirements, leaves = load_branch(branch_data)
    print(f"--- paper text ({inputs['paperSource']}, {len(summary)} chars) ---")
    print(summary[:4000] + (" ..." if len(summary) > 4000 else ""), flush=True)
    print(f"--- rubric branch: {len(leaves)} leaves ---", flush=True)

    price = price_of(args)
    judge = TimeoutLLM(
        PydanticAI(
            model=args.model,
            model_settings={
                "max_tokens": max(args.max_tokens, JUDGE_MIN_TOKENS),
                "temperature": 0.1,
                **OPENROUTER_SETTINGS,
            },
            retries=2,
        ),
        args.timeout,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    state = RunState(
        leaves=leaves,
        summary=summary,
        blacklist=blacklist,
        branch=branch_requirements,
        workdir=workdir,
        model=args.model,
        worker_model=worker_model_of(args),
        workers=args.workers,
        timeout=args.timeout,
        status_path=status,
        personas=args.personas,
        rounds=args.rounds,
        ranked=args.ranked,
        seats=args.seats,
        compose=args.compose,
        concurrency=args.concurrency,
        seed=args.seed,
        round_minutes=args.round_minutes,
        steps=args.steps,
        opencode_bin=args.opencode_bin,
        judge=judge,
        stop=stop,
        price=price,
        usd=args.usd,
        tokens=args.tokens,
        requests=args.requests,
        retries=args.retries,
        max_tokens=args.max_tokens,
    )
    outcome = await pipeline.run(state)
    if stop.is_set():
        raise Stopped()
    result = outcome.unwrap()

    return {
        "branch": result.branch,
        "paperSource": inputs["paperSource"],
        "inputs": inputs,
        "params": {
            "seed": args.seed,
            "model": args.model,
            "workerModel": result.worker_model,
            "workers": args.workers,
            "personas": args.personas,
            "rounds": args.rounds,
            "ranked": args.ranked,
            "seats": args.seats,
            "compose": args.compose,
            "concurrency": args.concurrency,
            "usd": args.usd,
            "tokens": args.tokens,
            "requests": args.requests,
            "maxTokens": args.max_tokens,
            "roundMinutes": args.round_minutes,
            "steps": args.steps,
            "pdfEngine": args.pdf_engine,
        },
        "argv": sys.argv[1:],
        "command": shlex.join(
            ["python", "benchmarks/paperbench/run.py", *sys.argv[1:]]
        ),
        "code": result.code,
        "files": result.files,
        "kept": result.kept,
        "workdir": str(result.workdir),
        "personas": len(result.cast),
        "roundsRun": result.rounds_run,
        "cast": result.cast,
        "trace": result.trace,
        "errors": result.errors,
        "compose": {
            "attempts": result.compose_attempts,
            "fellBack": result.compose_fell_back,
        }
        if args.compose
        else None,
        "swarmSeconds": round(result.swarm_seconds, 1),
        "judgeSeconds": round(result.judge_seconds, 1),
        "usage": result.usage,
        "budget": result.budget,
        "startedAt": started_at,
        "endedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        **result.scored,
    }


def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--paper", default="classifier-free-guidance")
    p.add_argument(
        "--paper-md",
        default=None,
        help="parsed paper markdown; skips data/<paper>/paper.md",
    )
    p.add_argument(
        "--paper-tex",
        default=None,
        help="paper LaTeX source (a .tex file or a directory of them), cleaned at startup",
    )
    p.add_argument(
        "--paper-pdf",
        default=None,
        help="paper PDF, converted at startup with --pdf-engine",
    )
    p.add_argument(
        "--pdf-engine",
        choices=ENGINES,
        default="marker",
        help="marker (layout, tables, OCR; minutes) or pymupdf (text layer; seconds)",
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
        "--model",
        default=DEFAULT_MODEL,
        help="pydantic-ai model id for the composer, the queen, the judge and prompt "
        "workers, e.g. openrouter:qwen/qwen3.8-flash",
    )
    p.add_argument(
        "--workers",
        choices=("opencode", "prompt"),
        default="opencode",
        help="opencode: a coding agent per voice in its own workspace; prompt: one "
        "metered prompt per voice per round that posts a whole file",
    )
    p.add_argument(
        "--worker-model",
        default=None,
        help="OpenCode model id for the voices, e.g. openrouter/qwen/qwen3.8-flash; "
        "defaults to --model with the first ':' replaced by '/'",
    )
    p.add_argument(
        "--round-minutes",
        type=float,
        default=5.0,
        help="wall clock an OpenCode voice gets per round before its session is aborted",
    )
    p.add_argument(
        "--steps",
        type=int,
        default=24,
        help="tool-loop steps an OpenCode voice may take per round",
    )
    p.add_argument("--opencode-bin", default=os.environ.get("OPENCODE_BIN", "opencode"))
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--workdir", default=str(Path(__file__).parent / "out" / "workdir"))
    p.add_argument(
        "--report", default=str(Path(__file__).parent / "out" / "report.json")
    )
    p.add_argument(
        "--status", default=str(Path(__file__).parent / "out" / "status.json")
    )
    p.add_argument("--personas", type=int, default=3, help="voices in the swarm")
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
        "--concurrency",
        type=int,
        default=2,
        help="voices (sessions or requests) in flight at once",
    )
    p.add_argument(
        "--usd", type=float, default=0.0, help="stop the run once it costs this"
    )
    p.add_argument("--tokens", type=int, default=0, help="stop after this many tokens")
    p.add_argument(
        "--requests", type=int, default=0, help="stop after this many requests"
    )
    p.add_argument(
        "--price-in",
        type=float,
        default=None,
        help="USD per 1M input tokens; required for a model not in OPENROUTER_PRICES",
    )
    p.add_argument(
        "--price-out", type=float, default=None, help="USD per 1M output tokens"
    )
    p.add_argument(
        "--retries",
        type=int,
        default=3,
        help="attempts per call on a transient HTTP error",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="response length cap per pydantic-ai call",
    )
    p.add_argument("--seed", type=int, default=7)
    return p.parse_args()


if __name__ == "__main__":
    args = cli()
    load_dotenv(Path(__file__).parents[2] / ".env")
    status_path = Path(args.status)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    pid_path = Path(f"{status_path}.pid")
    pid_path.write_text(str(os.getpid()))
    try:
        report = json.dumps(asyncio.run(main(args)), indent=2, ensure_ascii=False)
    except Stopped:
        write_status(status_path, "stopped", 100)
        sys.exit(143)
    except BaseException as e:
        write_status(status_path, "failed", 100, error=str(e)[:500])
        raise
    finally:
        pid_path.unlink(missing_ok=True)
    Path(args.report).write_text(report)
    write_status(status_path, "done", 100)
    print(report)
