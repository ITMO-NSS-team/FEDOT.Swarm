"""The swarm of `packages/fedotmas-llm/tests/test_swarm.py` on a real provider instead of a
stub: personas argue a topic on a shared feed, ActivitySample decides who speaks each round,
ConcurrencyLimit caps in-flight requests, SqliteStore holds the feed, and the provider's token
usage is reported for the whole run. With --compose the cast is written by a meta-agent instead
of by hand, metered separately so composition and simulation costs stay apart. With --usd (or
--tokens, --requests) the run also stops when its budget is spent, mid-conversation.

Costs money and needs OPENROUTER_API_KEY in .env, so it lives here and not under pytest.

Usage:
uv run python benchmarks/swarm/run.py --personas 2 --rounds 1 --concurrency 1
uv run python benchmarks/swarm/run.py --personas 10 --rounds 3 --compose
uv run python benchmarks/swarm/run.py --personas 40 --rounds 15 --usd 0.001
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fedotmas import Plugin
from fedotmas.engine import PluginDispatcher, SqliteStore, View
from fedotmas.engine.contract import Fact, Node, Result
from fedotmas.engine.report import StepReport
from fedotmas.ext.plugins import ConcurrencyLimit, Retry
from fedotmas_llm import Price, SpendLimit
from fedotmas_llm.adapters.pydantic_ai import PydanticAI
from fedotmas_meta import AgentSpec, Catalog, SystemSpec, assemble, compose
from fedotmas_meta.presets import SwarmPreset, by_interest
from pydantic_ai.exceptions import ModelHTTPError

TOPIC = "Should frontier AI labs release model weights openly?"

VOICES = [
    ("an open-source maintainer", "argues from what shipping in public actually costs"),
    ("a safety researcher", "keeps pulling the thread back to misuse"),
    ("a startup founder", "cares about who can afford to compete"),
    ("an academic", "wants reproducibility above everything"),
    ("a policy advisor", "thinks in terms of what is enforceable"),
    ("a security engineer", "asks who patches it after release"),
    ("a journalist", "pushes for a plain answer, distrusts jargon"),
    ("an economist", "reduces the argument to incentives"),
]

FEED_WIDTH = 12


class Watch(Plugin):
    """Innermost plugin: sits under Retry so it counts every attempt (attempts minus fired
    rules is the retry count), under ConcurrencyLimit so its peak is real in-flight requests,
    and records what the provider actually raised."""

    def __init__(self) -> None:
        self.attempts = 0
        self.peak = 0
        self.failures: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()
        self._live = 0

    async def around_node(self, node, input, view, call) -> Result:
        self.attempts += 1
        self._live += 1
        self.peak = max(self.peak, self._live)
        try:
            return await call(input, view)
        except Exception as e:
            self.failures[type(e).__name__] += 1
            raise
        finally:
            self._live -= 1

    async def on_error(self, node: Node, error: Fact, view: View) -> None:
        self.errors[node.describe().name] += 1


class Tape(Plugin):
    """Appends what the run has spent so far after every superstep. The store keeps facts and
    not meters, and the report only lands once the run is over, so without this a reader
    watching the file has the conversation but no bill."""

    def __init__(self, path: Path, backend: PydanticAI, price: Price) -> None:
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


def handwritten(n: int) -> SystemSpec:
    """The hand-built cast, both the default and what the queen falls back to. Character only:
    how to behave on the feed is the preset's to say."""
    fill = {}
    for i in range(n):
        role, quirk = VOICES[i % len(VOICES)]
        fill[f"persona_{i}"] = AgentSpec(
            prompt=f"You are persona {i}, {role} who {quirk}."
        )
    return SystemSpec(preset="swarm", fill={"personas": fill})


def _capped(backend: PydanticAI, args: argparse.Namespace) -> SpendLimit | None:
    """The run's budget, built after composing so the cast costs whatever it costs and the
    cap covers the conversation itself."""
    if not (args.usd or args.tokens or args.requests):
        return None
    return SpendLimit(
        backend,
        usd=args.usd or None,
        tokens=args.tokens or None,
        requests=args.requests or None,
        price=Price(args.price_in, args.price_out),
    )


def _usage(llm: PydanticAI) -> dict[str, int]:
    u = llm.usage
    return {
        "requests": u.requests,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        # reasoning is billed inside output_tokens and fedotmas_llm.Usage does not model the
        # split, so read the provider's own breakdown off the adapter's RunUsage
        "reasoning_tokens": llm._usage.details.get("reasoning_tokens", 0),
    }


def _casting(view) -> dict[str, Any]:
    """What the live queen actually did: an amendment per round, the seats it filled and the
    personas it sent home."""
    final = view.value("cast") or {}
    moves = [a.value for a in view.query("amendment")]
    return {
        "amendments": sum(1 for a in moves if a.get("hire") or a.get("retire")),
        "rounds": len(moves),
        "hired": final.get("hired", {}),
        "retired": final.get("retired", []),
    }


