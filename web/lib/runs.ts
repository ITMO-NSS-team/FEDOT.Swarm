import { DatabaseSync } from "node:sqlite";
import { dirname, join } from "node:path";
import { dataDirectory, newRunId, projectRoot, runId, runPaths } from "@/lib/paths.ts";
import type { Run, RunRequest, RunState } from "@/lib/types.ts";

const registry = () => join(dataDirectory(), "web.sqlite3");

/** Children this process owns. A run started by another coordinator is visible in the
 * registry but cannot be stopped from here, which is why `stop` reports what it did. */
const children = new Map<string, Deno.ChildProcess>();

function connect(): DatabaseSync {
  Deno.mkdirSync(dataDirectory(), { recursive: true, mode: 0o700 });
  Deno.mkdirSync(join(dataDirectory(), "runs"), { recursive: true, mode: 0o700 });
  const db = new DatabaseSync(registry());
  db.exec(
    "PRAGMA busy_timeout = 5000; PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL;",
  );
  db.exec(`CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY NOT NULL,
    payload TEXT NOT NULL,
    started_at INTEGER NOT NULL
  ) STRICT, WITHOUT ROWID;`);
  return db;
}

function use<T>(action: (db: DatabaseSync) => T): T {
  const db = connect();
  try {
    return action(db);
  } finally {
    db.close();
  }
}

function save(run: Run) {
  use((db) =>
    db.prepare(
      "INSERT INTO runs(id, payload, started_at) VALUES (?, ?, ?) " +
        "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
    ).run(run.id, JSON.stringify(run), run.startedAt)
  );
}

export function read(id: string): Run | null {
  runId(id);
  const row = use((db) =>
    db.prepare("SELECT payload FROM runs WHERE id = ?").get(id)
  ) as { payload: string } | undefined;
  return row ? settle(JSON.parse(row.payload) as Run) : null;
}

export function list(): Run[] {
  const rows = use((db) =>
    db.prepare("SELECT payload FROM runs ORDER BY started_at DESC LIMIT 200").all()
  ) as { payload: string }[];
  return rows.map((r) => settle(JSON.parse(r.payload) as Run));
}

/** A provider key can reach a traceback through a request header; nothing derived from a
 * child's stderr leaves this process without passing through here. */
function redact(text: string) {
  return text
    .replace(/\b(sk|or)-[A-Za-z0-9_-]{8,}/g, "[redacted]")
    .replace(/([A-Za-z0-9_]*(?:KEY|TOKEN|SECRET)[A-Za-z0-9_]*\s*[=:]\s*)\S+/gi, "$1[redacted]");
}

function tail(path: string, lines = 4) {
  try {
    const text = Deno.readTextFileSync(path).trimEnd();
    return redact(text.split("\n").slice(-lines).join("\n")).slice(-600);
  } catch {
    return null;
  }
}

/** Brings a stored record up to date with the filesystem: a finished child leaves a report,
 * and a crashed one leaves only a log. Called on every read so a restarted server still
 * resolves runs it no longer owns. */
function settle(run: Run): Run {
  if (run.state === "done" || run.state === "failed") return run;
  const paths = runPaths(run.id);
  let report: Record<string, unknown> | null = null;
  try {
    report = JSON.parse(Deno.readTextFileSync(paths.report));
  } catch {
    report = null;
  }
  if (report) {
    const settled: Run = {
      ...run,
      state: "done",
      endedAt: run.endedAt ?? Date.now(),
      report,
    };
    save(settled);
    return settled;
  }
  if (run.state === "running" && !children.has(run.id)) {
    // no report, no child: either another coordinator owns it or the process died
    return run;
  }
  return run;
}

function args(id: string, request: RunRequest): string[] {
  const paths = runPaths(id);
  const list = [
    "run",
    "python",
    "benchmarks/swarm/run.py",
    "--topic",
    request.topic,
    "--model",
    request.model,
    "--personas",
    String(request.personas),
    "--rounds",
    String(request.rounds),
    "--concurrency",
    String(request.concurrency),
    "--db",
    paths.db,
    "--report",
    paths.report,
    "--no-reasoning",
  ];
  if (request.compose) list.push("--compose");
  if (request.ranked) list.push("--ranked");
  if (request.seats > 0) list.push("--seats", String(request.seats));
  if (request.usd > 0) list.push("--usd", String(request.usd));
  if (request.tokens > 0) list.push("--tokens", String(request.tokens));
  if (request.requests > 0) list.push("--requests", String(request.requests));
  return list;
}

export function create(request: RunRequest): Run {
  const id = newRunId();
  const paths = runPaths(id);
  Deno.mkdirSync(dirname(paths.db), { recursive: true, mode: 0o700 });

  const run: Run = {
    ...request,
    id,
    state: "starting",
    startedAt: Date.now(),
    endedAt: null,
    error: null,
    report: null,
  };
  save(run);

  const log = Deno.openSync(paths.log, { create: true, write: true, truncate: true });
  const child = new Deno.Command("uv", {
    args: args(id, request),
    cwd: projectRoot(),
    stdin: "null",
    stdout: "null",
    stderr: "piped",
  }).spawn();
  children.set(id, child);

  child.stderr.pipeTo(log.writable).catch(() => {});
  child.status.then((status) => {
    children.delete(id);
    const current = read(id);
    if (!current || current.state === "done") return;
    let report: Record<string, unknown> | null = null;
    try {
      report = JSON.parse(Deno.readTextFileSync(paths.report));
    } catch {
      report = null;
    }
    const state: RunState = report
      ? "done"
      : current.state === "stopped"
      ? "stopped"
      : "failed";
    save({
      ...current,
      state,
      endedAt: Date.now(),
      report,
      error: report ? null : tail(paths.log),
    });
  });

  const started: Run = { ...run, state: "running" };
  save(started);
  return started;
}

/** Stops a run this process owns. Anything the provider has already been asked for still
 * costs money: this ends the conversation, it does not cancel in-flight requests. */
export function stop(id: string): boolean {
  const child = children.get(runId(id));
  if (!child) return false;
  const current = read(id);
  if (current) save({ ...current, state: "stopped" });
  try {
    child.kill("SIGTERM");
  } catch {
    return false;
  }
  return true;
}
