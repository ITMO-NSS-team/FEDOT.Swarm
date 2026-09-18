import { dirname, join } from "node:path";
import { newRunId, paperPaths, projectRoot, runId } from "@/lib/paths.ts";
import {
  pidAlive,
  readJson,
  readPid,
  redact,
  Registry,
  removeQuietly,
  tail,
} from "@/lib/registry.ts";
import type { PaperScalars } from "@/lib/paper_upload.ts";
import { type LiveBoard, type RunState, terminal } from "@/lib/types.ts";

export type PaperRunState = RunState;

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
  score: number;
  rounds?: number;
  cost?: number;
  filesChanged?: number;
  graded?: boolean;
  angle?: string;
}

export interface PaperUsage {
  requests: number;
  inputTokens: number;
  outputTokens: number;
  usd?: number;
}

export interface PaperTrace {
  rounds: number;
  tokens: number;
  cost: number;
  filesChanged: number;
  toolCalls: number;
  timedOut: number;
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
  usage?: { swarm?: PaperUsage; workers?: PaperUsage; judge?: PaperUsage };
  score: number;
  leaves: RubricLeaf[];
  inputs?: Record<string, unknown>;
  params?: Record<string, unknown>;
  command?: string;
  kept?: { voice: string; dir: string };
  trace?: Record<string, PaperTrace>;
  errors?: { producer: string; step: number; error: string }[];
  budget?: Record<string, unknown>;
  startedAt?: string;
  endedAt?: string;
}

export interface PaperProgress {
  step: string;
  percent: number;
  stage?: string;
  engine?: string;
  round?: number;
  rounds?: number;
  at?: number;
  error?: string;
}

/** What the run was started from, kept so it can be told apart and reproduced. */
export interface PaperInputsRecord {
  kind: "tex" | "pdf" | "bundled";
  paperName: string;
  paperSha256: string | null;
  rubricSha256: string | null;
}

export interface PaperRun extends PaperScalars {
  id: string;
  paper: string;
  state: PaperRunState;
  startedAt: number;
  endedAt: number | null;
  error: string | null;
  report: PaperReport | null;
  progress?: PaperProgress;
  parentId: string | null;
  inputs: PaperInputsRecord | null;
  pid: number | null;
}

const registry = new Registry<PaperRun>("paper_runs", "paperbench");
const children = new Map<string, Deno.ChildProcess>();

/** Rows written before these fields existed read as the run they were. */
function normalize(row: Partial<PaperRun> & { id: string }): PaperRun {
  return {
    seed: 7,
    pdfEngine: "pymupdf",
    roundMinutes: 5,
    steps: 24,
    concurrency: 2,
    workers: "prompt",
    parentId: null,
    inputs: null,
    pid: null,
    ...row,
  } as PaperRun;
}

export function read(id: string): PaperRun | null {
  const row = registry.read(runId(id));
  return row ? settle(normalize(row)) : null;
}

export function list(): PaperRun[] {
  return registry.list().map((row) => settle(normalize(row)));
}

export function running(): number {
  return list().filter((run) => !terminal(run.state)).length;
}

/** The live board `workers.LiveBoard` writes: who is inside an OpenCode session now. */
export function live(id: string): LiveBoard {
  return readJson<LiveBoard>(join(paperPaths(id).workdir, "live.json")) ?? {};
}

function pidOf(run: PaperRun): number | null {
  return readPid(`${paperPaths(run.id).status}.pid`) ?? run.pid;
}

/** Brings a stored record up to date with what `run.py` left on disk: a report means done,
 * a stopped or failed status says so, and a running row with no process behind it is lost.
 * Called on every read so a restarted server still resolves runs it no longer owns. */
