"""A spec is the artifact a meta-agent emits, so it has to survive json and it has to reject
what the preset cannot use: both are what the composer's repair round depends on."""

import pytest
from fedotmas_meta import AgentSpec, SystemSpec
from pydantic import ValidationError


def _spec() -> SystemSpec:
    return SystemSpec(
        preset="swarm",
        fill={
            "personas": {
                "hawk": AgentSpec(prompt="You are a hawk."),
                "dove": AgentSpec(
                    prompt="You are a dove.", model="cheap", tools=["add"]
                ),
            }
        },
    )


def test_a_spec_round_trips_through_json():
    back = SystemSpec.model_validate_json(_spec().model_dump_json())
    assert back == _spec()


def test_a_many_role_stays_a_mapping_and_does_not_collapse_to_one_agent():
    many = _spec().fill["personas"]
    assert isinstance(many, dict)
    assert isinstance(many["hawk"], AgentSpec)


def test_a_single_agent_role_parses_as_one_agent():
    spec = SystemSpec(preset="pair", fill={"lead": AgentSpec(prompt="You lead.")})
    assert isinstance(spec.fill["lead"], AgentSpec)


def test_an_invented_field_is_refused():
    with pytest.raises(ValidationError):
        AgentSpec.model_validate({"prompt": "You are a hawk.", "temperature": 0.9})