async def main(args: argparse.Namespace) -> dict[str, Any]:
    rng = random.Random(args.seed)
    settings: dict[str, Any] = {"max_tokens": args.max_tokens, "temperature": 0.9}
    if args.no_reasoning:
        settings["extra_body"] = {"reasoning": {"enabled": False}}
    backend = PydanticAI(model=args.model, model_settings=settings)
    preset = SwarmPreset(
        feed_width=FEED_WIDTH,
        min_active=args.min_active,
        max_active=args.max_active,
        ranker=by_interest if args.ranked else None,
        casting=args.seats > 0,
        seats=args.seats,
        rng=rng,
    )

    fallback = handwritten(args.personas)
    queen = PydanticAI(model=args.model, model_settings=settings | {"max_tokens": 8000})
    composed = None
    started = time.monotonic()
    if args.compose:
        composed = await compose(
            args.topic,
            preset,
            llm=queen,
            count=args.personas,
            batch=args.batch or None,
            repairs=args.repairs,
            fallback=fallback,
        )
    composing = time.monotonic() - started

    spec = composed.spec if composed else fallback
    cast = sorted(spec.fill["personas"])
    # before the run, not after: a composed cast is otherwise never persisted, and a reader
    # watching the store mid-run has the posts but not the characters that produced them
    Path(f"{args.db}.spec.json").write_text(spec.model_dump_json(indent=2))
    board = assemble(spec, Catalog(preset))
    watch = Watch()
    limit = _capped(backend, args)
    price = Price(args.price_in, args.price_out)
    plugins = PluginDispatcher(
        # only HTTP failures are worth another attempt: a 429 or a 5xx clears, a bad prompt
        # or a blown token budget just repeats. SpendLimit sits under ConcurrencyLimit so it
        # checks the cap where the call actually leaves, and over Watch so a skipped node is
        # not counted as an attempt
        [
            Tape(Path(f"{args.db}.usage.jsonl"), backend, price),
            Retry(args.retries, on=ModelHTTPError),
            ConcurrencyLimit(args.concurrency),
            *([limit] if limit else []),
            watch,
        ]
    )
    system = board.system(bind={"llm": backend}, plugins=plugins)
    store = SqliteStore(args.db)

    started = time.monotonic()
    run = await system.run(
        preset.seed(args.topic, cast),
        goal="__never__",  # nothing writes this tag: only rounds or the budget end the run
        budget=args.rounds,
        plugins=plugins,
        store=store,
    )
    elapsed = time.monotonic() - started

    # a SqliteStore snapshot reads through the live connection, so everything the report
    # needs comes off the store before it is closed
    store_view = store.snapshot()
    posts = store_view.query("post")
    casting = _casting(store_view) if args.seats else {}
    store.close()

    # by cast, not by exclusion: with --ranked the preset also wires a feed rule per persona,
    # and those are named after the personas rather than reserved
    voices = set(cast) | {f"seat_{i}" for i in range(args.seats)}

    def spoke(step) -> int:
        return sum(1 for name in step.fired if name in voices)

    swarm_usage = _usage(backend)
    # a node the budget skipped is armed and reported as fired but never reaches Watch, so
    # it is not an invocation for the retry arithmetic
    skipped = limit.skipped if limit else 0
    invocations = sum(len(s.fired) for s in run.steps) - skipped
    report = {
        "model": args.model,
        "personas": args.personas,
        "rounds": len(run.steps),
        "reason": run.reason,
        "active_per_round": [spoke(s) for s in run.steps],
        "personas_fired": sum(spoke(s) for s in run.steps),
        "posts": len(posts),
        **swarm_usage,
        "attempts": watch.attempts,
        "retried": watch.attempts - invocations,
        "raised": dict(watch.failures),
        "failed_nodes": dict(watch.errors),
        "peak_in_flight": watch.peak,
        "seconds": round(elapsed, 1),
        "usd": round(price.of(backend.usage), 6),
        "budget": limit.report() if limit else {},
        "cast": cast,
        "casting": casting,
        "sample": [f"{f.producer}: {f.value}" for f in posts[:3]],
    }
    if composed is not None:
        queen_usage = _usage(queen)
        report["composed"] = {
            "attempts": composed.attempts,
            "fell_back": composed.fell_back,
            "rejected": list(composed.rejected),
            "seconds": round(composing, 1),
            "usd": round(price.of(queen.usage), 6),
            **queen_usage,
        }
    return report


def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="openrouter:qwen/qwen3.7-flash")
    p.add_argument("--personas", type=int, default=10)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--min-active", type=int, default=2)
    p.add_argument("--max-active", type=int, default=4)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=800)
    p.add_argument("--no-reasoning", action="store_true")
    p.add_argument(
        "--compose", action="store_true", help="let a meta-agent write the personas"
    )
    p.add_argument(
        "--batch",
        type=int,
        default=10,
        help="personas per composing call (0 for one call)",
    )
    p.add_argument("--repairs", type=int, default=1, help="retries on a rejected spec")
    p.add_argument(
        "--ranked", action="store_true", help="give each persona its own ranked feed"
    )
    p.add_argument(
        "--seats", type=int, default=0, help="free seats a queen may fill mid-run"
    )
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--topic", default=TOPIC)
    p.add_argument("--db", default=str(Path(__file__).parents[1] / "out" / "swarm.db"))
    p.add_argument(
        "--report", default="", help="where to write the report (default: <db>.json)"
    )
    p.add_argument(
        "--price-in", type=float, default=0.03, help="USD per 1M input tokens"
    )
    p.add_argument("--price-out", type=float, default=0.13, help="USD per 1M output")
    p.add_argument(
        "--usd", type=float, default=0.0, help="stop once the run costs this"
    )
    p.add_argument("--tokens", type=int, default=0, help="stop after this many tokens")
    p.add_argument(
        "--requests", type=int, default=0, help="stop after this many requests"
    )
    return p.parse_args()


if __name__ == "__main__":
    args = cli()
    load_dotenv(Path(__file__).parents[2] / ".env")
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    Path(args.db).unlink(missing_ok=True)
    report = json.dumps(asyncio.run(main(args)), indent=2, ensure_ascii=False)
    Path(args.report or f"{args.db}.json").write_text(report)
    print(report)
