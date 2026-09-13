# web

The demonstration front end: compose a swarm for a topic, watch it argue, and see what it
spent. Fresh 2 on Deno with Preact islands and `node:sqlite`; no charting or graph library.

```sh
deno install --frozen
deno task dev
```

The server spawns `uv run python benchmarks/swarm/run.py` in the repository root and reads the
run's `SqliteStore` while it is still being written. `OPENROUTER_API_KEY` is read by `run.py`
from the repository `.env` and never passes through this layer.

| Variable                | Default | What it is                         |
| ----------------------- | ------- | ---------------------------------- |
| `FEDOTMAS_WEB_DATA_DIR` | `./var` | run registry, fact stores, reports |
| `FEDOTMAS_ROOT`         | `..`    | where `uv run` is spawned          |

## Three screens

**Compose** sets the topic, the model, the cast size and the limit. _Write the cast_ is the
auto-construction path: a meta-agent proposes the personas and a deterministic assembler
checks them against the preset, with the handwritten cast as the fallback. _Free seats_ leaves
room for a casting agent to seat voices mid-run. A run with no limit is refused.

**Swarm** is the live picture, below. **Runs** lists what every run cost and why it ended.

## The influence graph

The store holds facts, so the drawing is derived rather than recorded. An edge runs from a
reader to an author whose post `by_interest` would have placed in that reader's feed window:
rank every post committed so far by how much of the reader's own vocabulary it uses, recent
first among equals, keep the top twelve. `lib/influence.ts` ports that ranking from
`fedotmas_meta.presets._swarm` so the graph can be rebuilt at any past round, which is what
the round scrubber does. Self-edges are dropped.

Three things the picture cannot say, and says so on screen instead:

- Below twelve posts every feed holds everything, so the graph is complete by construction.
- Without _a feed each_, the run read one shared wall; the edges are then affinity the run
  never acted on.
- A voice matches its own vocabulary best, so a loud one crowds its own window and appears to
  read fewer others.

## Scale

Cast size is nearly free at run time: `ActivitySample` lets two to a few dozen agents speak per
round whatever the roster holds, so a 200-agent room costs about what a 40-agent room costs per
round. What grows with cast size is composition, which is paid once.

Measured on this machine, building the graph and running sixty layout ticks:

| agents | posts | build  | edges  | layout/frame |
| ------ | ----- | ------ | ------ | ------------ |
| 40     | 90    | 9 ms   | 217    | 0.04 ms      |
| 200    | 625   | 15 ms  | 2 258  | 0.11 ms      |
| 500    | 1 500 | 73 ms  | 5 858  | 0.45 ms      |
| 1 000  | 2 400 | 215 ms | 11 859 | 1.58 ms      |

The force layout is not the limit: it stays two orders of magnitude inside a frame. The limits
are the per-poll graph build, which is O(readers x posts), and the number of SVG elements the
browser re-diffs. Past two thousand edges a snapshot carries only the strongest and counts the
rest, so both the payload and the element count are bounded by the cap rather than the cast.

A real 200-agent run, composed in batches of ten and capped at three rounds, served its graph in
10 ms over a 215 kB snapshot: 200 nodes, 2 000 edges with 289 thinned. What the picture showed
is that 129 of the 200 never spoke, because the activity throttle admits a few voices a round
whatever the roster holds. A large cast is a statement about who could speak, not about who
did.

## Verify

```sh
deno task verify
```

Formatting, lint, types, tests and the production build. The tests cover the ranking, the
layout, request validation and reading a store the engine wrote; they never call a provider.
Starting a real run, and everything downstream of the provider, is not covered by them.
