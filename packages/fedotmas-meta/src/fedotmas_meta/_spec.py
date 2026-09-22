from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from fedotmas.engine.system import Compilable
from pydantic import BaseModel, Field


class AgentSpec(BaseModel):
    """One agent as fillable strings: the prompt, an optional model key (resolved against a
    `models` registry at assembly, None falls back to the run-scoped `bind={"llm": ...}`), and
    tool names (a registry key for a local fn, a url for an MCP server). Pure data, so a spec
    round-trips through json and a meta-agent authors one without touching an SDK."""

    model_config = {"extra": "forbid"}

    prompt: str = Field(min_length=1)
    model: str | None = None
    tools: list[str] = Field(default_factory=list)


class SystemSpec(BaseModel):
    """A whole system as a preset name plus its filling: each role maps to an AgentSpec, or to
    a name -> AgentSpec dict for a `many` role. The serializable proposal a meta-agent emits."""

    model_config = {"extra": "forbid"}

    preset: str
    fill: dict[str, AgentSpec | dict[str, AgentSpec]]


@dataclass(frozen=True)
class RoleSpec:
    """One slot of a preset: `many=False` takes one AgentSpec, `many=True` a name -> AgentSpec
    dict whose keys become node names and routing labels."""

    name: str
    hint: str
    many: bool = False


@runtime_checkable
class Preset(Protocol):
    """A pattern family with named role slots. `hint` is the one-liner the selector ranks on,
    `roles` says which slots to fill, `reserved` the wiring names a many role must avoid, and
    `build` turns a filling into a container the engine can compile (a Flow, a Board, any
    Compilable). The catalog is the caller's: the package ships this protocol, not a fixed
    menu of systems."""

    @property
    def name(self) -> str: ...
    @property
    def hint(self) -> str: ...
    @property
    def roles(self) -> tuple[RoleSpec, ...]: ...
    @property
    def reserved(self) -> frozenset[str]: ...
    def build(self, fill: Any) -> Compilable: ...


class SpecError(ValueError):
    """A spec that does not fit its preset, or that names something no registry holds. The
    message lists every problem at once, so one repair round fixes a whole malformed spec."""
