# Results

n = 100, seed = 7, 3 runs per cell (mean±sd). Executor = model column. Selector judge = fixed gpt-4o-mini. Random = analytic expected accuracy of a uniform pattern pick. Best fixed = the single best pattern's mean accuracy (one pattern committed across runs). Oracle per-task = stable per-item argmax across runs. MathQA absolute accuracy is capped (~20% of items carry a 5th option the scoring schema cannot express).

## Accuracy

### GSM8K

| configuration | gpt-oss-20b | ministral-8b | llama-3.1-8b |
|---|---|---|---|
| single | 0.94±0.02 | 0.94±0.01 | 0.80±0.05 |
| chain | 0.84±0.01 | 0.90±0.02 | 0.61±0.07 |
| debate | 0.89±0.02 | 0.95±0.01 | 0.61±0.05 |
| eval_optimizer | 0.95±0.01 | 0.95±0.01 | 0.75±0.04 |
| orchestrator | 0.90±0.01 | 0.80±0.02 | 0.69±0.02 |
| blackboard | 0.95±0.01 | 0.90±0.02 | 0.60±0.04 |
| random (expected) | 0.91±0.00 | 0.91±0.00 | 0.67±0.00 |
| best fixed | 0.95 (blackboard) | 0.95 (debate) | 0.80 (single) |
| oracle per-task | 0.98 | 0.96 | 0.92 |
| selector | 0.89 | 0.94 | 0.74 |

### MMLU

| configuration | gpt-oss-20b | ministral-8b | llama-3.1-8b |
|---|---|---|---|
| single | 0.89±0.02 | 0.83±0.01 | 0.63±0.01 |
| chain | 0.89±0.02 | 0.78±0.02 | 0.58±0.02 |
| debate | 0.88±0.02 | 0.83±0.01 | 0.61±0.01 |
| eval_optimizer | 0.89±0.01 | 0.81±0.02 | 0.65±0.05 |
| orchestrator | 0.82±0.06 | 0.79±0.02 | 0.59±0.02 |
| blackboard | 0.88±0.02 | 0.82±0.02 | 0.61±0.08 |
| random (expected) | 0.87±0.00 | 0.81±0.00 | 0.61±0.01 |
| best fixed | 0.89 (eval_optimizer) | 0.83 (debate) | 0.65 (eval_optimizer) |
| oracle per-task | 0.95 | 0.90 | 0.84 |
| selector | 0.88 | 0.78 | 0.63 |

### MathQA

| configuration | gpt-oss-20b |
|---|---|
| single | 0.73±0.01 |
| chain | 0.70±0.01 |
| debate | 0.70±0.03 |
| eval_optimizer | 0.70±0.01 |
| orchestrator | 0.71±0.02 |
| blackboard | 0.69±0.03 |
| random (expected) | 0.71±0.00 |
| best fixed | 0.73 (single) |
| oracle per-task | 0.74 |
| selector | — |

### LogiQA

| configuration | gpt-oss-20b |
|---|---|
| single | 0.77±0.04 |
| chain | 0.64±0.04 |
| debate | 0.76±0.04 |
| eval_optimizer | 0.79±0.01 |
| orchestrator | 0.70±0.02 |
| blackboard | 0.72±0.02 |
| random (expected) | 0.73±0.01 |
| best fixed | 0.79 (eval_optimizer) |
| oracle per-task | 0.89 |
| selector | 0.71±0.03 |

## Tokens per task

### GSM8K

| pattern | gpt-oss-20b | ministral-8b | llama-3.1-8b |
|---|---|---|---|
| single | 398 | 528 | 324 |
| chain | 972 | 685 | 599 |
| debate | 1226 | 1839 | 1095 |
| eval_optimizer | 1019 | 803 | 876 |
| orchestrator | 1893 | 276848 | 11188 |
| blackboard | 1692 | 2087 | 1293 |

### MMLU

| pattern | gpt-oss-20b | ministral-8b | llama-3.1-8b |
|---|---|---|---|
| single | 849 | 1026 | 584 |
| chain | 1749 | 1797 | 991 |
| debate | 2892 | 4236 | 2291 |
| eval_optimizer | 2768 | 7946 | 2682 |
| orchestrator | 2679 | 65978 | 15626 |
| blackboard | 3138 | 5595 | 2590 |

### MathQA

| pattern | gpt-oss-20b |
|---|---|
| single | 870 |
| chain | 1856 |
| debate | 3253 |
| eval_optimizer | 3499 |
| orchestrator | 2183 |
| blackboard | 3178 |

### LogiQA

| pattern | gpt-oss-20b |
|---|---|
| single | 1481 |
| chain | 2682 |
| debate | 4104 |
| eval_optimizer | 6248 |
| orchestrator | 3444 |
| blackboard | 4952 |

## Per-task headroom — gpt-oss-20b (one executor across difficulty)

