#!/usr/bin/env bash
# Runs the web front end inside the image. State lives under /data (a volume): the run
# registry and reports in /data/var, run workdirs in /data/workdir, and the home of the
# non-root user, which is where OpenCode keeps its session storage.
set -euo pipefail
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY is required: put it in .env next to compose.yaml}"
mkdir -p /data/var /data/workdir /data/home
export HOME=/data/home
export FEDOTMAS_ROOT=/app
export FEDOTMAS_WEB_DATA_DIR=/data/var
export FEDOTMAS_PAPERBENCH_WORKDIR=/data/workdir
exec deno serve -A --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" /app/web/_fresh/server.js
