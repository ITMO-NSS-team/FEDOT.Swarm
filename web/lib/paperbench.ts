import { DatabaseSync } from "node:sqlite";
import { dirname, join } from "node:path";
import {
  dataDirectory,
  newRunId,
  paperPaths,
  projectRoot,
  runId,
} from "@/lib/paths.ts";
import type { PaperScalars } from "@/lib/paper_upload.ts";

export type PaperRunState =
  | "starting"
  | "running"
  | "done"
  | "failed"
  | "stopped";

export interface RubricLeaf {
  id: string;
  requirements: string;
  weight: number;
  passed: boolean;
  reason: string;
}

export interface PaperFile {
  path: string;
  absPath: string;
  lines: number;
}

export interface PaperCastMember {
  id: string;
  angle: string;
  score: number;
}

export interface PaperUsage {
  requests: number;
  inputTokens: number;
  outputTokens: number;
}

export interface PaperReport {
  branch: string;
  code: string;
  files?: PaperFile[];
  workdir: string;
  personas?: number;
  roundsRun?: number;
  cast?: PaperCastMember[];
  compose?: { attempts: number; fellBack: boolean } | null;
  swarmSeconds?: number;
  judgeSeconds?: number;
  /** Only meaningful for a run started with `backend: "openrouter"`; `run.py` reports it
   * empty for `claude-code`, which has no per-token cost to meter. */
  backend?: string;
  usage?: { swarm?: PaperUsage; judge?: PaperUsage };
  score: number;
  leaves: RubricLeaf[];
}

export interface PaperProgress {
  step: "parsing" | "swarm" | "judge";
  percent: number;
}

export interface PaperRun {
  id: string;
  paper: string;
  timeoutSeconds: number;
  personas: number;
  rounds: number;
  ranked: boolean;
  seats: number;
  compose: boolean;
  backend: string;
  model: string;
  usd: number;
  tokens: number;
  requests: number;
  state: PaperRunState;
  startedAt: number;
  endedAt: number | null;
  error: string | null;
  report: PaperReport | null;
  progress?: PaperProgress;
}

const registry = () => join(dataDirectory(), "web.sqlite3");

const children = new Map<string, Deno.ChildProcess>();

function connect(): DatabaseSync {
  Deno.mkdirSync(dataDirectory(), { recursive: true, mode: 0o700 });
  Deno.mkdirSync(join(dataDirectory(), "paperbench"), {
    recursive: true,
    mode: 0o700,
  });
  const db = new DatabaseSync(registry());
  db.exec(
    "PRAGMA busy_timeout = 5000; PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL;",
  );
  db.exec(`CREATE TABLE IF NOT EXISTS paper_runs (
    id TEXT PRIMARY KEY NOT NULL,
    payload TEXT NOT NULL,
    started_at INTEGER NOT NULL
  ) STRICT, WITHOUT ROWID;`);
  return db;
}

function withDb<T>(action: (db: DatabaseSync) => T): T {
  const db = connect();
  try {
    return action(db);
  } finally {
    db.close();
  }
}

function save(run: PaperRun) {
  withDb((db) =>
    db.prepare(
      "INSERT INTO paper_runs(id, payload, started_at) VALUES (?, ?, ?) " +
        "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
    ).run(run.id, JSON.stringify(run), run.startedAt)
  );
}

export function read(id: string): PaperRun | null {
  runId(id);
  const row = withDb((db) =>
    db.prepare("SELECT payload FROM paper_runs WHERE id = ?").get(id)
  ) as { payload: string } | undefined;
  return row ? settle(JSON.parse(row.payload) as PaperRun) : null;
}

/** Drops the registry row and best-effort removes whatever the run left on disk: the
 * report/status/log under the repo's data dir, uploaded inputs beside them, and the
 * coder's and judge's workdirs wherever `paperPaths` currently points them (outside the
 * repo, see paths.ts). A run still in flight is left to finish; its process outlives the
 * deleted row harmlessly, `create`'s completion handler already treats a missing row as
 * nothing to update. */
export function remove(id: string) {
  runId(id);
  const paths = paperPaths(id);
  withDb((db) => db.prepare("DELETE FROM paper_runs WHERE id = ?").run(id));
  for (const path of [paths.report, paths.status, paths.log]) {
    try {
      Deno.removeSync(path);
    } catch {
      // already gone
    }
  }
  for (const path of [paths.inputs, paths.workdir]) {
    try {
      Deno.removeSync(path, { recursive: true });
    } catch {
      // already gone
    }
  }
}

