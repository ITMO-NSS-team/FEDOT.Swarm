import { DatabaseSync } from "node:sqlite";
import type { Fact, Post, PostMeta, UsageTick } from "@/lib/types.ts";

/** Reads a fedotmas `SqliteStore` while the run that owns it is still writing. The store is
 * WAL with a single writer, so a second connection sees committed supersteps as they land;
 * nothing here writes, and a missing file just means the run has not committed yet. */
function open<T>(path: string, action: (db: DatabaseSync) => T): T | null {
  let db: DatabaseSync;
  try {
    db = new DatabaseSync(path, { readOnly: true });
  } catch {
    return null;
  }
  try {
    db.exec("PRAGMA busy_timeout = 2000");
    return action(db);
  } catch {
    return null;
  } finally {
    db.close();
  }
}

interface Row {
  tag: string;
  value_json: string;
  producer: string;
  step: number;
}

function decode(row: Row): Fact {
  return {
    tag: row.tag,
    value: JSON.parse(row.value_json),
    producer: row.producer,
    step: row.step,
  };
}

export function facts(path: string, tag?: string): Fact[] {
  return open(path, (db) => {
    const rows = tag
      ? db.prepare(
        "SELECT tag, value_json, producer, step FROM facts WHERE tag = ? ORDER BY rowid_",
      ).all(tag)
      : db.prepare(
        "SELECT tag, value_json, producer, step FROM facts ORDER BY rowid_",
      ).all();
    return (rows as unknown as Row[]).map(decode);
  }) ?? [];
}

type Structured = Record<string, unknown> & { report: string };

const structured = (value: unknown): value is Structured =>
  typeof value === "object" && value !== null &&
  typeof (value as { report?: unknown }).report === "string";

/** What a post reads as: the same rule as `fedotmas_meta.presets.post_text`. */
export function postText(value: unknown): string {
  if (structured(value)) return value.report;
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

const sum = (record: unknown): number =>
  typeof record === "object" && record !== null
    ? Object.values(record as Record<string, unknown>).reduce<number>(
      (n, v) => n + (typeof v === "number" ? v : 0),
      0,
    )
    : 0;

export function postMeta(value: unknown): PostMeta | undefined {
  if (!structured(value)) return undefined;
  return {
    files: Array.isArray(value.files) ? value.files.map(String) : [],
    cost: typeof value.cost === "number" ? value.cost : 0,
    tokens: sum(value.tokens),
    toolCalls: sum(value.toolCalls),
    seconds: typeof value.seconds === "number" ? value.seconds : 0,
    timedOut: value.timedOut === true,
    error: typeof value.error === "string" ? value.error : null,
  };
}

export function posts(path: string): Post[] {
  return facts(path, "post").map((f) => {
    const meta = postMeta(f.value);
    return {
      producer: f.producer,
      step: f.step,
      text: postText(f.value),
      ...(meta ? { meta } : {}),
    };
  });
}

export function topic(path: string): string {
  const found = facts(path, "topic");
  return found.length ? String(found[0].value) : "";
}

/** Highest committed superstep, which is how far a scrubber may go. */
export function lastStep(path: string): number {
  return open(path, (db) => {
    const row = db.prepare("SELECT MAX(step) AS step FROM facts").get() as
      | { step: number | null }
      | undefined;
    return row?.step ?? -1;
  }) ?? -1;
}

/** The cast as `run.py` persisted it before starting: name to character. */
export function cast(specPath: string): Record<string, string> {
  let text: string;
  try {
    text = Deno.readTextFileSync(specPath);
  } catch {
    return {};
  }
  try {
    const spec = JSON.parse(text) as {
      fill?: { personas?: Record<string, { prompt?: string }> };
    };
    const personas = spec.fill?.personas ?? {};
    return Object.fromEntries(
      Object.entries(personas).map((
        [name, agent],
      ) => [name, agent.prompt ?? ""]),
    );
  } catch {
    return {};
  }
}

/** The sidecar `run.py` appends to after every superstep. One line per step, so the last
 * line is what the run has spent so far and the file is the curve. */
export function usage(path: string): UsageTick[] {
  let text: string;
  try {
    text = Deno.readTextFileSync(path);
  } catch {
    return [];
  }
  const ticks: UsageTick[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      ticks.push(JSON.parse(line) as UsageTick);
    } catch {
      // a half-written last line is normal while the run is appending
    }
  }
  return ticks;
}
