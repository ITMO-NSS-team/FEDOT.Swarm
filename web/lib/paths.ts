import { join, resolve } from "node:path";
import { homedir } from "node:os";

/** Where runs are kept: one `<id>.db` fact store, one `<id>.db.spec.json` cast and one
 * `<id>.db.json` report per run, all written by `benchmarks/swarm/run.py`. */
export function dataDirectory() {
  return resolve(Deno.env.get("FEDOTMAS_WEB_DATA_DIR") ?? "./var");
}

/** The repository root, so the server can spawn `uv run` in it. */
export function projectRoot() {
  return resolve(Deno.env.get("FEDOTMAS_ROOT") ?? "..");
}

export function runId(id: string) {
  if (!/^[a-zA-Z0-9_-]{1,64}$/.test(id)) throw new TypeError("Invalid run id");
  return id;
}

export function runPaths(id: string) {
  const base = join(dataDirectory(), "runs", runId(id));
  return {
    db: `${base}.db`,
    spec: `${base}.db.spec.json`,
    report: `${base}.db.json`,
    usage: `${base}.db.usage.jsonl`,
    log: `${base}.log`,
  };
}

export function newRunId() {
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
  return `${stamp}-${crypto.randomUUID().slice(0, 8)}`;
}

/** Outside the repository on purpose: a run's workdir can grow arbitrarily large (a
 * cast's whole `SqliteStore` plus every judged variant), so it lives in a user cache
 * directory rather than inside the checkout. */
function paperWorkDirectory() {
  return resolve(
    Deno.env.get("FEDOTMAS_PAPERBENCH_WORKDIR") ??
      join(homedir(), ".cache", "fedotmas-paperbench"),
  );
}

/** One `<id>.json` report and one `<id>/` workdir per PaperBench run, written by
 * `benchmarks/paperbench/run.py`. The report/status/log stay under the repo's own data
 * directory; only the workdir (where the harness actually reads and writes) moves out. The
 * swarm's own fact store and the cast `run.py` wrote before starting live inside that
 * workdir — same `<db>` / `<db>.spec.json` convention `benchmarks/swarm/run.py` uses, so
 * the same graph-building code can read either. */
export function paperPaths(id: string) {
  const base = join(dataDirectory(), "paperbench", runId(id));
  const workdir = join(paperWorkDirectory(), runId(id));
  const db = join(workdir, "swarm.db");
  return {
    report: `${base}.json`,
    status: `${base}.status.json`,
    workdir,
    log: `${base}.log`,
    db,
    spec: `${db}.spec.json`,
    /** Same JSONL-per-superstep shape `runPaths().usage` is, so the graph endpoint and
     * `SwarmView`'s spend meter read either the same way. */
    usage: `${db}.usage.jsonl`,
    /** Uploaded `tex/` (a LaTeX source tree) and `rubric_branch.json`, when the run was
     * started with files instead of a paper from `benchmarks/paperbench/data`. Fixed
     * names and sanitized relative paths, never the client's own, so nothing uploaded
     * can escape this directory. */
    inputs: `${base}.inputs`,
  };
}
