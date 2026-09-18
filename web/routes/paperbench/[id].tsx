import { HttpError } from "fresh";
import { Head } from "fresh/runtime";
import { type Lineage, PaperSwarm } from "@/islands/PaperSwarm.tsx";
import { list, read } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

export default define.page(({ params }) => {
  const run = read(params.id);
  if (!run) throw new HttpError(404);
  const parent = run.parentId ? read(run.parentId) : null;
  const lineage: Lineage = {
    parent: parent ? { id: parent.id, paper: parent.paper } : null,
    children: list().filter((r) => r.parentId === run.id).map((r) => ({
      id: r.id,
      state: r.state,
      score: r.report ? r.report.score : null,
    })),
  };
  return (
    <main id="main-content" class="wrap wrap-wide" tabIndex={-1}>
      <Head>
        <title>{run.paper} · FEDOT.Swarm</title>
        <link rel="icon" type="image/svg+xml" href="/icon-paper.svg" />
      </Head>
      <PaperSwarm run={run} lineage={lineage} />
    </main>
  );
});