| benchmark | single | best fixed | oracle per-task | headroom |
|---|---|---|---|---|
| GSM8K | 0.94 | 0.95 | 0.98 | +3pp |
| MMLU | 0.89 | 0.89 | 0.95 | +6pp |
| LogiQA | 0.77 | 0.79 | 0.89 | +9pp |
| MathQA (capped) | 0.73 | 0.73 | 0.74 | +1pp |

_Selector single-run except LogiQA/gpt-oss-20b (3 runs); MathQA selector not run. Figures: benchmarks/figures/{headroom,pareto,selector}.png._

## Swarm cost — qwen3.8-flash (40 agents, 15 rounds)

Not accuracy: what a throttled swarm of prompt rules costs on a real provider. Setup and
commentary in `benchmarks/swarm/README.md`; run with `benchmarks/swarm/run.py`.

| run | personas x rounds | requests | input | output | of which reasoning | USD | wall |
|---|---|---|---|---|---|---|---|
| smoke | 2 x 1 | 1 | 101 | 293 | 257 | 0.0002 | 17s |
| small | 10 x 3 | 10 | 1 832 | 2 959 | 2 439 | 0.0017 | 40s |
| small, no reasoning | 10 x 3 | 10 | 1 544 | 496 | 0 | 0.0005 | 22s |
| full | 40 x 15 | 76 | 56 693 | 29 914 | 26 428 | 0.0226 | 262s |
| full, no reasoning | 40 x 15 | 76 | 51 745 | 4 199 | 0 | 0.0097 | 92s |

_`openrouter:qwen/qwen3.8-flash`, 2026-09-12, seed 7, `ActivitySample(3, 8)` +
`ConcurrencyLimit(3)` + `Retry(3, on=ModelHTTPError)` over `SqliteStore`. Priced at the
catalog's $0.15/M input, $0.47/M output. ActivitySample turned 600 possible persona-rounds
into 76 requests; no 429 or 5xx occurred, so Retry never fired._

## Composing the swarm — qwen3.7-flash (40 agents, 15 rounds)

Whether a meta-agent can write the cast the swarm above runs by hand. Commentary in
`benchmarks/swarm/README.md`; run with `benchmarks/swarm/run.py --compose --batch 10`.

| run | cast | compose calls | compose USD | requests | input | output | swarm USD | wall |
|---|---|---|---|---|---|---|---|---|
| handwritten | 40 by hand | | | 76 | 44 629 | 3 348 | 0.0018 | 49s |
| composed, one call | fell back to hand | 2 | 0.0007 | 76 | 44 408 | 3 406 | 0.0018 | 55s + 51s |
| composed, batch 10 | 40 composed | 4 | 0.0007 | 76 | 51 979 | 3 666 | 0.0020 | 50s + 48s |
| composed, batch 10, ranked | 40 composed | 4 | 0.0007 | 76 | 50 130 | 3 564 | 0.0020 | 49s + 52s |
| composed, batch 10, live queen | 40 + 5 seated | 4 | 0.0006 | 120 | 107 889 | 15 109 | 0.0052 | 43s + 170s |

_`openrouter:qwen/qwen3.7-flash`, 2026-09-12, reasoning off, seed 7, same `ActivitySample(3, 8)`
+ `ConcurrencyLimit(3)` + `Retry(3, on=ModelHTTPError)` over `SqliteStore` as the run above.
Priced at the catalog's $0.03/M input, $0.13/M output. Asked for all 40 personas in one answer
the model returned 31 and then 38 and the run fell back to the handwritten cast; asked for 10
at a time it filled all 40 with nothing rejected. Composing costs four calls against the run's
76 and does not grow with the number of rounds. The last row keeps the composer on the board
(`--seats 6`): it changed the cast in 9 of its 14 answers and filled 5 seats, but a voice
seated mid-run competes with 40 others for 3 to 8 slots a round and the five of them managed
two posts between them, at 2.6x the cost of the same run without it._

## Stopping on budget — qwen3.7-flash (10 agents, 8 rounds)

Whether a run can be told what it may spend instead of how many rounds it may take. Commentary
in `benchmarks/swarm/README.md`; run with `benchmarks/swarm/run.py --usd 0.001`.

| cap | requests | input | output | USD | rounds | skipped | reason |
|---|---|---|---|---|---|---|---|
| `--requests 8` | 9 | 1 184 | 346 | 0.000081 | 7 of 8 | 12 | stalled |
| `--usd 0.00005` | 8 | 992 | 326 | 0.000072 | 7 of 8 | 13 | stalled |

_`openrouter:qwen/qwen3.7-flash`, 2026-09-12, reasoning off, seed 7, concurrency 2, priced at
$0.03/M input and $0.13/M output. `SpendLimit` sits under `ConcurrencyLimit` and checks the cap
before each call, so calls already in flight still land and the overshoot is bounded by the
concurrency (1 request here). Past the cap no node is called at all, so nothing is written,
nothing re-arms and the run ends itself with the feed intact._
