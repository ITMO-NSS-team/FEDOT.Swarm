<div align="center">

<img src="https://raw.githubusercontent.com/ITMO-NSS-Team/fedotmas/main/assets/logo.svg" alt="logo" width="180"/>

# `FEDOT.MAS`

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://python.org)

</div>

A tiny typed dataflow engine for systems that build up a shared state, and the harness that orchestrates the agents inside them. Bring agents from any framework, mix them with plain code and raw model calls, and run them as one typed system instead of gluing them together by hand. A thin LLM layer (PydanticAI by default) on top turns it into a multi-agent framework.

## Install

Install from git with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/ITMO-NSS-team/fedotmas-harness.git
cd fedotmas-harness
uv sync --all-packages
```

## Packages

- [`fedotmas`](packages/fedotmas): the engine and typed SDK.
- [`fedotmas-llm`](packages/fedotmas-llm): the LLM extension. Agents, provider backends, serving. Early.
- [`fedotmas-meta`](packages/fedotmas-meta): the meta-agent that builds systems from a task description. Early.
- [`web`](web): the demonstration front end. Compose a swarm, watch it argue on an influence graph, and see what it spent.

## Running the demo

The demo reproduces the code of a paper with a swarm of OpenCode coding agents, graded against one PaperBench rubric branch, and shows the run live in the web front end. Everything runs from one container; the only input is an OpenRouter key.

```bash
cp .env.example .env      # OPENROUTER_API_KEY=sk-or-...
just up                   # builds the image and serves http://localhost:8000
```

The image carries marker (PDF to markdown with layout, tables, equations and OCR), OpenCode 1.18.20 and the built front end; runs and their workspaces live in the `fedotmas-data` volume. [docs/paperbench.md](docs/paperbench.md) walks through composing, watching, exploring and reproducing a run.

From a checkout instead, with OpenCode on the PATH and `marker_single` as an optional `uv tool` (pymupdf is the fallback):

```bash
uv sync --all-packages --extra pydantic-ai --extra opencode --group paperbench
just web                  # the dev front end on http://127.0.0.1:5173
just smoke                # a two-agent, two-round run from the CLI (about $0.10)
```

`benchmarks/swarm` is the free-topic swarm the same front end also starts:

```bash
uv run python benchmarks/swarm/run.py --personas 2 --rounds 1 --usd 0.001
```

`just verify` runs ruff, ty, pytest and the web checks; `just e2e` drives the front end in headless Chromium against a fake runner.

## Articles

- **Does going multi-agent pay off, and can you auto-pick a pattern per task?**
  · [EN](https://dev.to/enorth/does-going-multi-agent-pay-off-and-can-you-auto-pick-a-pattern-per-task-15ld)
  · [RU](https://habr.com/ru/articles/1047422/)
