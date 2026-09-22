# classifier-free-guidance (Code Development only)

A bundled example for a quick, working `run.py` smoke test — **not a full
PaperBench rubric**. `rubric_branch.json` here is filtered down to only the
"Code Development" leaves of the paper's real rubric tree (70 of them): the ones
a judge that only reads code, never runs it, can actually grade. The paper's
"Code Execution" and "Result Analysis" leaves (verifying that training actually
ran, that a metric came out within some range) are left out on purpose — nothing
in this pipeline executes anything, so those leaves can never be honestly passed
or failed here.

Contents:

- `paper.pdf` — _"Stay on topic with Classifier-Free Guidance"_ (Sanchez,
  Spangher, Fan, Levi, Biderman), straight from its source PDF.
- `rubric_branch.json` — the 70-leaf Code Development branch described above.

No pre-parsed `paper.md` here on purpose — this example works straight from the
PDF, so `--paper-pdf` is required (`run.py` never reads `paper.pdf` on its own;
without either `--paper-pdf` or a `paper.md`/`paper_summary.md` already in this
folder, it has no paper text to load):

```bash
uv run python benchmarks/paperbench/run.py --paper classifier-free-guidance \
  --paper-pdf benchmarks/paperbench/data/classifier-free-guidance/paper.pdf \
  --personas 3 --rounds 4 --compose --usd 0.05
```

There is no `blacklist.txt` here (the paper's own repository is unknown), so
nothing is named as off-limits beyond the generic instruction in `run.py`'s own
`paper_topic()`.
