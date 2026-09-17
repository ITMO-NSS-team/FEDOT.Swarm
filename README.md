<div align="center">

<img src="https://raw.githubusercontent.com/ITMO-NSS-Team/fedotmas/main/assets/logo.svg" alt="logo" width="180"/>

# `FEDOT.MAS`

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://python.org)

</div>

> [!WARNING]
> Early development (v0.1). The API will change between versions.

A tiny typed dataflow engine for systems that build up a shared state, and the
harness that orchestrates the agents inside them. Bring agents from any
framework, mix them with plain code and raw model calls, and run them as one
typed system instead of gluing them together by hand. A thin LLM layer
(PydanticAI by default) on top turns it into a multi-agent framework.

## Install

Install from git with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/ITMO-NSS-team/fedotmas-harness.git
cd fedotmas-harness
uv sync --all-packages
```

## Packages

- [`fedotmas`](packages/fedotmas): the engine and typed SDK.
- [`fedotmas-llm`](packages/fedotmas-llm): the LLM extension. Agents, provider
  backends, serving. Early.
- [`fedotmas-meta`](packages/fedotmas-meta): the meta-agent that builds systems
  from a task description. Early.
- [`web`](web): the demonstration front end. Compose a swarm, watch it argue on
  an influence graph, and see what it spent. Deno and Fresh, not part of the
  Python workspace.

## Running the demo

`benchmarks/swarm` and [`benchmarks/paperbench`](benchmarks/paperbench) both run
on OpenRouter (`OPENROUTER_API_KEY` in `.env`) through `fedotmas-llm`'s
`pydantic-ai` extra, one shared venv for the whole workspace:

```bash
uv sync --all-packages --extra pydantic-ai
uv run python benchmarks/swarm/run.py --personas 2 --rounds 1 --usd 0.001
```

PaperBench (also reachable from the same web UI, as "PaperBench" in Compose)
needs one more group for `--paper-pdf` support — add `--group paperbench` to the
`uv sync` above and it runs the same way; its own
[README](benchmarks/paperbench/README.md) is only for the extra flags (paper
source, rubric, spend caps), not required just to get it running.

The [`web`](web) front end drives both:

```bash
cd web
deno install --frozen
deno task dev
```

## Articles

- **Does going multi-agent pay off, and can you auto-pick a pattern per task?**
  ·
  [EN](https://dev.to/enorth/does-going-multi-agent-pay-off-and-can-you-auto-pick-a-pattern-per-task-15ld)
  · [RU](https://habr.com/ru/articles/1047422/)
