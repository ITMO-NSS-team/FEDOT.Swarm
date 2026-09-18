import { dirname } from "node:path";
import { newRunId, projectRoot, runId, runPaths } from "@/lib/paths.ts";
import {
  pidAlive,
  readJson,
  Registry,
  removeQuietly,
  tail,
} from "@/lib/registry.ts";
import { type Run, type RunRequest, terminal } from "@/lib/types.ts";

const registry = new Registry<Run>("runs", "runs");

/** Children this process owns. A run started by another coordinator is visible in the
 * registry but cannot be stopped from here, which is why `stop` reports what it did. */
const children = new Map<string, Deno.ChildProcess>();

export function read(id: string): Run | null {
  const row = registry.read(runId(id));
  return row ? settle(row) : null;
}

export function list(): Run[] {
  return registry.list().map(settle);
}

export function running(): number {
  return list().filter((run) => !terminal(run.state)).length;
}

/** Brings a stored record up to date with the filesystem: a finished child leaves a report,
 * a crashed one leaves only a log, and a running row with no process behind it is lost. */
function settle(run: Run): Run {
  if (terminal(run.state)) return run;
  const paths = runPaths(run.id);
  const report = readJson<Record<string, unknown>>(paths.report);
  if (report) {
    const settled: Run = {
      ...run,
      state: "done",
      endedAt: run.endedAt ?? Date.now(),
      report,
    };
    registry.save(settled);
    return settled;
  }
  if (!children.has(run.id) && !pidAlive(run.pid)) {
    const lost: Run = {
      ...run,
      state: "lost",
      endedAt: Date.now(),
      error:
        "The server lost this run: its process is gone and no report was written.",
    };
    registry.save(lost);
    return lost;
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
    pid: null,
  };
  const log = Deno.openSync(paths.log, {
    create: true,
    write: true,
    truncate: true,
  });
  let child: Deno.ChildProcess;
  try {
    child = new Deno.Command("uv", {
      args: args(id, request),
      cwd: projectRoot(),
      stdin: "null",
      stdout: "null",
      stderr: "piped",
    }).spawn();
  } catch (error) {
    log.close();
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Could not start run.py: ${detail}`);
  }
  children.set(id, child);
  child.stderr.pipeTo(log.writable).catch(() => {});
  const started: Run = { ...run, state: "running", pid: child.pid };
  registry.save(started);
  child.status.then(() => {
    children.delete(id);
    const current = registry.read(id);
    if (!current || current.state === "done") return;
    const report = readJson<Record<string, unknown>>(paths.report);
    registry.save({
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
  return started;
}

/** Ends the conversation. Requests already with the provider are still billed, so the
 * caller says what was stopped rather than claiming the run cost nothing more. */
export function stop(id: string): boolean {
  const child = children.get(runId(id));
  if (!child) return false;
  const current = registry.read(id);
  if (current && !terminal(current.state)) {
    registry.save({ ...current, state: "stopped" });
  }
  try {
    child.kill("SIGTERM");
  } catch {
    return false;
  }
  return true;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function remove(id: string) {
  const run = registry.read(runId(id));
  if (!run) return;
  if (!terminal(run.state)) {
    stop(id);
    const deadline = Date.now() + 5000;
    while (children.has(id) && Date.now() < deadline) await sleep(250);
  }
  const paths = runPaths(id);
  registry.delete(id);
  for (
    const path of [
      paths.db,
      `${paths.db}-wal`,
      `${paths.db}-shm`,
      paths.spec,
      paths.report,
      paths.usage,
      paths.log,
    ]
  ) {
    removeQuietly(path);
  }
}
