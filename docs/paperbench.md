# Running PaperBench from the web UI

A full walkthrough: install everything PaperBench needs, start the web front
end, and score the bundled `classifier-free-guidance` example by uploading
its own `paper.pdf` and `rubric_branch.json`
(`benchmarks/paperbench/data/classifier-free-guidance/`) through the form —
no `data/` wiring, no CLI flags.

## 1. Install

One shared venv for the whole workspace, plus the two extras PaperBench
needs (`pydantic-ai` for the OpenRouter backend, `paperbench` for
`pymupdf`/PDF parsing):

```bash
uv sync --all-packages --extra pydantic-ai --group paperbench
```

Add an OpenRouter key to the repository's `.env`:

```bash
echo 'OPENROUTER_API_KEY=sk-or-...' >> .env
```

## 2. Start the web UI

```bash
cd web
deno install --frozen
deno task dev
```

Open the URL it prints (`http://localhost:5173` by default) and go to
**Compose**.

## 3. Configure the run

- **Target**: click **PaperBench** (instead of "Free topic").
- **Source**: click **PDF**, then upload
  `benchmarks/paperbench/data/classifier-free-guidance/paper.pdf` under
  **Paper PDF**.
- **Rubric branch JSON (optional)**: upload
  `benchmarks/paperbench/data/classifier-free-guidance/rubric_branch.json`.
  This branch is filtered to the paper's Code Development leaves only — see
  its own `README.md` in that same directory for what that does and doesn't
  grade.
- **Model**: any OpenRouter id from the list (e.g. `openrouter:qwen/qwen3.7-flash`).
- **Stop after**: pick an axis (dollars/tokens/requests) and an amount above
  zero — required for PaperBench, the run is refused with all three at zero.
- **Max tokens**: the judge answers with one verdict per rubric leaf in a
  single reply, so the bigger the rubric, the higher this needs to be set —
  well above the field's default for the bundled example's 70 leaves, and
  higher still for a larger `rubric_branch.json` of your own. Too low and the
  judge step exhausts its output retries instead of finishing.

## 4. Run and read the result

Start the run and watch it on the **Swarm** screen; PaperBench reuses the
same live influence graph and round scrubber the free-topic path uses.  When
it finishes, **Runs** shows the score, and the run's own page breaks it down
per rubric leaf.

This is the same pipeline `benchmarks/paperbench/run.py` runs from the
command line — see its own `README.md` for the CLI flags, the pipeline's
shape (swarm → judge), and how to point it at a paper of your own instead of
the bundled example.
