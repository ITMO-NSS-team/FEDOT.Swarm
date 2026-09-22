"""Plugin hooks: bind validation, step accounting, observers-vs-interceptors across nested
runs, and the run-end symmetry between .run and .stream."""

import asyncio

import pytest
from fedotmas import Plugin, Rule, action, blackboard, nest
from fedotmas.engine import (
    Fact,
    PluginDispatcher,
    PluginError,
    ReactiveExecutor,
    Result,
    Store,
    System,
    as_node,
    register_event,
)
from fedotmas.ext.plugins import ConcurrencyLimit, Retry


async def double(x):
    return x * 2


class Meter(Plugin):
    def __init__(self):
        self.steps = 0

    async def after_step(self, report):
        self.steps += 1


def test_a_data_field_with_a_reserved_prefix_is_not_a_hook():
    class P(Plugin):
        def __init__(self):
            self.on_conflict = "skip"
            self.before_total = 3

        async def after_step(self, report): ...

    PluginDispatcher([P()])


def test_a_sync_hook_method_fails_at_bind():
    class P(Plugin):
        def after_step(self, report): ...  # type: ignore[override]

    with pytest.raises(PluginError, match="async"):
        PluginDispatcher([P()])


def test_a_non_callable_hook_override_fails_at_bind():
    class P(Plugin):
        after_node = None  # type: ignore[assignment]

    with pytest.raises(PluginError):
        PluginDispatcher([P()])


def test_a_hook_typo_fails_at_bind_with_a_near_match():
    class P(Plugin):
        async def after_stpe(self, report): ...

    with pytest.raises(PluginError, match="after_step"):
        PluginDispatcher([P()])


def test_a_wrong_phase_fails_at_bind():
    class P(Plugin):
        async def before_step(self, report): ...

    with pytest.raises(PluginError, match="before"):
        PluginDispatcher([P()])


def test_a_plain_object_is_not_a_plugin():
    class P:
        async def after_step(self, report): ...

    with pytest.raises(PluginError, match="subclass"):
        PluginDispatcher([P()])  # ty: ignore[invalid-argument-type]


def test_a_duplicate_event_registration_fails():
    with pytest.raises(PluginError, match="registered"):
        register_event("error")


async def test_an_instance_attribute_override_binds():
    seen = []

    class P(Plugin):
        def __init__(self):
            async def before_node(node, input, view):
                seen.append(node.name)

            self.before_node = before_node  # ty: ignore[invalid-assignment]

    await action(double).run(1, plugins=[P()])
    assert seen


async def test_after_step_fires_on_the_quiescence_step():
    async def fn(input, view):
        return Result(writes=[Fact(tag="out", value=1)])

    meter = Meter()
    system = System([as_node(fn, name="n", reads="in")])
    run = await ReactiveExecutor().run(
        system, Store(), seed=[Fact(tag="in", value=1)], plugins=[meter]
    )
    assert run.reason == "quiescence"
    assert meter.steps == len(run.steps)


async def test_after_run_fires_for_run_and_for_a_consumed_stream():
    class Ends(Plugin):
        def __init__(self):
            self.runs = []

        async def after_run(self, run):
            self.runs.append(run.reason)

    ends = Ends()
    flow = action(double)
    await flow.run(1, plugins=[ends])
    async for _ in flow.stream(1, plugins=[ends]):
        pass
    assert len(ends.runs) == 2


async def test_on_error_receives_the_error_fact():
    seen = []

    class Alarm(Plugin):
        async def on_error(self, node, error, view):
            seen.append(error)

    async def boom(x):
        raise ValueError("boom")

    outcome = await action(boom).run(1, plugins=[Alarm()])
    assert not outcome.ok
    assert seen and seen[0].tag.startswith("error:")
    assert seen[0].meta["type"] == "ValueError"


async def test_a_custom_event_binds_and_emits():
    register_event("probe")
    seen = []

    class P(Plugin):
        async def on_probe(self, payload):
            seen.append(payload)

    await PluginDispatcher([P()]).emit("probe", 42)
    assert seen == [42]


async def test_a_bare_system_runs_with_plugins():
    meter = Meter()
    outcome = (
        await action(double)
        .system(entry="in", out="out")
        .run({"in": 2}, plugins=[meter])
    )
    assert outcome.value == 4
    assert meter.steps == len(outcome.steps)


async def test_an_interceptor_does_not_cross_into_a_nested_run():
    wrapped = []

    class Count(Plugin):
        async def around_node(self, node, input, view, call):
            wrapped.append(node.name)
            return await call(input, view)

    inner = blackboard(Rule("inner", double, reads="seed", writes="out"))
    flow = action(double) + nest(inner, entry="seed", out="out")
    outcome = await flow.run(2, plugins=[Count()])
    assert outcome.value == 8
    assert wrapped and "inner" not in wrapped


async def test_retry_attempts_do_not_multiply_through_nest():
    calls = {"n": 0}

    async def boom(x):
        calls["n"] += 1
        raise RuntimeError("boom")

    inner = blackboard(Rule("b", boom, reads="seed", writes="out"))
    outcome = await nest(inner, entry="seed", out="out").run(1, plugins=[Retry(2)])
    assert not outcome.ok
    assert calls["n"] == 2


def test_retry_needs_at_least_one_attempt():
    with pytest.raises(ValueError, match="times >= 1"):
        Retry(0)


async def test_concurrency_limit_bounds_how_many_calls_run_at_once():
    current = {"n": 0, "peak": 0}

    async def slow(x, view):
        current["n"] += 1
        current["peak"] = max(current["peak"], current["n"])
        await asyncio.sleep(0.01)
        current["n"] -= 1
        return Result(writes=[])

    nodes = [as_node(slow, name=f"n{i}", reads="in") for i in range(10)]
    system = System(nodes)
    await ReactiveExecutor().run(
        system, Store(), seed=[Fact(tag="in", value=1)], plugins=[ConcurrencyLimit(3)]
    )
    assert current["peak"] <= 3


async def test_concurrency_limit_of_one_serializes_calls():
    order = []

    def make_record(i):
        async def record(input, view):
            order.append(("start", i))
            await asyncio.sleep(0.01)
            order.append(("end", i))
            return Result(writes=[])

        return record

    nodes = [as_node(make_record(i), name=f"n{i}", reads="in") for i in range(3)]
    system = System(nodes)
    await ReactiveExecutor().run(
        system, Store(), seed=[Fact(tag="in", value=1)], plugins=[ConcurrencyLimit(1)]
    )
    # a limit of 1 never lets a second call start before the first ends
    starts_and_ends = [kind for kind, _ in order]
    assert starts_and_ends == ["start", "end"] * 3


def test_concurrency_limit_needs_at_least_one_slot():
    with pytest.raises(ValueError, match="n >= 1"):
        ConcurrencyLimit(0)


async def test_retry_on_narrows_what_is_retried():
    calls = {"n": 0}

    async def boom(x):
        calls["n"] += 1
        raise ValueError("not a timeout")

    outcome = await action(boom).run(1, plugins=[Retry(3, on=TimeoutError)])
    assert not outcome.ok
    assert calls["n"] == 1


async def test_observer_hooks_follow_the_nested_run():
    scopes = []

    class Scoped(Plugin):
        async def before_run(self, system, view, scope):
            scopes.append(scope)

    meter = Meter()
    inner = blackboard(Rule("inner", double, reads="seed", writes="out"))
    flow = action(double) + nest(inner, entry="seed", out="out")
    outcome = await flow.run(2, plugins=[Scoped(), meter])
    assert () in scopes and any(s for s in scopes)
    assert meter.steps > len(outcome.steps)
