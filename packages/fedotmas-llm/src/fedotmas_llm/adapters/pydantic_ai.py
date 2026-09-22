from __future__ import annotations

import json
from typing import Any

from fedotmas.engine.contract import View
from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model, infer_model
from pydantic_ai.usage import RunUsage, UsageLimits

from fedotmas_llm._llm import Call, Usage
from fedotmas_llm._tools import FunctionTool, MCPTool


def _as_text(input: Any) -> str:
    if isinstance(input, str):
        return input
    if isinstance(input, BaseModel):
        return input.model_dump_json()
    return json.dumps(input, ensure_ascii=False, default=str)


def _split(tools: tuple[Any, ...]) -> tuple[list[Tool], list[Any]]:
    """Route fedotmas descriptors to pydantic-ai's two slots: FunctionTool -> tools=,
    MCPTool -> toolsets= (MCPToolset reads the transport off the url)."""
    fns = [Tool(t.fn, name=t.name) for t in tools if isinstance(t, FunctionTool)]
    servers = [MCPToolset(t.url) for t in tools if isinstance(t, MCPTool)]
    return fns, servers


class PydanticAI:
    """An LLM backend over pydantic-ai Agent."""

    def __init__(self, model: str, **settings: Any) -> None:
        self._model = model
        self._settings = settings
        self._model_obj: Model | None = None
        self._usage = RunUsage()
        # the shared meter is also what pydantic-ai checks its limits against, so its
        # default request_limit=50 would cap the whole backend, not one call
        self._limits = UsageLimits(request_limit=None)

    @property
    def usage(self) -> Usage:
        return Usage(
            self._usage.input_tokens, self._usage.output_tokens, self._usage.requests
        )

    async def complete(self, call: Call, view: View) -> Any:
        if self._model_obj is None:
            self._model_obj = infer_model(self._model)
        fns, servers = _split(call.tools)
        agent = Agent(
            self._model_obj,
            output_type=call.returns,
            system_prompt=call.prompt,
            tools=fns,
            toolsets=servers,
            **self._settings,
        )
        result = await agent.run(
            _as_text(call.input), usage=self._usage, usage_limits=self._limits
        )
        return result.output
