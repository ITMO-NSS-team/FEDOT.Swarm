# Swarm

What a swarm of prompt rules costs on a real provider, and what it costs to have a meta-agent
write the swarm instead of writing it by hand. The system is the one in
`packages/fedotmas-llm/tests/test_swarm.py` with the stub LLM swapped for `PydanticAI`:
personas with per-agent `activity_level` argue a topic on a shared feed, `ActivitySample`
picks who speaks each round, `ConcurrencyLimit` caps in-flight requests, `Retry` covers
provider HTTP failures, and `SqliteStore` holds the feed in a file. The stub test stays the
deterministic unit test; this is the paid, non-deterministic half, so it lives outside pytest.

The board itself is `fedotmas_meta.presets.SwarmPreset`, so the same shape is what
`fedotmas_meta.compose` fills when `--compose` is passed.

```bash
uv sync --all-packages --extra pydantic-ai
echo 'OPENROUTER_API_KEY=...' >> .env
uv run python benchmarks/swarm/run.py --personas 40 --rounds 15
uv run python benchmarks/swarm/run.py --personas 40 --rounds 15 --compose --batch 10
uv run python benchmarks/swarm/run.py --personas 40 --rounds 15 --usd 0.001
```

A run writes its report to `benchmarks/out/<db>.json` and leaves the feed itself in the
SQLite file beside it, readable mid-run from another process.

## Swarm cost

`qwen/qwen3.8-flash` via OpenRouter, 2026-09-12. 40 personas, 15 rounds,
`ActivitySample(3, 8)`, `ConcurrencyLimit(3)`, `Retry(3, on=ModelHTTPError)`,
`max_tokens=800`, `temperature=0.9`, seed 7. Cost at the catalog price of $0.15/M input and
$0.47/M output.

| run | personas x rounds | requests | input | output | of which reasoning | USD | wall |
|---|---|---|---|---|---|---|---|
| smoke | 2 x 1 | 1 | 101 | 293 | 257 | 0.0002 | 17s |
| small | 10 x 3 | 10 | 1 832 | 2 959 | 2 439 | 0.0017 | 40s |
| small, no reasoning | 10 x 3 | 10 | 1 544 | 496 | 0 | 0.0005 | 22s |
| full | 40 x 15 | 76 | 56 693 | 29 914 | 26 428 | 0.0226 | 262s |
| full, no reasoning | 40 x 15 | 76 | 51 745 | 4 199 | 0 | 0.0097 | 92s |

Reading the full run: the throttle turned 600 possible persona-rounds into 76 requests
(activation per round 3..8, mean 5.1), and the concurrency cap held at 3 in flight
throughout. Per request that is ~750 input and ~390 output tokens, input growing with the
feed and flat past the 12-post window the digest keeps.

Three things the numbers say:

- **Reasoning dominates the bill.** 88% of output tokens on this model are hidden reasoning
  for a two-sentence post. `--no-reasoning` sends OpenRouter's `reasoning: {enabled: false}`
  and cuts cost 2.3x and wall time 2.9x with no visible loss on this task.
- **Retry never fired.** Zero 429s and zero 5xx across the 173 requests at concurrency 3, so the
  cap is conservative for this key rather than load-bearing. The two failures in the full run
  were `UnexpectedModelBehavior`: reasoning consumed the whole `max_tokens` budget before any
  output, which no retry can fix, hence `on=ModelHTTPError` rather than `on=Exception`. With
  reasoning off, zero failures.
- **The swarm is cheap.** 2.3 cents for a 40-agent, 15-round conversation; the run is bounded
  by latency, not by budget.

The feed a persona reads trails the store by one round: a superstep commits at its end, so
the digest written in round n is read in round n+1 and covers posts through round n-1.

## Composing the cast

`qwen/qwen3.7-flash` via OpenRouter, 2026-09-12, same 40 x 15 shape and same throttle, all
runs with reasoning off, priced at $0.03/M input and $0.13/M output. The composer and the
swarm meter separately, so the two columns below are two different bills.

| run | cast | compose calls | compose USD | requests | input | output | swarm USD | wall |
|---|---|---|---|---|---|---|---|---|
| handwritten | 40 by hand | | | 76 | 44 629 | 3 348 | 0.0018 | 49s |
| composed, one call | fell back to hand | 2 | 0.0007 | 76 | 44 408 | 3 406 | 0.0018 | 55s + 51s |
| composed, batch 10 | 40 composed | 4 | 0.0007 | 76 | 51 979 | 3 666 | 0.0020 | 50s + 48s |
| composed, batch 10, ranked | 40 composed | 4 | 0.0007 | 76 | 50 130 | 3 564 | 0.0020 | 49s + 52s |
| composed, batch 10, live queen | 40 + 5 seated | 4 | 0.0006 | 120 | 107 889 | 15 109 | 0.0052 | 43s + 170s |

