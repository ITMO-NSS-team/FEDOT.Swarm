import { DatabaseSync } from "node:sqlite";
import type { Fact, Post } from "@/lib/types.ts";

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

export function posts(path: string): Post[] {
  return facts(path, "post").map((f) => ({
    producer: f.producer,
    step: f.step,
    text: String(f.value),
  }));
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
      Object.entries(personas).map(([name, agent]) => [name, agent.prompt ?? ""]),
    );
  } catch {
    return {};
  }
}

export interface UsageTick {
  index: number;
  fired: number;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  at: number;
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
