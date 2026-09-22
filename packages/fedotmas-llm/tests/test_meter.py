"""A run that stops when its money runs out. The budget is read off the backend's own meter,
so nothing in the engine knows what a token is; what it knows is that past the cap a node is
not called and the board goes quiet.
"""

from __future__ import annotations

from typing import Any

import pytest
from fedotmas import Rule, blackboard
from fedotmas.engine import PluginDispatcher, Store, View
from fedotmas.ext.plugins import ConcurrencyLimit
from fedotmas_llm import Call, Price, PromptRule, SpendLimit, Usage

PER_CALL = Usage(input_tokens=100, output_tokens=20, requests=1)


class MeteredStub:
    """A provider-shaped stub: answers instantly, for free, and bills a fixed amount per call
    the way a real backend accumulates on its shared RunUsage."""

    def __init__(self, per_call: Usage = PER_CALL) -> None:
        self.per_call = per_call
        self.usage = Usage()
        self.calls = 0

    async def complete(self, call: Call, view: View) -> Any:
        self.calls += 1
        self.usage += self.per_call
        return f"post {self.calls}"


def _clock() -> Rule:
    async def tick(v: int) -> int:
        return v + 1

    return Rule(name="clock", fn=tick, reads="tick", writes="tick", when=lambda v: True)


def _board(n: int = 3):
    personas = [
        PromptRule(
            name=f"persona_{i}",
            prompt=f"You are persona {i}.",
            input="round {input}",
            reads="tick",
            writes="post",
            when=lambda v: True,
        )
        for i in range(n)
    ]
    return blackboard(_clock(), *personas)


async def _run(limit: SpendLimit, llm: MeteredStub, *, rounds: int = 10, n: int = 3):
    plugins = PluginDispatcher([ConcurrencyLimit(1), limit])
    system = _board(n).system(bind={"llm": llm}, plugins=plugins)
    return await system.run(
        {"tick": 0}, goal="__never__", budget=rounds, plugins=plugins
    )


def test_price_is_per_million_tokens():
    price = Price(input=0.03, output=0.13)
    assert price.of(Usage(1_000_000, 1_000_000, 2)) == pytest.approx(0.16)
    assert price.of(Usage()) == 0.0


def test_usage_subtracts_to_one_meters_own_share():
    assert Usage(10, 4, 1) + Usage(5, 2, 1) - Usage(10, 4, 1) == Usage(5, 2, 1)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "at least one meter"),
        ({"meters": True}, "needs a cap"),
        ({"meters": True, "usd": 1.0}, "needs price="),
    ],
)
def test_a_limit_that_could_never_hold_is_refused(kwargs, message):
    meters = (MeteredStub(),) if kwargs.pop("meters", False) else ()
    with pytest.raises(ValueError, match=message):
        SpendLimit(*meters, **kwargs)


async def test_a_run_out_of_requests_stops_calling_the_provider():
    llm = MeteredStub()
    limit = SpendLimit(llm, requests=5)
    run = await _run(limit, llm)

    assert llm.calls == 5, "the cap is checked before the call, not after"
    assert limit.stopped
    # quiescence read through an Outcome whose goal was never written
    assert run.reason == "stalled", "nothing new is written, so nothing re-arms"
    assert run.errors == [], "a spent budget is not an error"


async def test_a_run_out_of_tokens_keeps_what_it_already_wrote():
    llm = MeteredStub()
    limit = SpendLimit(llm, tokens=500)
    run = await _run(limit, llm)

    assert (
        llm.calls == 5
    )  # 120 tokens a call, so the fifth lands at 600 and the sixth is cut
    assert run.view.count("post") == 5
    assert limit.spent == Usage(500, 100, 5)


async def test_a_run_out_of_money_stops_where_the_price_says():
    llm = MeteredStub()
    price = Price(input=0.03, output=0.13)
    limit = SpendLimit(llm, usd=price.of(PER_CALL) * 4, price=price)
    await _run(limit, llm)

    assert llm.calls == 4
    assert limit.report()["usd"] == pytest.approx(price.of(PER_CALL) * 4)


async def test_the_budget_covers_the_run_and_not_what_was_spent_before_it():
    llm = MeteredStub()
    await llm.complete(Call("composing the cast", "x"), Store().snapshot())
    limit = SpendLimit(llm, requests=3)
    await _run(limit, llm)

    assert llm.calls == 4, "one call composing, three inside the run"
    assert limit.spent.requests == 3


async def test_several_backends_share_one_budget():
    one, two = MeteredStub(), MeteredStub()
    limit = SpendLimit(one, two, requests=4)
    plugins = PluginDispatcher([ConcurrencyLimit(1), limit])
    board = blackboard(
        _clock(),
        PromptRule(
            name="a",
            prompt="a",
            reads="tick",
            writes="post",
            when=lambda v: True,
            llm=one,
        ),
        PromptRule(
            name="b",
            prompt="b",
            reads="tick",
            writes="post",
            when=lambda v: True,
            llm=two,
        ),
    )
    await board.system(plugins=plugins).run(
        {"tick": 0}, goal="__never__", budget=10, plugins=plugins
    )

    assert one.calls + two.calls == 4
    assert limit.spent.requests == 4


async def test_an_unspent_budget_leaves_the_run_alone():
    llm = MeteredStub()
    limit = SpendLimit(llm, requests=1000)
    run = await _run(limit, llm, rounds=3)

    assert run.reason == "budget"
    assert limit.skipped == 0
    assert not limit.stopped
    assert llm.calls == 9


async def test_the_cap_stops_code_rules_too():
    """Nodes are black boxes, so a spent budget cannot skip only the ones that cost money."""
    llm = MeteredStub()
    limit = SpendLimit(llm, requests=2)
    run = await _run(limit, llm, rounds=10, n=1)

    ticks = [s for s in run.steps if "clock" in s.fired]
    assert run.view.value("tick") == 2, (
        f"the clock stopped with the rest, {len(ticks)} steps"
    )


async def test_a_swarm_keeps_spending_bounded_under_concurrency():
    """With calls in flight the check can be passed by several at once, so the cap is a floor
    on what is spent and the overshoot is bounded by the concurrency limit."""
    llm = MeteredStub()
    limit = SpendLimit(llm, requests=10)
    plugins = PluginDispatcher([ConcurrencyLimit(4), limit])
    system = _board(8).system(bind={"llm": llm}, plugins=plugins)
    await system.run({"tick": 0}, goal="__never__", budget=20, plugins=plugins)

    assert 10 <= llm.calls <= 10 + 4


def test_a_limit_reports_what_it_spent_and_what_it_refused():
    llm = MeteredStub()
    limit = SpendLimit(llm, requests=1, price=Price(input=0.03, output=0.13))
    llm.usage += Usage(1000, 500, 2)

    assert limit.report() == {
        "input_tokens": 1000,
        "output_tokens": 500,
        "requests": 2,
        "usd": pytest.approx(9.5e-05),
        "skipped": 0,
        "stopped": False,
    }
