import { isText, MAX_FILE_BYTES, rootDir, safeJoin } from "@/lib/files.ts";
import { read } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

/** One text file of a run, as plain text. Binary files and large ones are refused rather
 * than streamed into a code view. */
export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });
    const url = new URL(ctx.req.url);
    const dir = rootDir(run.id, url.searchParams.get("root") ?? "solution");
    const path = dir && safeJoin(dir, url.searchParams.get("path") ?? "");
    if (!path) return Response.json({ error: "No such file" }, { status: 404 });
    let bytes: Uint8Array<ArrayBuffer>;
    try {
      const stat = Deno.statSync(path);
      if (!stat.isFile) throw new Error("not a file");
      if (stat.size > MAX_FILE_BYTES) {
        return Response.json({ error: "File too large to show" }, {
          status: 413,
        });
      }
      bytes = Deno.readFileSync(path);
    } catch {
      return Response.json({ error: "No such file" }, { status: 404 });
    }
    if (!isText(bytes)) {
      return Response.json({ error: "Binary file" }, { status: 415 });
    }
    return new Response(bytes, {
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  },
});
