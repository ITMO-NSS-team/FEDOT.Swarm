import { read, reproduce } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

/** Starts the same request on the same inputs as a new run that points at this one. */
export const handler = define.handlers({
  POST(ctx) {
    const parent = read(ctx.params.id);
    if (!parent) {
      return Response.json({ error: "No such run" }, { status: 404 });
    }
    try {
      return Response.json({ run: reproduce(parent.id) }, { status: 201 });
    } catch (error) {
      const detail = error instanceof Error
        ? error.message
        : "Could not start the run";
      return Response.json({ error: detail }, { status: 502 });
    }
  },
});
