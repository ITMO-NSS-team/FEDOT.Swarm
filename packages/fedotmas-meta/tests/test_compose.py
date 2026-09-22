"""The composer is the only part that talks to a model, so what is worth pinning is what it
does with the answer: accept it, send it back with its problems, or stand the fallback up. The
model itself is scripted here; the real provider is exercised in benchmarks/swarm."""

import pytest
from fedotmas.engine import View
from fedotmas_llm import Call
from fedotmas_meta import AgentSpec, SpecError, SystemSpec, brief, compose
from fedotmas_meta.presets import SwarmPreset

TASK = "should weights be open?"


class Scripted:
    """Hands back canned specs in order and keeps what it was asked, so a test can see what
    the repair round actually told the model."""

    def __init__(self, *answers: SystemSpec) -> None:
        self.answers = list(answers)
        self.asked: list[Call] = []

    async def complete(self, call: Call, view: View) -> SystemSpec:
        self.asked.append(call)
        return self.answers.pop(0)


def _cast(*names: str, preset: str = "swarm") -> SystemSpec:
    return SystemSpec(
        preset=preset,
        fill={"personas": {n: AgentSpec(prompt=f"You are the {n}.") for n in names}},
    )


async def test_a_valid_cast_is_taken_as_it_comes():
    llm = Scripted(_cast("hawk", "dove"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=2)
    assert out.attempts == 1
    assert out.rejected == ()
    assert not out.fell_back
    assert sorted(out.spec.fill["personas"]) == ["dove", "hawk"]


async def test_the_wrong_head_count_goes_back_with_the_number_it_missed():
    llm = Scripted(_cast("hawk"), _cast("hawk", "dove"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=2)
    assert out.attempts == 2
    assert "needs exactly 2 agents, got 1" in out.rejected[0]
    assert "rejected" in llm.asked[1].input
    assert not out.fell_back


async def test_a_cast_that_shadows_the_preset_is_sent_back():
    llm = Scripted(_cast("clock", "dove"), _cast("hawk", "dove"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=2)
    assert "['clock'] are taken already" in out.rejected[0]
    assert out.attempts == 2


async def test_naming_another_preset_is_sent_back():
    llm = Scripted(_cast("hawk", "dove", preset="pair"), _cast("hawk", "dove"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=2)
    assert "preset must be 'swarm', not 'pair'" in out.rejected[0]


async def test_a_model_that_keeps_failing_falls_back_instead_of_stalling_the_run():
    fallback = _cast("hawk", "dove")
    llm = Scripted(_cast("hawk"), _cast("dove"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=2, fallback=fallback)
    assert out.fell_back
    assert out.spec is fallback
    assert out.attempts == 2
    assert len(out.rejected) == 2


async def test_without_a_fallback_a_failed_composition_is_an_error():
    llm = Scripted(_cast("hawk"), _cast("dove"))
    with pytest.raises(SpecError, match="composition failed after 2 attempts"):
        await compose(TASK, SwarmPreset(), llm=llm, count=2)


async def test_repairs_zero_means_one_shot():
    llm = Scripted(_cast("hawk"))
    out = await compose(
        TASK, SwarmPreset(), llm=llm, count=2, repairs=0, fallback=_cast()
    )
    assert out.attempts == 1
    assert out.fell_back


def test_the_preset_describes_itself_to_the_composer():
    text = brief(SwarmPreset(), 7)
    assert "'swarm'" in text
    assert "exactly 7 of them" in text
    assert "['clock', 'feed']" in text
    assert (
        '{"preset": "swarm", "fill": {"personas": {"<id>": {"prompt": "..."}}}}' in text
    )


async def test_a_large_cast_is_filled_over_several_calls():
    llm = Scripted(_cast("hawk", "dove"), _cast("owl", "crow"), _cast("wren", "tern"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=6, batch=2)
    assert out.attempts == 3
    assert sorted(out.spec.fill["personas"]) == [
        "crow",
        "dove",
        "hawk",
        "owl",
        "tern",
        "wren",
    ]
    assert "already in the room" not in llm.asked[0].prompt
    assert "['dove', 'hawk']" in llm.asked[1].prompt
    assert "['crow', 'dove', 'hawk', 'owl']" in llm.asked[2].prompt


async def test_the_last_batch_asks_only_for_what_is_missing():
    llm = Scripted(_cast("hawk", "dove"), _cast("owl"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=3, batch=2)
    assert out.attempts == 2
    assert "exactly 1 of them" in llm.asked[1].prompt


async def test_a_batch_that_repeats_a_placed_id_is_sent_back():
    llm = Scripted(_cast("hawk", "dove"), _cast("hawk", "owl"), _cast("crow", "owl"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=4, batch=2)
    assert "['hawk'] are taken already" in out.rejected[0]
    assert sorted(out.spec.fill["personas"]) == ["crow", "dove", "hawk", "owl"]


async def test_a_batch_short_of_its_ask_is_sent_back_with_the_number_it_missed():
    llm = Scripted(_cast("hawk"), _cast("hawk", "dove"))
    out = await compose(TASK, SwarmPreset(), llm=llm, count=2, batch=2)
    assert "needs exactly 2 agents, got 1" in out.rejected[0]
    assert out.attempts == 2
