from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from fedotmas.engine.contract import Result
from fedotmas.engine.plugin import Plugin

from fedotmas_llm._llm import Usage

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fedotmas.engine.contract import Fact, Node, View

    NodeCall = Callable[[list[Fact], View], Awaitable[Result]]


class Meter(Protocol):
    """A backend that reports what it has spent so far. The `PydanticAI` adapter is one; a
    stub that counts its own calls is another."""

    @property
    def usage(self) -> Usage: ...


@dataclass(frozen=True)
class Price:
    """Catalog price in USD per million tokens, the unit providers quote. Reasoning is billed
    inside output tokens, so a model that thinks before answering is priced here as output."""

    input: float = 0.0
    output: float = 0.0

    def of(self, usage: Usage) -> float:
        return (
            usage.input_tokens * self.input + usage.output_tokens * self.output
        ) / 1e6


class SpendLimit(Plugin):
    """Cap what a run may spend, in tokens, requests, or USD at `price`. Past the cap no node
    is called: the plugin returns an empty result instead, so nothing new is written, nothing
    re-arms, and the run ends on quiescence with its store intact rather than on a pile of
    errors. Nodes are black boxes to the engine, so a spent budget stops the code rules too;
    the cap is on the run, not on the provider.

    Counts from the moment it is built, so composing a system before the run does not eat the
    run's budget. The check happens before each call, which means in-flight calls can still
    land: overshoot is bounded by how many run at once (see `ConcurrencyLimit`).
    """

    def __init__(
        self,
        *meters: Meter,
        tokens: int | None = None,
        requests: int | None = None,
        usd: float | None = None,
        price: Price | None = None,
    ) -> None:
        if not meters:
            raise ValueError("SpendLimit needs at least one meter to read")
        if tokens is None and requests is None and usd is None:
            raise ValueError("SpendLimit needs a cap: tokens=, requests= or usd=")
        if usd is not None and price is None:
            raise ValueError("SpendLimit needs price= to convert tokens to usd=")
        self.tokens = tokens
        self.requests = requests
        self.usd = usd
        self.price = price or Price()
        self.skipped = 0
        self._meters = meters
        self._base = self._total()

    def _total(self) -> Usage:
        total = Usage()
        for meter in self._meters:
            total += meter.usage
        return total

    @property
    def spent(self) -> Usage:
        """What the meters have run up since this limit was built."""
        return self._total() - self._base

    @property
    def stopped(self) -> bool:
        return self.skipped > 0

    def over(self) -> bool:
        spent = self.spent
        if self.tokens is not None and spent.total >= self.tokens:
            return True
        if self.requests is not None and spent.requests >= self.requests:
            return True
        return self.usd is not None and self.price.of(spent) >= self.usd

    def report(self) -> dict[str, Any]:
        spent = self.spent
        return {
            "input_tokens": spent.input_tokens,
            "output_tokens": spent.output_tokens,
            "requests": spent.requests,
            "usd": self.price.of(spent),
            "skipped": self.skipped,
            "stopped": self.stopped,
        }

    async def around_node(
        self, node: Node, input: list[Fact], view: View, call: NodeCall
    ) -> Result:
        if self.over():
            self.skipped += 1
            return Result()
        return await call(input, view)
