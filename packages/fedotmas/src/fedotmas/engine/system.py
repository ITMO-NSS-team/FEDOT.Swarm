from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Any, Protocol

from fedotmas.engine.contract import Fact, Node
from fedotmas.engine.outcome import Outcome
from fedotmas.engine.terminate import Budget, Goal, Terminate

if TYPE_CHECKING:
    from fedotmas.engine.plugin import Plugin, PluginDispatcher
    from fedotmas.engine.policy import Policy
    from fedotmas.engine.report import StepReport
    from fedotmas.engine.store import StoreBackend


@dataclass
class System:
    """The compiled unit the engine runs: a flat list of nodes over one store, plus the run
    discipline that is part of what the system is. `policy` arbitrates which armed nodes fire
    each superstep (None fires all, AuctionSelect holds a contract-net); `halt_on_error` is
    the error discipline (True ends the run at the first failed node, False records the error
    and keeps going). Both travel with the system — into nest/loop and through the blueprint
    round-trip — while what belongs to one invocation is declared per run instead: `goal`,
    `budget` and `plugins` on run/stream, the inner budget on the nest/loop boundary.

    `run` executes to a goal fact and reads that fact back as an Outcome; `stream` is the
    same run yielded step by step. Flow.run and Board.run compile and delegate here, and a
    System from from_blueprint or nest runs the same way. Plugins passed at run time observe
    and intercept this system's own supersteps; reaching inside nested sub-systems requires
    baking them at compile (Flow.system and the run surfaces do this)."""

    nodes: list[Node]
    _: KW_ONLY
    policy: Policy | None = None
    halt_on_error: bool = True

    def __post_init__(self) -> None:
        names = [n.name for n in self.nodes]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate node names: {dupes}")

    def _setup(
        self,
        seed: Mapping[str, Any],
        goal: str,
        budget: int | None,
        plugins: Sequence[Plugin] | PluginDispatcher,
    ) -> tuple[Any, list[Fact], list[Terminate], PluginDispatcher]:
        # Imported here: executor imports System at module level.
        from fedotmas.engine.executor import ReactiveExecutor
        from fedotmas.engine.plugin import PluginDispatcher

        terminate: list[Terminate] = [Goal(goal)]
        if budget is not None:
            terminate.append(Budget(budget))
        facts = [Fact(tag=tag, value=value) for tag, value in seed.items()]
        return ReactiveExecutor(), facts, terminate, PluginDispatcher.of(plugins)

    async def run(
        self,
        seed: Mapping[str, Any],
        *,
        goal: str = "out",
        budget: int | None = 100,
        plugins: Sequence[Plugin] | PluginDispatcher = (),
        store: StoreBackend | None = None,
    ) -> Outcome:
        """Execute on a fresh store and read the goal fact back as an Outcome. `seed` is a
        tag -> value map written as the initial facts; `goal` is the tag read back; `budget`
        caps the supersteps (the default 100 is a runaway guard, None lifts it). The
        selection policy and the error discipline are the system's own fields, not run
        arguments. `store` swaps the backend (e.g. a durable `SqliteStore`); default is a
        fresh in-memory `Store`."""
        from fedotmas.engine.store import Store

        executor, facts, terminate, dispatcher = self._setup(
            seed, goal, budget, plugins
        )
        run = await executor.run(
            self,
            store or Store(),
            seed=facts,
            terminate=terminate,
            plugins=dispatcher,
        )
        return Outcome(run, goal)

    async def stream(
        self,
        seed: Mapping[str, Any],
        *,
        goal: str = "out",
        budget: int | None = 100,
        plugins: Sequence[Plugin] | PluginDispatcher = (),
        store: StoreBackend | None = None,
    ) -> AsyncIterator[StepReport]:
        """The streaming form of .run: yields each StepReport as the run unfolds. `store`
        swaps the backend, as on .run."""
        from fedotmas.engine.store import Store

        executor, facts, terminate, dispatcher = self._setup(
            seed, goal, budget, plugins
        )
        async for report in executor.stream(
            self,
            store or Store(),
            seed=facts,
            terminate=terminate,
            plugins=dispatcher,
        ):
            yield report


class Compilable(Protocol):
    """The one contract a container satisfies to enter composition: render yourself as a
    System. nest() and Rule(nest=) accept any object with this method — a Flow, a Board, a
    third-party container — so new container kinds plug in without the core switching on
    classes. `entry`/`out` are the boundary tags: a container with no addressing of its own
    (a flow) compiles to them, one whose tags are fixed (a board) reads them as references.
    `bind` is the run-scoped binding map; `plugins` is the dispatcher whose nested faces are
    baked into interior boundaries at compile."""

    def system(
        self,
        *,
        entry: str = "in",
        out: str = "out",
        bind: Mapping[str, Any] | None = None,
        plugins: Sequence[Plugin] | PluginDispatcher = (),
    ) -> System: ...
