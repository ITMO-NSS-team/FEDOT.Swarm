import { join, resolve } from "node:path";

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
