import { cast, lastStep, posts, topic, usage } from "@/lib/facts.ts";
import { buildGraph } from "@/lib/influence.ts";
import { runPaths } from "@/lib/paths.ts";
import { read } from "@/lib/runs.ts";
import { define } from "@/utils.ts";

/** The live picture: the graph as of one superstep, the posts behind it, and where the run
 * has got to. Polled rather than streamed, because the store commits once per superstep and
 * a superstep is seconds long: an event stream would carry the same snapshot with more
 * moving parts. */
export const handler = define.handlers({
  GET(ctx) {
    const run = read(ctx.params.id);
    if (!run) return Response.json({ error: "No such run" }, { status: 404 });

    const paths = runPaths(run.id);
    const steps = lastStep(paths.db);
    const asked = new URL(ctx.req.url).searchParams.get("step");
    const step = asked !== null && /^\d+$/.test(asked)
      ? Math.min(Number(asked), steps)
      : steps;

    const all = posts(paths.db);
    const graph = buildGraph(all, cast(paths.spec), step, {
      ranked: run.ranked,
      topic: topic(paths.db) || run.topic,
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
