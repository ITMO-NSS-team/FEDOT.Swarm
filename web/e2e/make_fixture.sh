#!/usr/bin/env bash
# Turns a finished PaperBench run into the fixture the end-to-end tests replay, or the demo
# `seed.ts` restores:
#   make_fixture.sh <report.json> <status.json> <workdir> [dest] [run.json]
# Git metadata, virtualenvs and caches are left out, and the paper copies are cut to their
# first lines so the fixture stays small enough to commit.
set -euo pipefail
report="$1"
status="$2"
workdir="$3"
dest="${4:-$(dirname "$0")/../tests/fixtures/paperbench}"
rm -rf "$dest"
mkdir -p "$dest/workdir"
cp "$report" "$dest/report.json"
cp "$status" "$dest/status.json"
[ -n "${5:-}" ] && cp "$5" "$dest/run.json"
rsync -a --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
  --exclude '__pycache__' --exclude '*.db-wal' --exclude '*.db-shm' \
  --exclude 'opencode.log' "$workdir/" "$dest/workdir/"
find "$dest/workdir" -name 'paper.md' -print0 | while IFS= read -r -d '' f; do
  head -c 6000 "$f" > "$f.cut" && printf '\n\n[cut for the fixture]\n' >> "$f.cut" && mv "$f.cut" "$f"
done
du -sh "$dest"
