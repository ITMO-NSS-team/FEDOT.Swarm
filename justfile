venv:
    uv sync
    cp -n .env.example .env 2>/dev/null || true

venv-dev:
    uv sync --group dev
    uv run prek install
    @echo "Dev environment ready"

docs:
    uv run --group docs mkdocs serve

test-fedotmas:
    uv run pytest packages/fedotmas/tests

test-fedotmas-llm:
    uv run pytest packages/fedotmas-llm/tests

# Everything the pull request has to pass: ruff, ty, pytest (engine, adapters, paperbench) and the web checks.
verify:
    uv run ruff check packages/fedotmas-llm packages/fedotmas-meta benchmarks/paperbench
    uv run ruff format --check packages/fedotmas-llm packages/fedotmas-meta benchmarks/paperbench
    uv run ty check packages/ benchmarks/paperbench
    uv run pytest -q
    cd web && deno task verify

# Front end in the browser against a fake runner (no model, no money).
e2e:
    cd web/e2e && npm ci && npx playwright install chromium && npx playwright test

# A short real run on the bundled paper with OpenCode and marker from the host (about $0.10).
smoke:
    uv run --extra pydantic-ai --extra opencode --group paperbench \
      python benchmarks/paperbench/run.py --paper classifier-free-guidance \
      --paper-pdf benchmarks/paperbench/data/classifier-free-guidance/paper.pdf \
      --personas 2 --rounds 2 --round-minutes 4 --steps 16 --concurrency 2 --usd 0.3 \
      --workdir /tmp/pb-smoke/workdir --report /tmp/pb-smoke/report.json --status /tmp/pb-smoke/status.json

# The dev front end on http://127.0.0.1:5173.
web:
    cd web && deno task dev

# A PaperBench package from openai/frontier-evals into benchmarks/paperbench/data/<paper>.
fetch-paper paper="stochastic-interpolants":
    uv run --group paperbench python benchmarks/paperbench/fetch_paper.py --paper {{paper}}

# Turns a finished run into a fixture: the e2e replay (default) or, with a run.json, the demo seed.
fixture report status workdir dest="web/tests/fixtures/paperbench" run="":
    web/e2e/make_fixture.sh {{report}} {{status}} {{workdir}} {{dest}} {{run}}

# Registers the recorded demo run in the front end's registry, so Runs is never empty.
seed-demo:
    cd web && deno run -A scripts/seed.ts tests/fixtures/demo

# Container image for this machine's architecture, then for amd64 (built with emulation).
build:
    docker build -t fedotmas-swarm .

build-amd64:
    docker build --platform linux/amd64 -t fedotmas-swarm:amd64 .

# The demo on http://localhost:8000 with the key from .env.
up:
    docker compose up --build

down:
    docker compose down
