from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from fedotmas.engine import Store
from fedotmas_llm import LLM, Call

from fedotmas_meta._assemble import Models, Tools, resolve
from fedotmas_meta._spec import AgentSpec, Preset, SpecError, SystemSpec

BRIEF = """You compose an agent system for someone else to run.

The preset is {name!r}: {hint}
Fill these roles:
{roles}

An agent is {{"prompt": ..., "model": null, "tools": []}}. Its prompt states who the agent is,
in the second person, in one or two sentences: the role, what it argues from, and what puts it
at odds with the others. Say nothing about the medium or the output format, the preset supplies
those. Leave model null and tools empty.

The keys of a mapping role are node names: valid Python identifiers, all different, and none of
{reserved}.
{taken}
Answer with exactly this shape:
{shape}

Make the voices genuinely disagree. A room that agrees produces nothing worth reading."""

TAKEN = """
These voices are already in the room: {taken}. Do not reuse their ids, and do not write anyone
who would only echo them.
"""

Fill = dict[str, "AgentSpec | dict[str, AgentSpec]"]


@dataclass(frozen=True)
class Composed:
    """What a composition produced and what it took: `attempts` counts model calls, `rejected`
    holds what each discarded attempt was told, and `fell_back` means none of them passed."""

    spec: SystemSpec
    attempts: int
    rejected: tuple[str, ...] = ()
    fell_back: bool = False


def brief(preset: Preset, count: int, taken: Sequence[str] = ()) -> str:
    """The preset describing itself to the composer, so a new preset needs no second prompt
    written by hand. `taken` names the agents a previous batch already placed."""
    roles = "\n".join(
        f"- {r.name}: {r.hint} "
        f"({f'a mapping of ids to agents, exactly {count} of them' if r.many else 'one agent'})"
        for r in preset.roles
    )
    fill = {
        r.name: {"<id>": {"prompt": "..."}} if r.many else {"prompt": "..."}
        for r in preset.roles
    }
    return BRIEF.format(
        name=preset.name,
        hint=preset.hint,
        roles=roles,
        reserved=sorted(preset.reserved),
        taken=TAKEN.format(taken=list(taken)) if taken else "",
        shape=json.dumps({"preset": preset.name, "fill": fill}, ensure_ascii=False),
    )


async def compose(
    task: str,
    preset: Preset,
    *,
    llm: LLM,
    count: int,
    batch: int | None = None,
    models: Models | None = None,
    tools: Tools | None = None,
    repairs: int = 1,
    fallback: SystemSpec | None = None,
) -> Composed:
    """Have a model fill a preset's roles for a task, and validate what comes back before
    anything runs. A rejected batch goes round again with its problems attached, `repairs`
    times, and past that the fallback stands in or the last SpecError is raised. Asked for a
    large cast at once a model quietly returns fewer, so `batch` caps how many it is asked for
    in one call and the room fills over several, each told who is in it already. Only spec
    problems are caught here: a provider failure is the caller's to see."""
    size = max(1, min(batch or count, count))
    many = tuple(r.name for r in preset.roles if r.many)
    view = Store().snapshot()
    fill: Fill = {}
    rejected: list[str] = []
    attempts, left = 0, repairs
    while (ask := _wanted(fill, many, count, size)) is not None:
        taken = sorted(k for role in many for k in _mapping(fill, role))
        content = task
        if rejected:
            content = f"{task}\n\nYour last answer was rejected: {rejected[-1]}"
        attempts += 1
        spec = await llm.complete(
            Call(brief(preset, ask, taken), content, returns=SystemSpec), view
        )
        if issues := _issues(spec, preset, ask, taken, first=not fill):
            rejected.append("; ".join(issues))
            if left == 0:
                return _give_up(fallback, attempts, rejected)
            left -= 1
            continue
        _merge(fill, spec.fill, many)
        left = repairs
    final = SystemSpec(preset=preset.name, fill=fill)
    try:
        resolve(final, preset, models=models, tools=tools)
    except SpecError as e:
        rejected.append(str(e))
        return _give_up(fallback, attempts, rejected)
    return Composed(final, attempts, tuple(rejected))


def _wanted(fill: Fill, many: tuple[str, ...], count: int, size: int) -> int | None:
    """How many agents to ask for next, or None once every role is filled."""
    if not fill:
        return min(size, count)
    have = min((len(_mapping(fill, role)) for role in many), default=count)
    return min(size, count - have) if have < count else None


def _mapping(fill: Fill, role: str) -> dict[str, AgentSpec]:
    given = fill.get(role)
    return given if isinstance(given, dict) else {}


def _merge(fill: Fill, batch: Fill, many: tuple[str, ...]) -> None:
    """Keep the first agent placed under any name: a later batch repeating an id is the model
    echoing itself, not a correction."""
    for role, given in batch.items():
        if role not in many:
            fill.setdefault(role, given)
            continue
        placed = fill.setdefault(role, {})
        if isinstance(placed, dict) and isinstance(given, dict):
            for name, agent in given.items():
                placed.setdefault(name, agent)


def _issues(
    spec: SystemSpec,
    preset: Preset,
    ask: int,
    taken: Sequence[str],
    first: bool,
) -> list[str]:
    """What is wrong with one batch, in the words the model gets back. The whole spec is
    checked against the preset by resolve once the last batch lands."""
    issues = []
    if spec.preset != preset.name:
        issues.append(f"preset must be {preset.name!r}, not {spec.preset!r}")
    for role in preset.roles:
        given = spec.fill.get(role.name)
        if not role.many:
            if first and not isinstance(given, AgentSpec):
                issues.append(f"role {role.name!r} takes one agent")
            continue
        if not isinstance(given, dict):
            issues.append(
                f"role {role.name!r} takes a name to agent mapping, not one agent"
            )
            continue
        if len(given) != ask:
            issues.append(
                f"role {role.name!r} needs exactly {ask} agents, got {len(given)}"
            )
        if bad := sorted(k for k in given if not k.isidentifier()):
            issues.append(f"role {role.name!r}: {bad} are not usable ids")
        if clash := sorted(set(given) & (preset.reserved | set(taken))):
            issues.append(f"role {role.name!r}: {clash} are taken already")
    return issues


def _give_up(
    fallback: SystemSpec | None, attempts: int, rejected: list[str]
) -> Composed:
    if fallback is None:
        raise SpecError(f"composition failed after {attempts} attempts: {rejected[-1]}")
    return Composed(fallback, attempts, tuple(rejected), True)
