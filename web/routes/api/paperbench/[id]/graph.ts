import { cast, lastStep, posts, topic, usage } from "@/lib/facts.ts";
import { buildGraph } from "@/lib/influence.ts";
import { paperPaths } from "@/lib/paths.ts";
import { live, read } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

/** The PaperBench twin of `/api/runs/[id]/graph.ts`, plus the run record itself, its
 * progress and the live board, so one poll feeds the whole page. */
export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });

    const paths = paperPaths(run.id);
    const steps = lastStep(paths.db);
    const asked = new URL(ctx.req.url).searchParams.get("step");
    const step = asked !== null && /^\d+$/.test(asked)
      ? Math.min(Number(asked), steps)
      : steps;

    const all = posts(paths.db);
    const graph = buildGraph(all, cast(paths.spec), step, {
      ranked: run.ranked,
      topic: topic(paths.db) || run.paper,
      steps,
    });

    return new Response(
      JSON.stringify({
        graph,
        step,
        state: run.state,
        report: run.report,
        error: run.error,
        usage: usage(paths.usage),
        posts: all.filter((p) => p.step <= step).slice(-60),
        run,
        progress: run.progress ?? null,
        live: live(run.id),
      }),
      {
        headers: {
          "content-type": "application/json",
          "cache-control": "no-store",
        },
      },
    );
  },
});
