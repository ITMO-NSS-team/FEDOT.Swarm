import { read, stop } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "not found" }, { status: 404 });
    return Response.json(run);
  },
  /** Ends the run. A persona mid-call still finishes its turn, so the response says
   * what was stopped rather than claiming nothing more will happen. */
  DELETE(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "not found" }, { status: 404 });
    const stopped = stop(ctx.params.id);
    return Response.json({
      stopped,
      detail: stopped
        ? "No further rounds will start; sessions already in flight still complete."
        : "This run is not owned by this server process.",
    }, { status: stopped ? 200 : 409 });
  },
});
