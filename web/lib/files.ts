import { join, relative, resolve } from "node:path";
import { paperPaths } from "@/lib/paths.ts";

/** Reading a run's files back out: the kept solution, each voice's workspace, and the
 * uploaded inputs. Every path a client sends is confined to one of those roots. */

export const SKIP_DIRS = new Set([
  ".git",
  ".fedotmas",
  ".venv",
  "node_modules",
  "__pycache__",
]);

export const MAX_FILE_BYTES = 512 * 1024;
export const MAX_LISTED = 500;

export interface Listed {
  path: string;
  bytes: number;
}

const voiceName = /^[a-zA-Z0-9_-]{1,64}$/;

/** The directory a root name stands for, or null for a name that is not offered. */
export function rootDir(id: string, root: string): string | null {
  const paths = paperPaths(id);
  if (root === "solution") return join(paths.workdir, "solution");
  if (root === "inputs") return paths.inputs;
  if (root.startsWith("ws/")) {
    const voice = root.slice(3);
    return voiceName.test(voice) ? join(paths.workdir, "ws", voice) : null;
  }
  return null;
}

/** `rel` joined under `root`, or null when it would leave it: no absolute paths, no `.`
 * or `..` segments, no empty segments, and the resolved path must keep the root prefix. */
export function safeJoin(root: string, rel: string): string | null {
  if (!rel || rel.startsWith("/") || rel.startsWith("\\")) return null;
  const parts = rel.split(/[/\\]+/);
  if (parts.some((p) => p === "" || p === "." || p === "..")) return null;
  if (parts.some((p) => p.includes("\0"))) return null;
  const base = resolve(root);
  const full = resolve(base, ...parts);
  const back = relative(base, full);
  if (!back || back.startsWith("..") || back.startsWith("/")) return null;
  return full;
}

export function listFiles(dir: string, limit = MAX_LISTED): Listed[] {
  const out: Listed[] = [];
  const walk = (at: string, prefix: string) => {
    let entries: Deno.DirEntry[];
    try {
      entries = [...Deno.readDirSync(at)];
    } catch {
      return;
    }
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      if (out.length >= limit) return;
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory) {
        if (!SKIP_DIRS.has(entry.name)) walk(join(at, entry.name), rel);
      } else if (entry.isFile) {
        let bytes = 0;
        try {
          bytes = Deno.statSync(join(at, entry.name)).size;
        } catch {
          continue;
        }
        out.push({ path: rel, bytes });
      }
    }
  };
  walk(dir, "");
  return out;
}

/** A file is text when its first kilobytes hold no NUL byte. */
export function isText(bytes: Uint8Array): boolean {
  const head = bytes.subarray(0, 8192);
  return !head.includes(0);
}
