from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import Any

from fedotmas.engine.contract import Fact, View

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    rowid_ INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL,
    value_json TEXT NOT NULL,
    producer TEXT NOT NULL,
    step INTEGER NOT NULL,
    meta_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS facts_tag ON facts (tag);
"""


def _row_to_fact(row: tuple[Any, ...]) -> Fact:
    _, tag, value_json, producer, step, meta_json = row
    return Fact(
        tag=tag,
        value=json.loads(value_json),
        producer=producer,
        step=step,
        meta=json.loads(meta_json),
    )


class SqliteSnapshot:
    """A read-only View over `facts` as of one rowid cutoff. Mirrors `store.Snapshot`'s
    semantics (a plain tag matches exactly, `prefix*` matches by LIKE) over SQL instead of an
    in-memory index. Duck-types `View` like `store.Snapshot` does — no base class needed."""

    def __init__(self, conn: sqlite3.Connection, upto: int) -> None:
        self._conn = conn
        self._upto = upto

    def _where(self, pattern: str) -> tuple[str, tuple[Any, ...]]:
        if pattern.endswith("*"):
            prefix = pattern[:-1].replace("%", r"\%").replace("_", r"\_")
            return "tag LIKE ? ESCAPE '\\' AND rowid_ < ?", (f"{prefix}%", self._upto)
        return "tag = ? AND rowid_ < ?", (pattern, self._upto)

    def query(self, pattern: str) -> list[Fact]:
        clause, params = self._where(pattern)
        rows = self._conn.execute(
            f"SELECT * FROM facts WHERE {clause} ORDER BY rowid_", params
        ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def get(self, tag: str) -> Fact | None:
        clause, params = self._where(tag)
        row = self._conn.execute(
            f"SELECT * FROM facts WHERE {clause} ORDER BY rowid_ DESC LIMIT 1", params
        ).fetchone()
        return _row_to_fact(row) if row else None

    def value(self, tag: str) -> Any:
        f = self.get(tag)
        return f.value if f else None

    def exists(self, pattern: str) -> bool:
        clause, params = self._where(pattern)
        row = self._conn.execute(
            f"SELECT 1 FROM facts WHERE {clause} LIMIT 1", params
        ).fetchone()
        return row is not None

    def count(self, pattern: str) -> int:
        clause, params = self._where(pattern)
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM facts WHERE {clause}", params
        ).fetchone()
        return row[0]


class SqliteStore:
    """A durable `StoreBackend`: the same append-only, every-version-kept log as `Store`, but
    persisted to a SQLite file instead of a Python list, so state survives the process and a
    long run does not grow unbounded in RAM. Writes commit as one batch (`executemany`) per
    superstep, and `journal_mode=WAL` lets another connection read the file while a run is in
    progress — the same shape as OASIS's Platform: one writer, readable mid-run.

    `db_path` defaults to `:memory:` (a SQLite in-memory DB — useful for tests that want the
    real SQL code path without a file); pass a path to persist across processes."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()
        row = self._conn.execute("SELECT MAX(step) FROM facts").fetchone()
        self._clock = (row[0] + 1) if row[0] is not None else 0

    def commit(self, facts: Iterable[Fact]) -> None:
        rows = [
            (f.tag, json.dumps(f.value), f.producer, f.step, json.dumps(f.meta))
            for f in facts
        ]
        if not rows:
            return
        self._conn.executemany(
            "INSERT INTO facts (tag, value_json, producer, step, meta_json) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        self._clock = max(self._clock, *(step + 1 for _, _, _, step, _ in rows))

    def next_step(self) -> int:
        return self._clock

    def snapshot(self) -> View:
        last = self._conn.execute("SELECT MAX(rowid_) FROM facts").fetchone()[0] or 0
        return SqliteSnapshot(self._conn, last + 1)

    def close(self) -> None:
        self._conn.close()
