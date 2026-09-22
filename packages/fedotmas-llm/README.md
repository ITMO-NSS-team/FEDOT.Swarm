# fedotmas-llm

The LLM extension over the [`fedotmas`](../fedotmas) engine.

The bundled backend ships under an extra: `pip install fedotmas-llm[pydantic-ai]`. Serving lives under `serve`.

> The runnable examples need a provider key, e.g. `OPENAI_API_KEY`.

## Agents

`agent` lifts a prompt into a typed atom, the LLM version of `action`. It composes with everything in the core:

```python
import asyncio
from fedotmas_llm import agent
from fedotmas_llm.adapters.pydantic_ai import PydanticAI

outline = agent("outline", prompt="Give a 3-bullet outline for the topic.")
draft = agent("draft", prompt="Write one vivid paragraph from the outline.")

flow = outline + draft
backend = PydanticAI("openai:gpt-4o-mini")
print(asyncio.run(flow.run("geralt of rivia", bind={"llm": backend})).value)
```

The backend binds once per run under `"llm"`, so nothing is hard-wired into the nodes. Code and prompts mix freely, because `action` and `agent` are the same kind of node:

```python
from fedotmas import action

@action
async def count(text: str) -> dict:
    return {"text": text, "words": len(text.split())}

flow = agent("summarize", prompt="Summarize in one sentence.") + count
```

## The backend seam

A backend is anything with one method: `complete(call, view) -> value`, where `call` bundles the prompt, input, declared output type, and tools. Any agent SDK plugs in, and the engine never imports a provider:

```python
class Echo:
    async def complete(self, call, view):
        return f"{call.prompt}: {call.input}"

run = await flow.run("topic", bind={"llm": Echo()})
```

`PydanticAI` is the batteries-included adapter, with structured output and token accounting. See [examples/llm/backends.py](../../examples/llm/backends.py) for binding others.

## Classify and route

Give an agent `labels` and it returns one of them, the shape `branch` routes on:

```python
from fedotmas import branch

kind = agent("kind", prompt="Classify the issue.", labels=["bug", "feature"])
triage = branch(kind, {"bug": fix, "feature": plan})
```

## Reactive boards

`PromptRule` is the blackboard version, a rule whose body is a prompt. Code `Rule`s and `PromptRule`s share one board:

```python
from fedotmas import blackboard
from fedotmas_llm import PromptRule

board = blackboard(
    PromptRule(name="draft", reads="topic", writes="draft", prompt="Draft it."),
    PromptRule(name="check", reads="draft", writes="report", prompt="Review it."),
)
out = await board.run({"topic": "tea"}, goal="report", bind={"llm": backend})
```

## Spending

`SpendLimit` caps what a run may spend, in tokens, requests, or USD at a `Price` per million
tokens. Past the cap it stops calling nodes at all, so the board goes quiet and the run ends
with its store intact instead of with a pile of errors:

```python
from fedotmas.ext.plugins import ConcurrencyLimit
from fedotmas_llm import Price, SpendLimit

limit = SpendLimit(backend, usd=0.01, price=Price(input=0.03, output=0.13))
out = await board.run(seed, goal="report", bind={"llm": backend},
                      plugins=[ConcurrencyLimit(3), limit])
print(limit.report())
```

It reads the backend's own meter, counting from the moment it is built, so whatever was spent
configuring the system does not eat the run's budget. Nodes are black boxes to the engine, so
a spent budget stops the code rules too: the cap is on the run, not on the provider. The check
runs before each call, which means calls already in flight still land.

## Serving

Run a manifest over HTTP/SSE and MCP under the `serve` extra (`pip install fedotmas-llm[serve]`). MCP, file/URI, and A2A capabilities wire by reference. Early.
