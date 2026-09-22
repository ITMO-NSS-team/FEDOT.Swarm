from __future__ import annotations

import asyncio
import traceback
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any, NamedTuple

from fedotmas.engine.contract import (
    ERROR_CHANNEL,
    Fact,
    Key,
    Node,
    Status,
    View,
    patterns,
)
from fedotmas.engine.outcome import RunError
from fedotmas.engine.plugin import Plugin, PluginDispatcher
from fedotmas.engine.policy import FireAll
from fedotmas.engine.report import Run, StepReport
from fedotmas.engine.store import StoreBackend
from fedotmas.engine.system import System
from fedotmas.engine.terminate import Terminate


def _stamp(facts: Iterable[Fact], producer: str, step: int) -> list[Fact]:
    return [f.model_copy(update={"producer": producer, "step": step}) for f in facts]


def _seed(facts: Iterable[Fact], step: int) -> list[Fact]:
    """Default-stamp seed facts, keeping anything set explicitly. An unset step lands just
    before the store clock: on a fresh store that is the classic -1, on a re-run it is a
    fresh key instead of a collision with the previous run's seeds."""
    return [
        f.model_copy(
            update={
                "producer": f.producer or "seed",
                "step": f.step if f.step != -1 else step,
            }
        )
        for f in facts
    ]


def _matched(view: View, reads: str) -> list[Fact]:
    return [f for pattern in patterns(reads) for f in view.query(pattern)]


class _Armed(NamedTuple):
    node: Node
    input: list[Fact]
    key: frozenset[Key]


def _ready(
    system: System, view: View, last_input: dict[str, frozenset[Key]]
) -> list[_Armed]:
    """Nodes whose trigger holds and whose matched input differs from the one they last fired
    on. The store is append-only, so a node's matched set only ever grows; remembering the
    last set per node is enough to fire exactly once per distinct input."""
    armed = []
    for node in system.nodes:
        if not node.trigger(view):
            continue
        facts = _matched(view, node.reads) if node.reads else []
        key = frozenset(f.key for f in facts)
        if last_input.get(node.name) == key:
            continue
        armed.append(_Armed(node, facts, key))
    return armed


def _error_fact(name: str, message: str, step: int, exc: Exception | None) -> Fact:
    """The uniform error record: meta always carries `type`, `traceback` and `causes`. A
    RunError (a failed inner run) adds `reason` and dumps its facts into causes — each dump
    nests its own, so a deep failure arrives as a tree, not a flattened string."""
    meta: dict[str, Any] = {"type": None, "traceback": None, "causes": []}
    if exc is not None:
        meta["type"] = type(exc).__name__
        meta["traceback"] = "".join(traceback.format_exception(exc))
    if isinstance(exc, RunError):
        meta["reason"] = exc.reason
        meta["causes"] = [e.model_dump() for e in exc.errors]
    return Fact(
        tag=ERROR_CHANNEL + name, value=message, producer=name, step=step, meta=meta
    )


class ReactiveExecutor:
    """The superstep loop. The selection policy and the error discipline come from the system
    itself (`system.policy`, `system.halt_on_error`), so they hold wherever it runs —
    top-level or inside nest/loop. `plugins` accepts the raw list or an already-bound
    PluginDispatcher; `after_run` fires when a run completes — for `stream`, that is the
    natural end of the iteration, so an abandoned stream fires no end hook."""

    async def stream(
        self,
        system: System,
        store: StoreBackend,
        *,
        seed: Iterable[Fact] = (),
        terminate: Sequence[Terminate] = (),
        plugins: Sequence[Plugin] | PluginDispatcher = (),
    ) -> AsyncIterator[StepReport]:
        dispatcher = PluginDispatcher.of(plugins)
        steps: list[StepReport] = []
        async for report in self._steps(system, store, seed, terminate, dispatcher):
            steps.append(report)
            yield report
        await dispatcher.after_run(
            self._finish(
                steps, store, dispatcher.scope, system.halt_on_error, terminate
            )
        )

    async def run(
        self,
        system: System,
        store: StoreBackend,
        *,
        seed: Iterable[Fact] = (),
        terminate: Sequence[Terminate] = (),
        plugins: Sequence[Plugin] | PluginDispatcher = (),
    ) -> Run:
        dispatcher = PluginDispatcher.of(plugins)
        steps = [
            report
            async for report in self._steps(system, store, seed, terminate, dispatcher)
        ]
        run = self._finish(
            steps, store, dispatcher.scope, system.halt_on_error, terminate
        )
        await dispatcher.after_run(run)
        return run

    async def _steps(
        self,
        system: System,
        store: StoreBackend,
        seed: Iterable[Fact],
        terminate: Sequence[Terminate],
        dispatcher: PluginDispatcher,
    ) -> AsyncIterator[StepReport]:
        active = system.policy or FireAll()
        scope = dispatcher.scope
        store.commit(_seed(seed, store.next_step() - 1))
        await dispatcher.before_run(system, store.snapshot())
        last_input: dict[str, frozenset[Key]] = {}
        index = 0
        while True:
            view = store.snapshot()
            step = store.next_step()
            armed = _ready(system, view, last_input)
            chosen = {n.name for n in active.select([a.node for a in armed], view)}
            armed = [a for a in armed if a.node.name in chosen]
            if not armed:
                report = StepReport(step, index, [], [], view=view, scope=scope)
                await dispatcher.after_step(report)
                yield report
                return
            results = await asyncio.gather(
                *(dispatcher.invoke(a.node, a.input, view) for a in armed),
                return_exceptions=True,
            )
            writes: list[Fact] = []
            errors: list[Fact] = []
            for a, result in zip(armed, results):
                last_input[a.node.name] = a.key
                if isinstance(result, BaseException):
                    if not isinstance(result, Exception):
                        raise result
                    error = _error_fact(a.node.name, str(result), step, result)
                    await dispatcher.on_error(a.node, error, view)
                    errors.append(error)
                    continue
                if result.status is Status.ERROR:
                    error = _error_fact(a.node.name, result.error or "", step, None)
                    await dispatcher.on_error(a.node, error, view)
                    errors.append(error)
                writes.extend(_stamp(result.writes, a.node.name, step))
            store.commit([*writes, *errors])
            post = store.snapshot()
            report = StepReport(
                step,
                index,
                [a.node.name for a in armed],
                writes,
                view=post,
                errors=errors,
                scope=scope,
            )
            await dispatcher.after_step(report)
            yield report
            if errors and system.halt_on_error:
                return
            if any(t.done(post, report) for t in terminate):
                return
            index += 1

    def _finish(
        self,
        steps: list[StepReport],
        store: StoreBackend,
        scope: tuple[str, ...],
        halt: bool,
        terminate: Sequence[Terminate],
    ) -> Run:
        """Name how the run ended. "error" and "quiescence" are the engine's own outcomes
        (halted on a failure / nothing armed); otherwise the run ended on a terminate
        condition, and re-consulting the list on the final report names the first one that
        holds — Run.reason is its lowercased class name ("goal", "budget", ...)."""
        status = Status.ERROR if any(s.errors for s in steps) else Status.OK
        last = steps[-1]
        if halt and last.errors:
            reason = "error"
        elif not last.fired:
            reason = "quiescence"
        else:
            hit = next(t for t in terminate if t.done(last.view, last))
            reason = type(hit).__name__.lower()
        return Run(status, steps, store.snapshot(), reason, scope)
