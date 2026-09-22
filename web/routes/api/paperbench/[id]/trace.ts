import { join } from "node:path";
import { read } from "@/lib/paperbench.ts";
import { paperPaths } from "@/lib/paths.ts";
import { readJson } from "@/lib/registry.ts";
import { define } from "@/utils.ts";

/** Every round every voice worked, as `workers.py` recorded them beside the workspace:
 * the report, the files touched, tokens, cost, tool calls and whether it timed out. */
export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });
    const root = join(paperPaths(run.id).workdir, "ws");
    const rounds: Record<string, Record<string, unknown>[]> = {};
    let voices: Deno.DirEntry[] = [];
    try {
      voices = [...Deno.readDirSync(root)].filter((e) => e.isDirectory);
    } catch {
      voices = [];
    }
    for (const voice of voices.sort((a, b) => a.name.localeCompare(b.name))) {
      const notes = join(root, voice.name, ".fedotmas");
      let files: string[] = [];
      try {
        files = [...Deno.readDirSync(notes)].map((e) => e.name).filter((n) =>
          /^round-\d+\.json$/.test(n)
        );
      } catch {
        continue;
      }
      files.sort((a, b) => Number(a.slice(6, -5)) - Number(b.slice(6, -5)));
      rounds[voice.name] = files.map((name) =>
        readJson<Record<string, unknown>>(join(notes, name)) ?? {}
      );
    }
    return Response.json(
      { trace: run.report?.trace ?? {}, rounds },
      { headers: { "cache-control": "no-store" } },
    );
  },
});
