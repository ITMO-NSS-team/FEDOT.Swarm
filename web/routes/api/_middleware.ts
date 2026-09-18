import { running as runningPapers } from "@/lib/paperbench.ts";
import { running as runningTopics } from "@/lib/runs.ts";
import { define } from "@/utils.ts";

/** Two guards on the API. `FEDOTMAS_WEB_TOKEN`, when set, is required on every call that
 * starts, stops or deletes a run, as a bearer header or the cookie the front page sets
 * from `?token=`. `FEDOTMAS_MAX_RUNNING` caps how many runs may be in flight at once. */
const mutating = new Set(["POST", "DELETE", "PUT", "PATCH"]);
const starters = /^\/api\/(runs|paperbench)(\/[^/]+\/reproduce)?$/;

export function tokenOf(req: Request): string | null {
  const bearer = req.headers.get("authorization")?.match(/^Bearer\s+(.+)$/i);
  if (bearer) return bearer[1].trim();
  const cookie = req.headers.get("cookie")?.match(
    /(?:^|;\s*)fedotmas_token=([^;]+)/,
  );
  return cookie ? decodeURIComponent(cookie[1]) : null;
}

export const handler = define.middleware((ctx) => {
  const method = ctx.req.method.toUpperCase();
  if (!mutating.has(method)) return ctx.next();
  const required = Deno.env.get("FEDOTMAS_WEB_TOKEN");
  if (required && tokenOf(ctx.req) !== required) {
    return Response.json({ error: "A token is required for this action" }, {
      status: 401,
    });
  }
  const path = new URL(ctx.req.url).pathname;
  if (method === "POST" && starters.test(path)) {
    const max = Number(Deno.env.get("FEDOTMAS_MAX_RUNNING") ?? 2);
    if (Number.isFinite(max) && max > 0) {
      const busy = runningPapers() + runningTopics();
      if (busy >= max) {
        return Response.json({
          error: `${busy} run${
            busy === 1 ? " is" : "s are"
          } already in progress; wait for one to finish or stop it`,
        }, { status: 429 });
      }
    }
  }
  return ctx.next();
});
