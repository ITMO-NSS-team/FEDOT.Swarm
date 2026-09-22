import { create, list } from "@/lib/runs.ts";
import { InvalidRequest, parseRequest } from "@/lib/validate.ts";
import { define } from "@/utils.ts";

export const handler = define.handlers({
  GET() {
    return Response.json({ runs: list() });
  },
  async POST(ctx) {
    let body: unknown;
    try {
      body = await ctx.req.json();
    } catch {
      return Response.json({ error: "Expected a JSON body" }, { status: 400 });
    }
    try {
      return Response.json({ run: create(parseRequest(body)) }, {
        status: 201,
      });
    } catch (error) {
      if (error instanceof InvalidRequest) {
        return Response.json({ error: error.message }, { status: 422 });
      }
      const detail = error instanceof Error
        ? error.message
        : "Could not start the run";
      return Response.json({ error: detail }, { status: 502 });
    }
  },
});
