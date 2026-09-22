import { DatabaseSync } from "node:sqlite";
import { join } from "node:path";
import { dataDirectory } from "@/lib/paths.ts";

/** What both registries (free-topic and PaperBench runs) share: one sqlite table of json
 * payloads keyed by id, plus the helpers that read a child's leftovers safely. */

export interface Registered {
  id: string;
  startedAt: number;
}

export class Registry<T extends Registered> {
  constructor(private table: string, private subdir: string) {}

  private connect(): DatabaseSync {
    Deno.mkdirSync(dataDirectory(), { recursive: true, mode: 0o700 });
    Deno.mkdirSync(join(dataDirectory(), this.subdir), {
      recursive: true,
      mode: 0o700,
    });
    const db = new DatabaseSync(join(dataDirectory(), "web.sqlite3"));
    db.exec(
      "PRAGMA busy_timeout = 5000; PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL;",
    );
    db.exec(`CREATE TABLE IF NOT EXISTS ${this.table} (
      id TEXT PRIMARY KEY NOT NULL,
      payload TEXT NOT NULL,
      started_at INTEGER NOT NULL
    ) STRICT, WITHOUT ROWID;`);
    return db;
  }

  private use<R>(action: (db: DatabaseSync) => R): R {
    const db = this.connect();
    try {
      return action(db);
    } finally {
      db.close();
    }
  }

  save(run: T) {
    this.use((db) =>
      db.prepare(
        `INSERT INTO ${this.table}(id, payload, started_at) VALUES (?, ?, ?) ` +
          "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
      ).run(run.id, JSON.stringify(run), run.startedAt)
    );
  }

  read(id: string): T | null {
    const row = this.use((db) =>
      db.prepare(`SELECT payload FROM ${this.table} WHERE id = ?`).get(id)
    ) as { payload: string } | undefined;
    return row ? JSON.parse(row.payload) as T : null;
  }

  list(limit = 200): T[] {
    const rows = this.use((db) =>
      db.prepare(
        `SELECT payload FROM ${this.table} ORDER BY started_at DESC LIMIT ?`,
      ).all(limit)
    ) as { payload: string }[];
    return rows.map((r) => JSON.parse(r.payload) as T);
  }

  delete(id: string) {
    this.use((db) =>
      db.prepare(`DELETE FROM ${this.table} WHERE id = ?`).run(id)
    );
  }
}

/** A provider key can reach a traceback through a request header or an environment dump;
 * nothing derived from a child's stderr leaves this process without passing through here. */
export function redact(text: string) {
  return text
    .replace(/\b(sk|or)-[A-Za-z0-9_-]{8,}/g, "[redacted]")
    .replace(/\bsk-or-v1-[A-Za-z0-9]+/g, "[redacted]")
    .replace(
      /([A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*["']?\s*[=:]\s*["']?)[^\s"',}]+/gi,
      "$1[redacted]",
    );
}

/** The last lines of a log, redacted, for a failed run's explanation. */
export function tail(path: string, lines = 6) {
  try {
    const text = Deno.readTextFileSync(path).trimEnd();
    return redact(text.split("\n").slice(-lines).join("\n")).slice(-800);
  } catch {
    return null;
  }
}

export function pidAlive(pid: number | null | undefined): boolean {
  if (!pid || pid <= 0) return false;
  try {
    // SIGCONT is a no-op on a running process and throws on a missing one
    Deno.kill(pid, "SIGCONT");
    return true;
  } catch {
    return false;
  }
}

/** The pid `run.py` writes beside its status file while it runs. */
export function readPid(path: string): number | null {
  try {
    const pid = Number(Deno.readTextFileSync(path).trim());
    return Number.isInteger(pid) && pid > 0 ? pid : null;
  } catch {
    return null;
  }
}

export function removeQuietly(path: string, recursive = false) {
  try {
    Deno.removeSync(path, { recursive });
  } catch {
    // already gone
  }
}

export function readJson<T>(path: string): T | null {
  try {
    return JSON.parse(Deno.readTextFileSync(path)) as T;
  } catch {
    return null;
  }
}
