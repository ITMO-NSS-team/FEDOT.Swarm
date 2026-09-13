import { read, stop } from "@/lib/runs.ts";
import { define } from "@/utils.ts";

export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });
    return Response.json({ run });
  },
  /** Ends the conversation. Requests already with the provider are still billed, so the
   * response says what was stopped rather than claiming the run cost nothing more. */
  DELETE(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });
    const stopped = stop(ctx.params.id);
    return Response.json({
      stopped,
      detail: stopped
        ? "No further rounds will start; requests already in flight still complete."
        : "This run is not owned by this server process.",
    }, { status: stopped ? 200 : 409 });
  },
});
