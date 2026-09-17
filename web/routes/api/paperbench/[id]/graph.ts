import { cast, lastStep, posts, topic, usage } from "@/lib/facts.ts";
import { buildGraph } from "@/lib/influence.ts";
import { paperPaths } from "@/lib/paths.ts";
import { read } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

/** The PaperBench twin of `/api/runs/[id]/graph.ts`: same store, same spec file, same
 * `buildGraph`, because `benchmarks/paperbench/run.py`'s swarm stage writes both in the
 * same shape `benchmarks/swarm/run.py` does. Under `--backend claude-code` there is no
 * usage sidecar (that backend runs on the subscription, not per-token, so `run.py` never
 * writes `paths.usage`) — `usage()` already reads a missing file as `[]`, the same as an
 * empty free-topic run before its first superstep, so `SwarmView`'s meter degrades to
 * nothing shown rather than an error. Under `--backend openrouter` `run.py`'s own `Tape`
 * plugin writes that file live, the same shape `benchmarks/swarm/run.py`'s does. */
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
