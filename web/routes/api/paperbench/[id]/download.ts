import { basename, join } from "node:path";
import { zipSync } from "fflate";
import { listFiles, rootDir, safeJoin } from "@/lib/files.ts";
import { read } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

const MAX_ZIP_BYTES = 50 * 1024 * 1024;

/** One file of a run as a download, or a whole root as a zip. */
export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });
    const url = new URL(ctx.req.url);
    const root = url.searchParams.get("root") ?? "solution";
    const dir = rootDir(run.id, root);
    if (!dir) return Response.json({ error: "No such root" }, { status: 404 });
    const rel = url.searchParams.get("path");
    if (rel) {
      const path = safeJoin(dir, rel);
      if (!path) {
        return Response.json({ error: "No such file" }, { status: 404 });
      }
      try {
        const bytes = Deno.readFileSync(path);
        return new Response(bytes, {
          headers: {
            "content-type": "application/octet-stream",
            "content-disposition": `attachment; filename="${basename(path)}"`,
          },
        });
      } catch {
        return Response.json({ error: "No such file" }, { status: 404 });
      }
    }
    const files = listFiles(dir, 5000);
    const total = files.reduce((n, f) => n + f.bytes, 0);
    if (total > MAX_ZIP_BYTES) {
      return Response.json({ error: "Too large to zip" }, { status: 413 });
    }
    const entries: Record<string, Uint8Array> = {};
    for (const file of files) {
      try {
        entries[file.path] = Deno.readFileSync(join(dir, file.path));
      } catch {
        // a file that vanished mid-walk is left out
      }
    }
    const name = `${run.id}-${root.replace("/", "-")}.zip`;
    return new Response(new Uint8Array(zipSync(entries, { level: 6 })), {
      headers: {
        "content-type": "application/zip",
        "content-disposition": `attachment; filename="${name}"`,
      },
    });
  },
});
