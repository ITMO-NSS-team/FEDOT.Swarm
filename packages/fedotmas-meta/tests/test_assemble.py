"""Assembly is the deterministic half of synthesis: every way a spec can fail to fit its
preset is caught here, before a provider is touched, and reported in one message so a
meta-agent repairs the whole spec in one round."""

import pytest
from fedotmas.engine import View
from fedotmas_llm import Call, FunctionTool, MCPTool
from fedotmas_meta import (
    Agent,
    AgentSpec,
    Catalog,
    Fill,
    RoleSpec,
    SpecError,
    SystemSpec,
    resolve,
)


class Backend:
    """Stands in for a registered model: assembly only ever stores it, never calls it."""

    async def complete(self, call: Call, view: View) -> str:
        return ""


class Pair:
    """A two-role preset: one lead and a chorus of many, enough to exercise both slot kinds."""

    name = "pair"
    hint = "a lead and a chorus"
    roles = (
        RoleSpec("lead", "starts the song"),
        RoleSpec("chorus", "answers it", True),
    )
    reserved = frozenset({"clock"})

    def build(self, fill):
        return fill


def _one(fill: Fill, role: str) -> Agent:
    agent = fill[role]
    assert isinstance(agent, Agent)
    return agent


def _many(fill: Fill, role: str) -> dict[str, Agent]:
    agents = fill[role]
    assert isinstance(agents, dict)
    return agents


def _spec(**fill) -> SystemSpec:
    return SystemSpec(preset="pair", fill=fill)


def _ok() -> SystemSpec:
    return _spec(
        lead=AgentSpec(prompt="You lead."),
        chorus={"alto": AgentSpec(prompt="You are the alto.")},
    )


def test_a_well_formed_spec_resolves_to_agents_per_slot():
    fill = resolve(_ok(), Pair())
    assert _one(fill, "lead").name == "lead"
    assert _one(fill, "lead").prompt == "You lead."
    assert set(_many(fill, "chorus")) == {"alto"}
    assert _many(fill, "chorus")["alto"].llm is None


def test_registry_keys_resolve_to_backends_and_tools():
    backend = Backend()
    spec = _spec(
        lead=AgentSpec(
            prompt="You lead.", model="cheap", tools=["add", "https://mcp.test"]
        ),
        chorus={"alto": AgentSpec(prompt="You are the alto.")},
    )
    fill = resolve(spec, Pair(), models={"cheap": backend}, tools={"add": sum})
    lead = _one(fill, "lead")
    assert lead.llm is backend
    assert lead.tools == (FunctionTool("add", sum), MCPTool("https://mcp.test"))


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (_spec(chorus={"alto": AgentSpec(prompt="a")}), "'lead' is not filled"),
        (
            _ok().model_copy(
                update={"fill": {**_ok().fill, "solo": AgentSpec(prompt="a")}}
            ),
            "no role 'solo'",
        ),
        (
            _spec(lead=AgentSpec(prompt="a"), chorus=AgentSpec(prompt="b")),
            "takes a name to agent mapping",
        ),
        (
            _spec(
                lead={"x": AgentSpec(prompt="a")},
                chorus={"alto": AgentSpec(prompt="b")},
            ),
            "takes one agent",
        ),
        (_spec(lead=AgentSpec(prompt="a"), chorus={}), "filled with no agents"),
        (
            _spec(
                lead=AgentSpec(prompt="a"), chorus={"the alto": AgentSpec(prompt="b")}
            ),
            "not usable node names",
        ),
        (
            _spec(lead=AgentSpec(prompt="a"), chorus={"clock": AgentSpec(prompt="b")}),
            "collide with the preset's own nodes",
        ),
        (
            _spec(
                lead=AgentSpec(prompt="a", model="gpt9"),
                chorus={"alto": AgentSpec(prompt="b")},
            ),
            "no model 'gpt9'",
        ),
        (
            _spec(
                lead=AgentSpec(prompt="a", tools=["nope"]),
                chorus={"alto": AgentSpec(prompt="b")},
            ),
            "no tool 'nope'",
        ),
    ],
)
def test_a_spec_that_does_not_fit_its_preset_is_refused(spec, expected):
    with pytest.raises(SpecError, match=expected):
        resolve(spec, Pair())


def test_every_problem_is_reported_at_once_so_one_repair_round_is_enough():
    spec = _spec(chorus={"clock": AgentSpec(prompt="a", model="gpt9")})
    with pytest.raises(SpecError) as e:
        resolve(spec, Pair())
    message = str(e.value)
    assert "'lead' is not filled" in message
    assert "collide" in message
    assert "no model 'gpt9'" in message


def test_an_unknown_preset_names_the_catalog_it_is_missing_from():
    with pytest.raises(
        SpecError, match=r"no preset 'duet': the catalog holds \['pair'\]"
    ):
        Catalog(Pair())["duet"]


def test_a_catalog_refuses_two_presets_under_one_name():
    with pytest.raises(ValueError, match="duplicate preset names"):
        Catalog(Pair(), Pair())


def test_the_menu_is_the_line_a_selector_ranks_on():
    assert Catalog(Pair()).menu() == "pair: a lead and a chorus"
