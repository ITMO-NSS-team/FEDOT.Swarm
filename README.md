<div align="center">

<img src="https://raw.githubusercontent.com/ITMO-NSS-Team/fedotmas/main/assets/logo.svg" alt="logo" width="180"/>

# `FEDOT.Swarm`

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

## Running the demo

The demo reproduces the code of a paper with a swarm of OpenCode coding agents.

```bash
cp .env.example .env      # OPENROUTER_API_KEY=sk-or-...
just up                   # builds the image and serves http://localhost:8000
```

## Articles

- Does going multi-agent pay off, and can you auto-pick a pattern per task?
  · [EN](https://dev.to/enorth/does-going-multi-agent-pay-off-and-can-you-auto-pick-a-pattern-per-task-15ld)
  · [RU](https://habr.com/ru/articles/1047422/)
