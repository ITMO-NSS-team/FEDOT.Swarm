"""The pydantic-ai adapter's shared usage meter, which is also what pydantic-ai enforces its
limits against: one backend instance must keep metering a whole swarm, not stop at the
per-run default of 50 requests."""

import pytest

pytest.importorskip("pydantic_ai")

from fedotmas.engine import Store
from fedotmas_llm import Call
from fedotmas_llm.adapters.pydantic_ai import PydanticAI
from pydantic_ai.models.test import TestModel

CALLS = 60  # past pydantic-ai's default UsageLimits.request_limit of 50


async def test_usage_accumulates_past_the_default_request_limit():
    backend = PydanticAI(model="test")
    backend._model_obj = TestModel(custom_output_text="ok")
    view = Store().snapshot()

    for _ in range(CALLS):
        assert await backend.complete(Call("say ok", "ping"), view) == "ok"

    usage = backend.usage
    assert usage.requests == CALLS
    assert usage.input_tokens > 0 and usage.output_tokens > 0
