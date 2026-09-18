import { read, stop } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });
    return Response.json({ run }, { headers: { "cache-control": "no-store" } });
  },
  /** Ends the run: `run.py` aborts the OpenCode sessions in flight and exits, so the
   * response says what was signalled rather than claiming nothing more will happen. */
  DELETE(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });
    const stopped = stop(ctx.params.id);
    return Response.json({
      stopped,
      detail: stopped
        ? "Stopping: sessions in flight are being aborted and no further round will start."
        : "This run is not running, or its process is not reachable from this server.",
    }, { status: stopped ? 200 : 409 });
  },
});
