# PaperBench (Code-Dev, one branch)

Not the benchmark: one deliberately small slice of it. [PaperBench](https://arxiv.org/abs/2504.01848)
grades a paper reproduction against a rubric tree co-written with the paper's authors; the
full protocol trains the paper's models for real and costs on the order of $400-500 per
paper plus a GPU-day. This script keeps the shape of that grading (a rubric, per-leaf
verdicts, a weighted score) but only asks for code, never runs it, and only grades one
self-contained branch of one paper's rubric rather than the whole tree.

`data/<paper>/` holds `paper_summary.md` (a summary of the method, not the paper itself),
`rubric_branch.json` (one branch of the real rubric, unmodified) and `blacklist.txt` (the
paper's own repository, kept out of the coder's reach so it writes the implementation
rather than copying it). `parse_tex.py` cleans the paper's LaTeX source — a single `.tex`
file, or a whole arXiv-style source folder (`main.tex` plus whatever it `\input`s) — into
`paper.md`; when `paper.md` exists, `run.py` feeds the swarm the full paper instead of the
summary. Nothing beyond the standard library is needed: LaTeX source is already plain
text, there is no OCR step to install.

`run.py` runs the same swarm `benchmarks/swarm/run.py` does —
`packages/fedotmas-meta/src/fedotmas_meta/presets/_swarm.py`'s `SwarmPreset`, a cast
posting to one shared feed over a run of rounds, `ActivitySample` picking who speaks each
round, an optional queen recasting mid-run, an optional meta-agent (`compose()`) writing
the cast — unmodified. The only difference from the topic-debate benchmark is what the
room is for: the "topic" a persona reads is this paper's rubric branch, not free text, and
its conduct is "post your next revision of the code", not "post a one-line argument"
(`SwarmPreset(conduct=...)`, a small addition to the preset to make that swappable). After
the round budget, each persona's *last* post is taken as its code and a judge scores every
one against the branch's requirements, by reading it, never running it; the run keeps the
highest-scoring one and rolls its marks up by the rubric's own weights.

Every session — every persona, the queen, compose(), the judge — runs through
`ClaudeCodeLLM`, an adapter in `run.py` for `fedotmas_llm`'s one-method `LLM` protocol,
backed by the harness's `claude-code` provider: it drives your own logged-in Claude Code
CLI rather than a metered API key, so the whole swarm runs on your existing subscription
the same way the topic-debate swarm runs on OpenRouter through `PydanticAI` — just a
different backend behind the same seam. (`claude-acp` is the newer, non-deprecated
provider, but needs the separate `@agentclientprotocol/claude-agent-acp` npm package;
`claude-code` needs only the `claude` CLI itself, which is enough here since nothing uses
MCP extensions.)

The harness's Python client needs 3.12 while the rest of this workspace holds at 3.11, so
this script gets its own venv rather than joining `uv sync`:

```bash
cd benchmarks/paperbench
uv venv --python 3.12
uv pip install --python .venv/bin/python -e <path-to-the-sdk> \
  -e ../../packages/fedotmas -e ../../packages/fedotmas-llm -e ../../packages/fedotmas-meta
claude auth login   # once, if you have not already
.venv/bin/python run.py --paper stochastic-interpolants --personas 3 --rounds 4 --compose
```

Needs the harness's own CLI binary on `PATH` (built from its source) and `claude`
installed and logged in.

Every LLM call runs through `claude-code` by default — your own subscription, no metered
key. Pass `--backend openrouter` to run the swarm on OpenRouter instead, the same metered
backend `benchmarks/swarm/run.py` uses, then `--model` takes an OpenRouter model id (e.g.
`openrouter:qwen/qwen3.7-flash`) rather than a claude CLI alias, and `--usd`/`--tokens`/
`--requests` cap the run's spend. Needs the `pydantic-ai` extra installed into this venv
and `OPENROUTER_API_KEY` in the repo's `.env`:

```bash
uv pip install --python .venv/bin/python -e "../../packages/fedotmas-llm[pydantic-ai]"
.venv/bin/python run.py --paper stochastic-interpolants --backend openrouter \
  --model openrouter:qwen/qwen3.7-flash --usd 0.01
```

To run from the full paper instead of the summary, drop its LaTeX source at
`data/<paper>/paper_tex/` (or a single file at `data/<paper>/paper.tex`) and parse once
per paper:

```bash
.venv/bin/python benchmarks/paperbench/parse_tex.py --paper stochastic-interpolants
.venv/bin/python benchmarks/paperbench/run.py --paper stochastic-interpolants
```

`parse_tex.py` writes `data/<paper>/paper.md`; `run.py` prefers `paper.md` when present
and records which source it used as `paperSource` in the report.

The web UI also starts runs straight from uploads (the paper's LaTeX source — one `.tex`
file or a whole folder of them — plus a rubric branch JSON), without touching `data/`.
Uploaded files land beside the run, and `run.py` takes the same inputs as flags:
`--paper-tex` (a file or a directory, cleaned at startup), `--paper-md` (already parsed
markdown), `--rubric` and `--blacklist`. A bad rubric fails fast with the reason named,
both in the UI and on the command line. The UI's own backend switch and spend cap map onto
the same `--backend`/`--usd`/`--tokens`/`--requests` flags above.
