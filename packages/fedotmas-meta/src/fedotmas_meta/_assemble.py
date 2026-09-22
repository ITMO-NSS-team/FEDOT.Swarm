from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from fedotmas.engine.system import Compilable
from fedotmas_llm import LLM, FunctionTool, MCPTool, Tool

from fedotmas_meta._catalog import Catalog
from fedotmas_meta._spec import AgentSpec, Preset, SpecError, SystemSpec

Models = Mapping[str, LLM]
Tools = Mapping[str, Callable[..., Any]]


@dataclass(frozen=True)
class Agent:
    """An AgentSpec with its references resolved: the backend and tool objects the spec named
    by key, ready for a preset to wire into a node. `llm` None leaves the node on the
    run-scoped `bind={"llm": ...}`."""

    name: str
    prompt: str
    llm: LLM | None = None
    tools: tuple[Tool, ...] = ()


Fill = dict[str, "Agent | dict[str, Agent]"]


def assemble(
    spec: SystemSpec,
    catalog: Catalog,
    *,
    models: Models | None = None,
    tools: Tools | None = None,
) -> Compilable:
    """Turn a SystemSpec into a container the engine can compile. Provider-free and
    deterministic: it checks the fill against the preset's roles and resolves every model and
    tool key, then the preset does the wiring."""
    preset = catalog[spec.preset]
    return preset.build(resolve(spec, preset, models=models, tools=tools))


def resolve(
    spec: SystemSpec,
    preset: Preset,
    *,
    models: Models | None = None,
    tools: Tools | None = None,
) -> Fill:
    """Check a spec against its preset and resolve its registry keys, without building
    anything. Every problem is collected into one SpecError, so a meta-agent repairs a whole
    malformed spec in a single round."""
    known_models, known_tools = models or {}, tools or {}
    roles = {r.name: r for r in preset.roles}
    problems = [
        f"no role {name!r} in preset {preset.name!r}, its roles are {sorted(roles)}"
        for name in sorted(spec.fill.keys() - roles.keys())
    ]
    problems += [
        f"role {name!r} is not filled"
        for name in sorted(roles.keys() - spec.fill.keys())
    ]
    fill: Fill = {}
    for name, role in roles.items():
        match (role.many, spec.fill.get(name)):
            case (_, None):
                continue
            case (True, dict() as many):
                problems += _name_problems(name, many, preset.reserved)
                fill[name] = {
                    key: _agent(key, one, known_models, known_tools, problems)
                    for key, one in many.items()
                }
            case (False, AgentSpec() as one):
                fill[name] = _agent(name, one, known_models, known_tools, problems)
            case (True, _):
                problems.append(
                    f"role {name!r} takes a name to agent mapping, not one agent"
                )
            case _:
                problems.append(f"role {name!r} takes one agent, not a mapping")
    if problems:
        raise SpecError(f"preset {preset.name!r}: " + "; ".join(problems))
    return fill


def _name_problems(
    role: str, many: Mapping[str, AgentSpec], reserved: frozenset[str]
) -> list[str]:
    """A many role's keys become node names, so they have to be usable as such and must not
    shadow the nodes the preset wires in itself."""
    problems = [] if many else [f"role {role!r} is filled with no agents"]
    if bad := sorted(k for k in many if not k.isidentifier()):
        problems.append(f"role {role!r}: {bad} are not usable node names")
    if clash := sorted(set(many) & reserved):
        problems.append(f"role {role!r}: {clash} collide with the preset's own nodes")
    return problems


def _agent(
    name: str, spec: AgentSpec, models: Models, tools: Tools, problems: list[str]
) -> Agent:
    llm = None
    if spec.model is not None:
        llm = models.get(spec.model)
        if llm is None:
            problems.append(f"{name!r}: no model {spec.model!r} in {sorted(models)}")
    return Agent(
        name, spec.prompt, llm, tuple(_tools(name, spec.tools, tools, problems))
    )


def _tools(
    name: str, keys: Iterable[str], registry: Tools, problems: list[str]
) -> Iterable[Tool]:
    for key in keys:
        if key.startswith(("http://", "https://")):
            yield MCPTool(key)
        elif key in registry:
            yield FunctionTool(key, registry[key])
        else:
            problems.append(f"{name!r}: no tool {key!r} in {sorted(registry)}")
