"""A MiroFish/OASIS-shaped swarm on fedotmas primitives, driven by a stub LLM (no provider key
needed): many persona rules post to a shared feed over a run of rounds, but each round only a
throttled sample of them actually fires (ActivitySample) and only a hard-capped number run
concurrently regardless (ConcurrencyLimit), while the feed persists in a real SQLite file
(SqliteStore) rather than living only in the run's Python objects.

This is the stub half of the plan: it proves the three engine-level pieces compose into the
same shape OASIS uses (bounded activation, bounded concurrency, durable state) without an LLM
provider. Pointing `llm=` at a real backend instead of FakeLLM is the only change needed to run
it for real — left for once a provider key is available.
"""

from __future__ import annotations

import asyncio
import random
import sqlite3
from typing import Any

from fedotmas import Plugin, Rule, blackboard
from fedotmas.engine import ActivitySample, PluginDispatcher, SqliteStore, View
from fedotmas.ext.plugins import ConcurrencyLimit
from fedotmas_llm import Call, PromptRule

N_PERSONAS = 40
ROUNDS = 15
MIN_ACTIVE, MAX_ACTIVE = 3, 8
CONCURRENCY = 3


class StubLLM:
    """The 'заглушка': a deterministic, free, instant stand-in for a real provider. Records
    every call so the test can assert on volume and content without touching a network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def complete(self, call: Call, view: View) -> Any:
        self.calls.append((call.prompt, call.input))
        return f"reacted to round {call.input}"


class InFlightTracker(Plugin):
    """Counts concurrent node invocations to prove ConcurrencyLimit's cap actually holds,
    the way one would watch OASIS's semaphore from the outside."""

    def __init__(self) -> None:
        self.current = 0
        self.peak = 0

    async def before_node(self, node, input, view) -> None:
        self.current += 1
        self.peak = max(self.peak, self.current)

    async def after_node(self, node, result, view) -> None:
        self.current -= 1


def _clock() -> Rule:
    async def tick(v: int) -> int:
        return v + 1

    return Rule(name="clock", fn=tick, reads="tick", writes="tick", when=lambda v: True)


def _personas(n: int, rng: random.Random) -> list[PromptRule]:
    """One rule per persona, each with its own activity_level — the fedotmas analogue of
    OASIS's per-agent active_hours/activity_level on `agents_generator.py`'s profiles."""
    return [
        PromptRule(
            name=f"persona_{i}",
            prompt=f"You are persona {i}. React to the feed in one line.",
            reads="tick",
            writes="post",
            when=lambda v: True,
            meta={"activity_level": rng.uniform(0.2, 1.0)},
        )
        for i in range(n)
    ]


def _persona_counts(steps) -> list[int]:
    return [sum(1 for name in s.fired if name.startswith("persona_")) for s in steps]


async def test_swarm_throttles_activation_and_concurrency_over_a_persisted_feed(
    tmp_path,
):
    db_path = str(tmp_path / "swarm.db")
    stub = StubLLM()
    tracker = InFlightTracker()
    dispatcher = PluginDispatcher([ConcurrencyLimit(CONCURRENCY), tracker])

    board = blackboard(
        _clock(),
        *_personas(N_PERSONAS, random.Random(7)),
        policy=ActivitySample(MIN_ACTIVE, MAX_ACTIVE, rng=random.Random(11)),
    )
    system = board.system(bind={"llm": stub}, plugins=dispatcher)
    store = SqliteStore(db_path)

    run = await system.run(
        {"tick": 0},
        goal="__never__",  # nothing writes this tag: only the round budget ends the run
        budget=ROUNDS,
        plugins=dispatcher,
        store=store,
    )
    store.close()

    # the run went the full distance, one round per superstep
    assert run.reason == "budget"
    assert len(run.steps) == ROUNDS

    counts = _persona_counts(run.steps)
    # every round is capped — never more agents fire than the policy's ceiling, and with 40
    # personas at these activity levels there are always enough survivors to reach the floor
    assert all(MIN_ACTIVE <= c <= MAX_ACTIVE for c in counts)
    # a real reduction in call volume versus firing every persona every round (40 * 15)
    assert sum(counts) < N_PERSONAS * ROUNDS
    # different personas get sampled over time, not the same handful every round
    fired_personas = {
        name for s in run.steps for name in s.fired if name.startswith("persona_")
    }
    assert len(fired_personas) > MAX_ACTIVE

    # the concurrency cap held even though up to MAX_ACTIVE personas were armed at once
    assert tracker.peak <= CONCURRENCY

    # the stub recorded exactly as many calls as personas actually fired
    assert len(stub.calls) == sum(counts)

    # the feed is real, durable state — read it back from a fresh connection to the file,
    # the way an OASIS-style "interview" would query the platform's db mid- or post-run
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT COUNT(*) FROM facts WHERE tag = 'post'").fetchone()
    assert row[0] == sum(counts)
    producers = conn.execute(
        "SELECT DISTINCT producer FROM facts WHERE tag = 'post'"
    ).fetchall()
    assert {p for (p,) in producers} == fired_personas
    conn.close()


async def test_a_plain_fireall_run_would_have_fired_every_persona_every_round():
    """Baseline: without ActivitySample, every armed persona fires every round — the
    contrast that makes the throttled numbers above meaningful."""
    stub = StubLLM()
    board = blackboard(_clock(), *_personas(N_PERSONAS, random.Random(7)))
    run = await board.run(
        {"tick": 0}, goal="__never__", bind={"llm": stub}, budget=ROUNDS
    )
    counts = _persona_counts(run.steps)
    assert counts == [N_PERSONAS] * ROUNDS
    assert len(stub.calls) == N_PERSONAS * ROUNDS


async def test_concurrency_limit_alone_serializes_a_wide_swarm_round():
    """One round, all personas armed (no ActivitySample): ConcurrencyLimit still bounds how
    many stub calls run at once, independent of how many the round wants to fire."""
    tracker = InFlightTracker()
    dispatcher = PluginDispatcher([ConcurrencyLimit(CONCURRENCY), tracker])

    class SlowStub(StubLLM):
        async def complete(self, call: Call, view: View) -> Any:
            await asyncio.sleep(0.005)
            return await super().complete(call, view)

    slow = SlowStub()
    board = blackboard(*_personas(N_PERSONAS, random.Random(3)))
    system = board.system(bind={"llm": slow}, plugins=dispatcher)
    await system.run({"tick": 0}, goal="post", budget=1, plugins=dispatcher)

    assert len(slow.calls) == N_PERSONAS
    assert tracker.peak <= CONCURRENCY
