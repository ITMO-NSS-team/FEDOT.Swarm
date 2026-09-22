from __future__ import annotations

import random
from collections.abc import Callable
from typing import Protocol

from fedotmas.engine.contract import Node, View


class Policy(Protocol):
    """Decides which of the armed nodes actually fire this superstep. The default fires all of
    them; an auction fires one winner."""

    def select(self, ready: list[Node], view: View) -> list[Node]: ...


class FireAll:
    """Fire every armed node. The default: full parallelism each superstep."""

    def select(self, ready: list[Node], view: View) -> list[Node]:
        return ready


class AuctionSelect:
    """Fire only the single highest-scoring node, the contract-net selection. `key` is the bid each
    node makes given the store; ties break on iteration order."""

    def __init__(self, key: Callable[[Node, View], float]) -> None:
        self.key = key

    def select(self, ready: list[Node], view: View) -> list[Node]:
        if not ready:
            return []
        return [max(ready, key=lambda n: self.key(n, view))]


class ActivitySample:
    """Throttle a swarm: fire a random subset of the armed nodes instead of all of them,
    the way OASIS decides which agents act this round instead of waking the whole
    population. A node opts in by carrying `activity_level` (0..1) in its Card meta (e.g.
    `Rule(..., meta={"activity_level": 0.4})`); a node without it is infrastructure (a clock,
    a recsys step) and always fires, exempt from both the coin flip and the count cap.

    Each opted-in node is first kept independently with probability `activity_level`, then
    the survivors are capped to a count drawn uniformly from `[min_active, max_active]`
    (`max_active=None` skips the cap, keeping every survivor). `rng` takes a seeded
    `random.Random` for deterministic tests; the module-level generator otherwise."""

    def __init__(
        self,
        min_active: int = 0,
        max_active: int | None = None,
        *,
        rng: random.Random | None = None,
    ) -> None:
        if max_active is not None and min_active > max_active:
            raise ValueError(f"min_active ({min_active}) > max_active ({max_active})")
        self.min_active = min_active
        self.max_active = max_active
        self._rng = rng or random.Random()

    def select(self, ready: list[Node], view: View) -> list[Node]:
        always: list[Node] = []
        gated: list[tuple[Node, float]] = []
        for n in ready:
            level = n.describe().meta.get("activity_level")
            if level is None:
                always.append(n)
            else:
                gated.append((n, level))
        survivors = [n for n, level in gated if self._rng.random() < level]
        if self.max_active is not None and len(survivors) > self.max_active:
            target = self._rng.randint(self.min_active, self.max_active)
            survivors = self._rng.sample(survivors, min(target, len(survivors)))
        return always + survivors
