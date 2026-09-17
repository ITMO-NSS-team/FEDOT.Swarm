# PaperBench (Code-Dev, one branch)

Not the benchmark: one deliberately small slice of it.
[PaperBench](https://arxiv.org/abs/2504.01848) grades a paper reproduction
against a rubric tree co-written with the paper's authors; the full protocol
trains the paper's models for real and costs on the order of $400-500 per paper
plus a GPU-day. This script keeps the shape of that grading (a rubric, per-leaf
verdicts, a weighted score) but only asks for code, never runs it, and only
grades one self-contained branch of one paper's rubric rather than the whole
tree.

`data/<paper>/` holds a paper's inputs — `rubric_branch.json` (one branch of the
real rubric, unmodified) is the only piece every paper needs; the rest is
optional, and which of it exists varies per paper. `paper.md` is the full paper,
cleaned once by `parse_tex.py` (from a `.tex` file or a whole arXiv-style source
folder) or `parse_pdf.py` (from a PDF, see below); `run.py` prefers it when
present. `paper_summary.md` is a hand-written fallback for a paper that has
neither — a summary of the method, not the paper itself. `blacklist.txt`, when
present, names the paper's own repository so the coder is kept out of it rather
than copying it.

`run.py` runs the same swarm `benchmarks/swarm/run.py` does —
`packages/fedotmas-meta/src/fedotmas_meta/presets/_swarm.py`'s `SwarmPreset`, a
cast posting to one shared feed over a run of rounds, `ActivitySample` picking
who speaks each round, an optional queen recasting mid-run, an optional
meta-agent (`compose()`) writing the cast — unmodified. The only difference from
the topic-debate benchmark is what the room is for: the "topic" a persona reads
is this paper's rubric branch, not free text, and its conduct is "post your next
revision of the code", not "post a one-line argument"
(`SwarmPreset(conduct=...)`, a small addition to the preset to make that
swappable). After the round budget, each persona's _last_ post is taken as its
code and a judge scores every one against the branch's requirements, by reading
it, never running it; the run keeps the highest-scoring one and rolls its marks
up by the rubric's own weights.

Every session — every persona, the queen, compose(), the judge — runs through
`fedotmas_llm.adapters.pydantic_ai.PydanticAI`, the same metered OpenRouter
backend `benchmarks/swarm/run.py` runs on: `--usd`/`--tokens`/`--requests` cap
the run's spend the way they do there, and `--model` takes an OpenRouter model
id (e.g. `openrouter:qwen/qwen3.7-flash`). Each call is also bounded by
`--timeout` individually (there is no whole-run wall-clock cap, only per-call),
so the web UI refuses to start a run with all three of `--usd`/`--tokens`/
`--requests` left at zero; the CLI itself does not enforce that, so pass at
least one by hand.

No separate venv: this script lives in the same workspace
`uv sync
--all-packages` sets up, plus two extras — `fedotmas-llm`'s
`pydantic-ai` extra and this project's own `paperbench` dependency group
(`pymupdf`, only needed for `--paper-pdf`/`parse_pdf.py`):

```bash
uv sync --all-packages --extra pydantic-ai --group paperbench
echo 'OPENROUTER_API_KEY=...' >> .env
uv run python benchmarks/paperbench/run.py --paper classifier-free-guidance \
  --paper-pdf benchmarks/paperbench/data/classifier-free-guidance/paper.pdf \
  --personas 3 --rounds 4 --compose --usd 0.05
```

`data/classifier-free-guidance/` is a bundled, ready-to-run example — see its
own [README](data/classifier-free-guidance/README.md) for exactly what it is
and, importantly, what it is not: its rubric is filtered to Code Development
leaves only, for a quick smoke test, not a real PaperBench grade. It ships only
the PDF (`--paper-pdf` above, re-parsed fresh each run), no pre-parsed
`paper.md` cached alongside it.

`--usd`/`--tokens` are checked against `OPENROUTER_PRICES` in `run.py` — real
OpenRouter catalog prices (USD per 1M tokens) for the models
`web/lib/types.ts`'s `models` list offers — resolved by `--model`;
`--price-in`/`--price-out` override that table entry, or fill in for a model not
in it. `--retries` (default 3) retries a call on a transient HTTP error (a 429
or a 5xx), the same `Retry` plugin `benchmarks/swarm/run.py` uses.
`--max-tokens` (default 4000) caps a single reply's length — a persona reposts a
whole file every round and the judge answers with one verdict per rubric leaf in
one structured reply, so a rubric with many leaves needs this raised well above
the default or the judge can exhaust pydantic-ai's output retries on a truncated
reply ("Exceeded maximum output retries").

To run from the full paper instead of the summary, drop its LaTeX source at
`data/<paper>/paper_tex/` (or a single file at `data/<paper>/paper.tex`) and
parse once per paper:

```bash
uv run python benchmarks/paperbench/parse_tex.py --paper <paper>
uv run python benchmarks/paperbench/run.py --paper <paper> --usd 0.05
```

`parse_tex.py` writes `data/<paper>/paper.md`; `run.py` prefers `paper.md` when
present and records which source it used as `paperSource` in the report.

When the LaTeX source is not at hand, `parse_pdf.py` is the fallback: it reads a
PDF straight (no OCR — arXiv's own PDFs are born-digital, a real text layer
already), and strips running headers/footers by frequency (a line repeated on
most pages is noise, not argument). Math and layout survive worse than they do
from LaTeX — inline formulas come out as the renderer's own unicode glyphs, not
`$...$` source — so prefer `parse_tex.py` whenever the source is available.

```bash
uv run --group paperbench python benchmarks/paperbench/parse_pdf.py \
  --paper <paper> --source <paper.pdf>
uv run python benchmarks/paperbench/run.py --paper <paper> --usd 0.05
```

`data/classifier-free-guidance/` uses `--paper-pdf` directly instead (see above)
rather than caching a pre-parsed `paper.md`, so the parse step above is only
needed for a paper of your own.

The web UI starts runs straight from uploads, without touching `data/`: a rubric
branch JSON, hand-typed criteria in the form, or both (at least one is
required); a paper source either a LaTeX source (one `.tex` file or a whole
folder of them) or, when that is not at hand, a single PDF. Uploaded files land
beside the run, and `run.py` takes the same inputs as flags: `--paper-tex` (a
file or a directory, cleaned at startup), `--paper-pdf` (a PDF, cleaned the same
way), `--paper-md` (already parsed markdown), `--rubric` and `--blacklist`. A
bad rubric fails fast with the reason named, both in the UI and on the command
line; custom criteria typed into the form are folded into the rubric branch on
the server before it reaches `run.py` — `run.py` itself only ever sees one
finished branch JSON, the same shape either way. The UI's own spend cap and
max-tokens field map onto the same `--usd`/`--tokens`/`--requests`/
`--max-tokens` flags above.