function settle(run: PaperRun): PaperRun {
  const paths = paperPaths(run.id);
  if (terminal(run.state)) {
    if (run.state === "stopped" && !run.report) {
      const late = readJson<PaperReport>(paths.report);
      if (late) {
        const settled = { ...run, report: late };
        registry.save(settled);
        return settled;
      }
    }
    return run;
  }
  const report = readJson<PaperReport>(paths.report);
  if (report) {
    const settled: PaperRun = {
      ...run,
      state: "done",
      endedAt: run.endedAt ?? Date.now(),
      report,
    };
    registry.save(settled);
    return settled;
  }
  const status = readJson<PaperProgress>(paths.status);
  if (status?.step === "stopped" || status?.step === "failed") {
    const settled: PaperRun = {
      ...run,
      state: status.step,
      endedAt: run.endedAt ?? Date.now(),
      error: status.step === "failed"
        ? (status.error ? redact(status.error) : tail(paths.log))
        : null,
    };
    registry.save(settled);
    return settled;
  }
  if (!children.has(run.id) && !pidAlive(pidOf(run))) {
    const lost: PaperRun = {
      ...run,
      state: "lost",
      endedAt: Date.now(),
      error:
        "The server lost this run: its process is gone and no report was written.",
    };
    registry.save(lost);
    return lost;
  }
  return status ? { ...run, progress: status } : run;
}

/** Files a run was started with instead of a paper from `benchmarks/paperbench/data`:
 * absolute paths the server saved under `paperPaths(id).inputs`. */
export interface PaperInputs {
  id?: string;
  paperTex?: string;
  paperPdf?: string;
  rubric?: string;
  record?: PaperInputsRecord;
  parentId?: string;
}

function flags(
  paper: string,
  id: string,
  scalars: PaperScalars,
  inputs: PaperInputs,
): string[] {
  const paths = paperPaths(id);
  return [
    "--paper",
    paper,
    "--workdir",
    paths.workdir,
    "--report",
    paths.report,
    "--status",
    paths.status,
    "--timeout",
    String(scalars.timeoutSeconds),
    "--personas",
    String(scalars.personas),
    "--rounds",
    String(scalars.rounds),
    "--model",
    scalars.model,
    "--concurrency",
    String(scalars.concurrency),
    "--seed",
    String(scalars.seed),
    "--pdf-engine",
    scalars.pdfEngine,
    "--workers",
    scalars.workers,
    "--round-minutes",
    String(scalars.roundMinutes),
    "--steps",
    String(scalars.steps),
    "--max-tokens",
    String(scalars.maxTokens),
    ...(inputs.paperTex ? ["--paper-tex", inputs.paperTex] : []),
    ...(inputs.paperPdf ? ["--paper-pdf", inputs.paperPdf] : []),
    ...(inputs.rubric ? ["--rubric", inputs.rubric] : []),
    ...(scalars.ranked ? ["--ranked"] : []),
    ...(scalars.seats > 0 ? ["--seats", String(scalars.seats)] : []),
    ...(scalars.compose ? ["--compose"] : []),
    ...(scalars.usd > 0 ? ["--usd", String(scalars.usd)] : []),
    ...(scalars.tokens > 0 ? ["--tokens", String(scalars.tokens)] : []),
    ...(scalars.requests > 0 ? ["--requests", String(scalars.requests)] : []),
  ];
}

/** `FEDOTMAS_RUNNER` swaps `uv run ... run.py` for any executable that takes the same
 * flags, which is how the end-to-end tests run the front end without a model. */
function command(args: string[]): { cmd: string; args: string[] } {
  const runner = Deno.env.get("FEDOTMAS_RUNNER");
  if (runner) return { cmd: runner, args };
  return {
    cmd: "uv",
    args: [
      "run",
      "--extra",
      "pydantic-ai",
      "--extra",
      "opencode",
      "--group",
      "paperbench",
      "python",
      "benchmarks/paperbench/run.py",
      ...args,
    ],
  };
}

function finish(id: string) {
  children.delete(id);
  const paths = paperPaths(id);
  const current = registry.read(id);
  if (!current || current.state === "done") return;
  const report = readJson<PaperReport>(paths.report);
  const status = readJson<PaperProgress>(paths.status);
  const stopped = current.state === "stopped" || status?.step === "stopped";
  registry.save({
    ...normalize(current),
    state: report ? "done" : stopped ? "stopped" : "failed",
    endedAt: Date.now(),
    report,
    error: report || stopped
      ? null
      : (status?.error ? redact(status.error) : null) ?? tail(paths.log),
  });
}

