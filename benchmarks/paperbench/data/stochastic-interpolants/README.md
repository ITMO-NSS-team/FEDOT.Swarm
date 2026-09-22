# stochastic-interpolants (Code Development only)

Fetched by `fetch_paper.py` from the PaperBench package in openai/frontier-evals. `rubric_branch.json` keeps the 58 Code Development leaves of the 69-leaf rubric, the ones a judge that reads code and never runs it can grade; `rubric.json` is the whole tree. `paper.upstream.md` is the authors' own markdown, kept for comparison with what `parse_pdf.py` makes of `paper.pdf`.

```bash
uv run --extra pydantic-ai --extra opencode --group paperbench python benchmarks/paperbench/run.py --paper stochastic-interpolants --paper-pdf benchmarks/paperbench/data/stochastic-interpolants/paper.pdf --usd 1.2
```
