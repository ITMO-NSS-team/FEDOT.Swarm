# AGENTS.md

Working notes for agents and contributors. `fedotmas` is a uv-workspace monorepo: a tiny typed
dataflow engine (`fedotmas`) with an LLM extension (`fedotmas-llm`) and a meta-agent
(`fedotmas-meta`). Python 3.11+.

## Setup

```bash
uv sync --all-packages
```

Dependencies go through uv, never by hand-editing `pyproject.toml`:

```bash
uv add <pkg>                 # runtime dep of the current package
uv add --group dev <pkg>     # dev tooling
```

## Verify before calling work done

```bash
uv run ruff check <paths>             # lint
uv run ruff format <paths>            # format (add --check to verify only)
uv run ty check packages/                                     # types
uv run pytest packages/fedotmas packages/fedotmas-llm packages/fedotmas-meta -q
```

Trust ruff, ty, and pytest, not the editor's Pyright.

## Code style

Maximum minimalism; the code speaks for itself.

- Docstrings and docs: 1 to 3 sentences (what and why), never a retell of the implementation. The
  long essay-docstrings in older modules are not the model.
- No filler comments and no noise. Show structure with code, not comment banners.
- No ASCII separators (`# --- ... ---`, `=== ... ===`).
- All imports at the top of the file.
- Prose (README, docs, this file): no long dashes; use a colon, parentheses, or a period.
- Prefer `match`/`case` over long `isinstance` ladders.

## Architecture invariants

- `engine/` is the floor: one primitive (a `Node`, a guarded reaction over a shared fact store)
  plus a superstep executor. Coordination happens only through fact tags on the store; nodes are
  black boxes.
- `flow/` and `blackboard/` are the two authoring surfaces over the engine. They are peers and
  depend only downward, on `engine`.
- `serialize/` is a projection beside the runtime: it imports inward (`engine`, `flow`,
  `blackboard`) and is never imported by the surfaces. Keep the surfaces serialization-agnostic.
  The dependency direction is `engine <- {flow, blackboard} <- serialize`.
- `atoms.py` is the code leaf (`action`); `ext.py` is the extension seam for custom node-kinds.
- Core `fedotmas` is provider-free (no LLM). Backends, agents, and `PromptRule` live in
  `fedotmas-llm`; system synthesis lives in `fedotmas-meta`.

## Tests

- pytest runs with `asyncio_mode = "auto"`: write plain `async def test_...`, no decorator.
- Tests live in `packages/<pkg>/tests/`.

## Git

Commit or push only when explicitly asked.
