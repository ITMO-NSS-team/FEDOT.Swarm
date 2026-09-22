"""SqliteStore: the same StoreBackend contract as Store, plus what only a durable backend
needs to prove — data survives closing and reopening the file."""

import os

from fedotmas.engine import Fact, SqliteStore
from fedotmas.engine.contract import matches


def test_clock_is_one_past_the_highest_committed_step():
    store = SqliteStore()
    assert store.next_step() == 0
    store.commit([Fact(tag="a", step=0)])
    assert store.next_step() == 1
    store.commit([Fact(tag="b", step=5)])
    assert store.next_step() == 6
    store.commit([Fact(tag="c", step=2)])
    assert store.next_step() == 6


def test_seeds_at_minus_one_do_not_advance_the_clock():
    store = SqliteStore()
    store.commit([Fact(tag="seed", step=-1)])
    assert store.next_step() == 0


def test_glob_preserves_insertion_order_across_tags():
    store = SqliteStore()
    store.commit(
        [
            Fact(tag="a:1", step=0),
            Fact(tag="b:1", step=0),
            Fact(tag="a:2", step=1),
            Fact(tag="b:2", step=1),
        ]
    )
    view = store.snapshot()
    assert [f.tag for f in view.query("*")] == ["a:1", "b:1", "a:2", "b:2"]
    assert [f.tag for f in view.query("a:*")] == ["a:1", "a:2"]


def test_snapshot_is_isolated_from_later_commits():
    store = SqliteStore()
    store.commit([Fact(tag="a", step=0)])
    view = store.snapshot()
    store.commit([Fact(tag="b", step=1)])
    assert view.exists("a")
    assert not view.exists("b")


def test_patterns_and_latest_wins():
    store = SqliteStore()
    store.commit(
        [
            Fact(tag="draft:1", value="v1", step=0),
            Fact(tag="draft:2", value="v2", step=1),
            Fact(tag="other", step=1),
        ]
    )
    view = store.snapshot()
    assert view.count("draft:*") == 2
    assert [f.tag for f in view.query("draft:1")] == ["draft:1"]
    assert view.value("draft:*") == "v2"
    assert view.get("missing") is None
    assert view.value("missing") is None


def test_snapshot_isolates_versions_of_the_same_tag():
    store = SqliteStore()
    store.commit([Fact(tag="t", value=1, step=0)])
    view = store.snapshot()
    store.commit([Fact(tag="t", value=2, step=1)])
    assert view.count("t") == 1
    assert view.value("t") == 1
    assert store.snapshot().count("t") == 2
    assert store.snapshot().value("t") == 2


def test_every_view_operation_agrees_with_a_linear_scan():
    committed: list[Fact] = []
    store = SqliteStore()
    for k in range(4):
        batch = [
            Fact(tag=f"state:{k}", value=k, step=k),
            Fact(tag="reply", value=k, step=k),
        ]
        committed.extend(batch)
        store.commit(batch)
    view = store.snapshot()
    for pattern in ("state:2", "state:*", "reply", "missing", "missing:*", "*"):
        expected = [f for f in committed if matches(f.tag, pattern)]
        assert [f.key for f in view.query(pattern)] == [f.key for f in expected]
        assert view.exists(pattern) == bool(expected)
        assert view.count(pattern) == len(expected)
        assert view.get(pattern) == (expected[-1] if expected else None)
        assert view.value(pattern) == (expected[-1].value if expected else None)


def test_a_glob_prefix_does_not_leak_into_sql_wildcards():
    store = SqliteStore()
    store.commit([Fact(tag="a_b", step=0), Fact(tag="axb", step=0)])
    view = store.snapshot()
    # "a_b*" must match only tags literally starting with "a_b", not the SQL LIKE wildcard "_"
    assert [f.tag for f in view.query("a_b*")] == ["a_b"]


def test_state_survives_reopening_the_file(tmp_path):
    db_path = str(tmp_path / "swarm.db")
    store = SqliteStore(db_path)
    store.commit([Fact(tag="post", value="hello", producer="agent_0", step=0)])
    store.close()

    reopened = SqliteStore(db_path)
    view = reopened.snapshot()
    assert view.value("post") == "hello"
    fact = view.get("post")
    assert fact is not None
    assert fact.producer == "agent_0"
    # the clock resumes past what was already on disk, not from zero
    assert reopened.next_step() == 1
    reopened.close()

    assert os.path.exists(db_path)