export function create(
  paper: string,
  scalars: PaperScalars,
  inputs: PaperInputs = {},
): PaperRun {
  const id = inputs.id ? runId(inputs.id) : newRunId();
  const paths = paperPaths(id);
  Deno.mkdirSync(dirname(paths.report), { recursive: true, mode: 0o700 });
  const run: PaperRun = {
    ...scalars,
    id,
    paper,
    state: "starting",
    startedAt: Date.now(),
    endedAt: null,
    error: null,
    report: null,
    parentId: inputs.parentId ?? null,
    inputs: inputs.record ?? null,
    pid: null,
  };
  const log = Deno.openSync(paths.log, {
    create: true,
    write: true,
    truncate: true,
  });
  const { cmd, args } = command(flags(paper, id, scalars, inputs));
  let child: Deno.ChildProcess;
  try {
    child = new Deno.Command(cmd, {
      args,
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
  const started: PaperRun = { ...run, state: "running", pid: child.pid };
  registry.save(started);
  child.status.then(() => finish(id));
  return started;
}

/** Stops a run: SIGTERM to `run.py`, which aborts its OpenCode sessions and ends its
 * process group, else to the child this server spawned. */
export function stop(id: string): boolean {
  const run = registry.read(runId(id));
  if (!run) return false;
  let signalled = false;
  const pid = readPid(`${paperPaths(id).status}.pid`);
  if (pid && pidAlive(pid)) {
    try {
      Deno.kill(pid, "SIGTERM");
      signalled = true;
    } catch {
      signalled = false;
    }
  }
  const child = children.get(id);
  if (!signalled && child) {
    try {
      child.kill("SIGTERM");
      signalled = true;
    } catch {
      signalled = false;
    }
  }
  if (signalled && !terminal(run.state)) {
    registry.save({ ...normalize(run), state: "stopped" });
  }
  return signalled;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Stops the run if it is still going, waits for its process, then drops the row and
 * everything it left on disk: report, status, log, uploaded inputs and the workdir. */
export async function remove(id: string) {
  const run = registry.read(runId(id));
  if (!run) return;
  if (!terminal(run.state)) {
    stop(id);
    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      if (!children.has(id) && !pidAlive(pidOf(normalize(run)))) break;
      await sleep(250);
    }
  }
  const paths = paperPaths(id);
  registry.delete(id);
  for (
    const path of [paths.report, paths.status, `${paths.status}.pid`, paths.log]
  ) {
    removeQuietly(path);
  }
  for (const path of [paths.inputs, paths.workdir]) removeQuietly(path, true);
}

/** Runs the same request on the same inputs again as a new run that remembers its
 * parent. The seed fixes which voices the activity sampler wakes, not what the model
 * says, so two reproductions agree on the shape of the run and differ in its content. */
export function reproduce(parentId: string): PaperRun {
  const parent = read(parentId);
  if (!parent) throw new Error("No such run");
  const scalars: PaperScalars = {
    timeoutSeconds: parent.timeoutSeconds,
    personas: parent.personas,
    rounds: parent.rounds,
    ranked: parent.ranked,
    seats: parent.seats,
    compose: parent.compose,
    model: parent.model,
    usd: parent.usd,
    tokens: parent.tokens,
    requests: parent.requests,
    maxTokens: parent.maxTokens,
    seed: parent.seed,
    pdfEngine: parent.pdfEngine,
    roundMinutes: parent.roundMinutes,
    steps: parent.steps,
    concurrency: parent.concurrency,
    workers: parent.workers,
  };
  const id = newRunId();
  const from = paperPaths(parent.id).inputs;
  const inputs: PaperInputs = {
    id,
    parentId: parent.id,
    record: parent.inputs ?? undefined,
  };
  let hasInputs = false;
  try {
    hasInputs = Deno.statSync(from).isDirectory;
  } catch {
    hasInputs = false;
  }
  if (hasInputs) {
    const to = paperPaths(id).inputs;
    copyTree(from, to);
    for (
      const [key, name] of [["paperTex", "tex"], ["paperPdf", "paper.pdf"], [
        "rubric",
        "rubric_branch.json",
      ]] as const
    ) {
      try {
        Deno.statSync(join(to, name));
        inputs[key] = join(to, name);
      } catch {
        // that input was not part of the parent run
      }
    }
  }
  return create(parent.paper, scalars, inputs);
}

function copyTree(from: string, to: string) {
  Deno.mkdirSync(to, { recursive: true, mode: 0o700 });
  for (const entry of Deno.readDirSync(from)) {
    const source = join(from, entry.name);
    const target = join(to, entry.name);
    if (entry.isDirectory) copyTree(source, target);
    else if (entry.isFile) Deno.copyFileSync(source, target);
  }
}
