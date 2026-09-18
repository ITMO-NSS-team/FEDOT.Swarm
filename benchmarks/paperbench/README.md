# PaperBench (Code Development, one branch)

Not the benchmark: one deliberately small slice of it. [PaperBench](https://arxiv.org/abs/2504.01848) grades a paper reproduction against a rubric tree co-written with the paper's authors; the full protocol trains the paper's models for real and costs on the order of $400-500 per paper plus a GPU-day. This script keeps the shape of that grading (a rubric, per-leaf verdicts, a weighted score) but only asks for code, never runs it, and only grades the Code Development branch of one paper's rubric rather than the whole tree.

## Running

```bash
uv sync --all-packages --extra pydantic-ai --extra opencode --group paperbench
echo 'OPENROUTER_API_KEY=...' >> .env
uv run --extra pydantic-ai --extra opencode --group paperbench \
  python benchmarks/paperbench/run.py --paper classifier-free-guidance \
  --paper-pdf benchmarks/paperbench/data/classifier-free-guidance/paper.pdf \
  --personas 2 --rounds 2 --round-minutes 4 --steps 16 --usd 0.3
```

OpenCode has to be on the PATH (`--opencode-bin` or `OPENCODE_BIN` otherwise). `data/classifier-free-guidance/` is the bundled example (see its README); `fetch_paper.py --paper stochastic-interpolants` fetches a PaperBench package from openai/frontier-evals into `data/<paper>/`, with the rubric filtered to its Code Development leaves.
