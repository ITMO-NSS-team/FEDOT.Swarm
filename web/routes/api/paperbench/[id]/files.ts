import { listFiles, rootDir } from "@/lib/files.ts";
import { read } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

/** The files under one root of a run: `solution`, `inputs`, or `ws/<voice>`. */
export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });
    const root = new URL(ctx.req.url).searchParams.get("root") ?? "solution";
    const dir = rootDir(run.id, root);
    if (!dir) return Response.json({ error: "No such root" }, { status: 404 });
    return Response.json(
      { root, files: listFiles(dir) },
      { headers: { "cache-control": "no-store" } },
    );
  },
});