export function list(): PaperRun[] {
  const rows = withDb((db) =>
    db.prepare(
      "SELECT payload FROM paper_runs ORDER BY started_at DESC LIMIT 200",
    )
      .all()
  ) as { payload: string }[];
  return rows.map((r) => settle(JSON.parse(r.payload) as PaperRun));
}

function tail(path: string, lines = 4) {
  try {
    const text = Deno.readTextFileSync(path).trimEnd();
    return text.split("\n").slice(-lines).join("\n").slice(-600);
  } catch {
    return null;
  }
}

function settle(run: PaperRun): PaperRun {
  if (
    run.state === "done" || run.state === "failed" || run.state === "stopped"
  ) {
    return run;
  }
  const paths = paperPaths(run.id);
  let report: PaperReport | null = null;
  try {
    report = JSON.parse(Deno.readTextFileSync(paths.report));
  } catch {
    report = null;
  }
  if (report) {
    const settled: PaperRun = {
      ...run,
      state: "done",
      endedAt: run.endedAt ?? Date.now(),
      report,
    };
    save(settled);
    return settled;
  }
  try {
    const progress = JSON.parse(Deno.readTextFileSync(paths.status));
    return { ...run, progress };
  } catch {
    return run;
  }
}

/** Files a run was started with instead of a paper from `benchmarks/paperbench/data`:
 * absolute paths the server saved under `paperPaths(id).inputs`, passed straight
 * through to `run.py`'s `--paper-tex` (a file or a directory of them) / `--rubric`. */
export interface PaperInputs {
  id?: string;
  paperTex?: string;
  rubric?: string;
}

export function create(
  paper: string,
  scalars: PaperScalars,
  inputs: PaperInputs = {},
): PaperRun {
  const { timeoutSeconds, personas, rounds, ranked, seats, compose, backend, model } =
    scalars;
  const id = inputs.id ? runId(inputs.id) : newRunId();
  const paths = paperPaths(id);
  Deno.mkdirSync(dirname(paths.report), { recursive: true, mode: 0o700 });

  const run: PaperRun = {
    id,
    paper,
    timeoutSeconds,
    personas,
    rounds,
    ranked,
    seats,
    compose,
    backend,
    model,
    usd: scalars.usd,
    tokens: scalars.tokens,
    requests: scalars.requests,
    state: "starting",
    startedAt: Date.now(),
    endedAt: null,
    error: null,
    report: null,
  };
  save(run);

  const log = Deno.openSync(paths.log, {
    create: true,
    write: true,
    truncate: true,
  });
  // Its own venv, not the workspace one: the harness's Python client needs Python 3.12
  // and a local path source (the internal git host it normally comes from is not
  // reachable here), neither of which the rest of the workspace should depend on.
  const child = new Deno.Command("benchmarks/paperbench/.venv/bin/python", {
    args: [
      "benchmarks/paperbench/run.py",
      "--paper",
      paper,
      "--workdir",
      paths.workdir,
      "--report",
      paths.report,
      "--status",
      paths.status,
      "--timeout",
      String(timeoutSeconds),
      "--personas",
      String(personas),
      "--rounds",
      String(rounds),
      "--backend",
      backend,
      "--model",
      model,
      ...(inputs.paperTex ? ["--paper-tex", inputs.paperTex] : []),
      ...(inputs.rubric ? ["--rubric", inputs.rubric] : []),
      ...(ranked ? ["--ranked"] : []),
      ...(seats > 0 ? ["--seats", String(seats)] : []),
      ...(compose ? ["--compose"] : []),
      ...(scalars.usd > 0 ? ["--usd", String(scalars.usd)] : []),
      ...(scalars.tokens > 0 ? ["--tokens", String(scalars.tokens)] : []),
      ...(scalars.requests > 0 ? ["--requests", String(scalars.requests)] : []),
    ],
    cwd: projectRoot(),
    stdin: "null",
    stdout: "null",
    stderr: "piped",
  }).spawn();
  children.set(id, child);

  child.stderr.pipeTo(log.writable).catch(() => {});
  child.status.then(() => {
    children.delete(id);
    const current = read(id);
    if (!current || current.state === "done") return;
    let report: PaperReport | null = null;
    try {
      report = JSON.parse(Deno.readTextFileSync(paths.report));
    } catch {
      report = null;
    }
    save({
      ...current,
      state: report
        ? "done"
        : current.state === "stopped"
        ? "stopped"
        : "failed",
      endedAt: Date.now(),
      report,
      error: report ? null : tail(paths.log),
    });
  });

  const started: PaperRun = { ...run, state: "running" };
  save(started);
  return started;
}

/** Stops a run this process owns. A persona mid-call still finishes its turn: this ends
 * the run, it does not cancel in-flight sessions. */
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
