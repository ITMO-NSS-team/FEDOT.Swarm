from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from fedotmas.engine.contract import Fact, View


class Snapshot:
    """A read-only View over the facts as of one moment: the shared append-only log, the
    shared tag index and a cutoff, so taking one copies nothing. Patterns are the contract's
    tag language (see contract.matches); get/value return the latest match in insertion
    order."""

    def __init__(
        self, facts: list[Fact], index: dict[str, list[int]], upto: int
    ) -> None:
        self._facts = facts
        self._index = index
        self._upto = upto

    def _hits(self, pattern: str) -> list[int]:
        """Matching log positions below the cutoff, in insertion order."""
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            hits = [
                p
                for tag, positions in self._index.items()
                if tag.startswith(prefix)
                for p in positions[: bisect_left(positions, self._upto)]
            ]
            hits.sort()
            return hits
        positions = self._index.get(pattern, [])
        return positions[: bisect_left(positions, self._upto)]

    def query(self, pattern: str) -> list[Fact]:
        return [self._facts[p] for p in self._hits(pattern)]

    def get(self, tag: str) -> Fact | None:
        hits = self._hits(tag)
        return self._facts[hits[-1]] if hits else None

    def value(self, tag: str) -> Any:
        f = self.get(tag)
        return f.value if f else None

    def exists(self, pattern: str) -> bool:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return any(
                tag.startswith(prefix) and positions[0] < self._upto
                for tag, positions in self._index.items()
            )
        positions = self._index.get(pattern)
        return bool(positions) and positions[0] < self._upto

    def count(self, pattern: str) -> int:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return sum(
                bisect_left(positions, self._upto)
                for tag, positions in self._index.items()
                if tag.startswith(prefix)
            )
        positions = self._index.get(pattern, [])
        return bisect_left(positions, self._upto)


@runtime_checkable
class StoreBackend(Protocol):
    """What the executor needs from a store: commit facts, read the clock, take a snapshot.
    `Store` is the default in-memory backend; a durable one (e.g. `SqliteStore`) satisfies the
    same three methods and drops into `System.run(..., store=...)` unchanged."""

    def commit(self, facts: Iterable[Fact]) -> None: ...
    def next_step(self) -> int: ...
    def snapshot(self) -> View: ...


class Store:
    """The blackboard: an append-only log of facts plus a monotonic step clock. Writes are
    never overwritten and the log is never truncated: a tag keeps every version, the clock
    only moves forward, and a snapshot is just a cutoff into the log — the executor's
    fire-once-per-distinct-input and snapshot isolation both stand on this invariant.
    Reads go through `snapshot` and resolve via the per-tag index of log positions."""

    def __init__(self) -> None:
        self._facts: list[Fact] = []
        self._index: dict[str, list[int]] = {}
        self._clock = 0

    def commit(self, facts: Iterable[Fact]) -> None:
        for f in facts:
            self._index.setdefault(f.tag, []).append(len(self._facts))
            self._facts.append(f)
            if f.step >= self._clock:
                self._clock = f.step + 1

    def next_step(self) -> int:
        return self._clock

    def snapshot(self) -> View:
        return Snapshot(self._facts, self._index, len(self._facts))