What the composer runs showed:

- **One call cannot fill a large cast.** Asked for 40 personas in one answer the model
  returned 31 and then 38, twice in a row, and the run fell back to the handwritten voices.
  Asked for 20 it succeeded on the second try; for 10, on the first. In batches of 10, told
  which ids are already in the room, it filled all 40 with no rejected batch at all, twice.
  The failure is head count, not schema or truncation: the structured output validated every
  time, and the answers were well inside `max_tokens`.
- **Composition is cheap and does not scale with the run.** Four calls configure a run that
  then costs 76; the composer is about a third of the bill once and nothing per round.
- **The fallback is what makes it safe.** The run whose composition failed still produced a
  full 15-round conversation at exactly the handwritten cost, because `compose(fallback=...)`
  hands back the handwritten spec instead of raising.
- **Batching fixes head count, not variety.** 26 of the 40 composed ids share a word stem with
  another (`biosecurity_guardian` and `biosecurity_sentinel`, `adversarial_ml_researcher` and
  `adversarial_tester`). Naming the taken ids stops duplicate keys, not duplicate viewpoints.
- **Personal feeds are free.** `--ranked` gives every persona its own feed rule, ranking the
  same posts by how much of their vocabulary that persona already uses. That is 40 extra rules
  firing every round, all of them plain Python, and the provider bill does not move. It is the
  precondition for a room splitting instead of converging, which one shared wall cannot
  produce; the ranking is word overlap, not embeddings, so it costs nothing and knows nothing.

Every composed run above ended with no retry and 3 requests in flight at the peak, the same as
the handwritten baseline: composing the cast changes who is in the room, not how the room runs.

## Stopping on budget

`--usd`, `--tokens` and `--requests` put a `SpendLimit` in the onion under `ConcurrencyLimit`,
so the run ends when its money runs out rather than when its rounds do. Ten personas over a
nominal eight rounds, reasoning off, concurrency 2:

| cap | requests | input | output | USD | rounds | skipped | reason |
|---|---|---|---|---|---|---|---|
| `--requests 8` | 9 | 1 184 | 346 | 0.000081 | 7 of 8 | 12 | stalled |
| `--usd 0.00005` | 8 | 992 | 326 | 0.000072 | 7 of 8 | 13 | stalled |

Both runs stopped themselves. Two things the numbers show:

- **The cap is a floor, and the overshoot is the concurrency.** The request run asked for 8
  and made 9: the check happens before a call, so calls already in flight still land. At
  concurrency 2 the overshoot was 1, and it cannot exceed the cap.
- **A spent budget is not a failure.** Nothing is called past the cap, so no new facts are
  written, nothing re-arms and the run winds down on its own. `reason` is `stalled` only
  because these runs name a goal tag nothing ever writes; the feed and every post made before
  the cap are in the SQLite file exactly as they would be after a full run.

## The queen inside the loop

`--seats 6` keeps the composer on the board for the whole run: it reads the feed its own
personas wrote and each round may seat a new voice in a free seat, send one home, or do
nothing. The mechanism is described in `packages/fedotmas-meta/README.md`; what it did here:

- **It used the room.** Nine of its fourteen answers carried a change. It filled five of the
  six seats, sent one persona home, and left the room alone the other five rounds, which was
  the instruction.
- **It forgot which seats it had used, four times out of nine.** Twice it tried to seat a new
  character in `seat_0` after filling it, twice in `seat_3`. The fold keeps a seat's first
  occupant, so those were inert rather than rewriting a persona out from under posts it had
  already made. Without that rule the run would have silently swapped characters mid-stream.
- **A late arrival is nearly inaudible.** Five seated voices produced two posts between them.
  `ActivitySample` gives a newcomer the same odds as anyone else, so a voice seated at round 7
  competes with forty others for three to eight slots over the eight rounds it has left. If
  the queen's interventions are meant to change the conversation, a newcomer needs a louder
  `activity_level` than the room, or the room needs to be smaller.
- **It is not free.** Against the same run without it: input roughly doubled, output more than
  quadrupled, wall time tripled and the bill went from $0.0020 to $0.0052, for two extra posts.
  The queen fires every round, is exempt from the activity throttle as infrastructure, and its
  structured answer is the most expensive single call in the run.
- **One of its calls failed output validation** (`UnexpectedModelBehavior`, retries exhausted)
  and became an `error:queen` fact. The board is lenient, so the swarm carried on and the cast
  simply did not change that round. Nothing else in the run failed.

The mechanism works and costs nothing in the engine. Whether it earns its tokens at this shape
is a different question, and at forty personas the honest answer is no.
