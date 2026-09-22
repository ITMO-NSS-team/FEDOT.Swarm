#!/usr/bin/env bash
# Stands in for `uv run ... benchmarks/paperbench/run.py` under the end-to-end tests: takes
# the same flags, replays the recorded fixture into the run's workdir, walks the status
# through the real phases, and writes the fixture's report. FAKE_FAIL=1 fails instead, with
# a provider key in the traceback, so the tests can check that the log tail is redacted.
# A `fail` file in $FAKE_CONTROL does the same; a `slow` file there holds the swarm phase
# open for 30 seconds, so stop and delete can be exercised.
set -euo pipefail
fixture="${FAKE_FIXTURE:-$(dirname "$0")/../tests/fixtures/paperbench}"
workdir=""
report=""
status=""
while [ $# -gt 0 ]; do
  case "$1" in
    --workdir) workdir="$2"; shift 2 ;;
    --report) report="$2"; shift 2 ;;
    --status) status="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "$workdir" ] && [ -n "$report" ] && [ -n "$status" ] || { echo "fake_runner: missing --workdir/--report/--status" >&2; exit 2; }
mkdir -p "$workdir" "$(dirname "$status")"
echo $$ > "$status.pid"
trap 'printf "{\"step\": \"stopped\", \"percent\": 100}" > "$status"; rm -f "$status.pid"; exit 143' TERM INT
now() { python3 -c 'import time; print(time.time())'; }
printf '{"step": "parsing", "percent": 2, "engine": "marker", "at": %s}' "$(now)" > "$status"
sleep 1
control="${FAKE_CONTROL:-/nonexistent}"
if [ "${FAKE_FAIL:-}" = "1" ] || [ -f "$control/fail" ]; then
  echo "Traceback (most recent call last):" >&2
  echo "  File \"run.py\", line 1, in <module>" >&2
  echo "    headers={'Authorization': 'Bearer sk-or-v1-deadbeefdeadbeefdeadbeef'}" >&2
  echo "RuntimeError: provider refused the request" >&2
  printf '{"step": "failed", "percent": 100, "error": "provider refused the request (OPENROUTER_API_KEY=sk-or-v1-deadbeefdeadbeefdeadbeef)"}' > "$status"
  rm -f "$status.pid"
  exit 1
fi
cp -R "$fixture/workdir/." "$workdir/"
printf '{"step": "swarm", "percent": 30, "round": 1, "rounds": 2, "at": %s}' "$(now)" > "$status"
if [ -f "$control/slow" ]; then sleep 30 & else sleep 2 & fi
wait $!
printf '{"step": "judge", "percent": 60, "at": %s}' "$(now)" > "$status"
sleep 1
python3 - "$fixture/report.json" "$report" "$workdir" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
report["workdir"] = sys.argv[3]
report["kept"] = {"voice": report.get("kept", {}).get("voice", ""), "dir": sys.argv[3] + "/solution"}
for f in report.get("files", []):
    f["absPath"] = sys.argv[3] + "/solution/" + f["path"]
json.dump(report, open(sys.argv[2], "w"), indent=2)
EOF
printf '{"step": "done", "percent": 100, "at": %s}' "$(now)" > "$status"
rm -f "$status.pid"
