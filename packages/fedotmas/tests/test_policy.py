"""ActivitySample: gate armed nodes by an opt-in activity_level, cap the survivor count, and
leave anything without an activity_level alone."""

import random

import pytest
from fedotmas import Rule
from fedotmas.engine import ActivitySample, Node, Store


def _rule(name: str, activity_level: float | None = None) -> Node:
    async def fn(x):
        return x

    meta = {} if activity_level is None else {"activity_level": activity_level}
    return Rule(name, fn, reads="in", writes=name, meta=meta).to_node({})


def test_a_node_without_activity_level_always_fires():
    infra = _rule("clock")
    policy = ActivitySample(min_active=0, max_active=0, rng=random.Random(0))
    assert policy.select([infra], Store().snapshot()) == [infra]


def test_activity_level_zero_never_fires():
    node = _rule("shy", activity_level=0.0)
    policy = ActivitySample(rng=random.Random(0))
    assert policy.select([node], Store().snapshot()) == []


def test_activity_level_one_always_survives_the_coin_flip():
    node = _rule("loud", activity_level=1.0)
    policy = ActivitySample(rng=random.Random(0))
    assert policy.select([node], Store().snapshot()) == [node]


def test_the_survivor_count_never_exceeds_max_active():
    nodes = [_rule(f"a{i}", activity_level=1.0) for i in range(50)]
    policy = ActivitySample(min_active=2, max_active=5, rng=random.Random(1))
    view = Store().snapshot()
    for _ in range(20):
        chosen = policy.select(nodes, view)
        assert 2 <= len(chosen) <= 5


def test_max_active_none_keeps_every_survivor():
    nodes = [_rule(f"a{i}", activity_level=1.0) for i in range(10)]
    policy = ActivitySample(rng=random.Random(2))
    assert len(policy.select(nodes, Store().snapshot())) == 10


def test_infra_and_gated_nodes_compose():
    clock = _rule("clock")
    agents = [_rule(f"a{i}", activity_level=1.0) for i in range(10)]
    policy = ActivitySample(min_active=1, max_active=3, rng=random.Random(3))
    chosen = policy.select([clock, *agents], Store().snapshot())
    assert clock in chosen
    assert 1 + 1 <= len(chosen) <= 1 + 3


def test_min_active_over_max_active_is_rejected():
    with pytest.raises(ValueError, match="min_active"):
        ActivitySample(min_active=5, max_active=2)


def test_is_deterministic_under_a_seeded_rng():
    nodes = [_rule(f"a{i}", activity_level=0.5) for i in range(20)]
    view = Store().snapshot()
    a = ActivitySample(min_active=1, max_active=4, rng=random.Random(42))
    b = ActivitySample(min_active=1, max_active=4, rng=random.Random(42))
    names_a = [n.name for n in a.select(nodes, view)]
    names_b = [n.name for n in b.select(nodes, view)]
    assert names_a == names_b
