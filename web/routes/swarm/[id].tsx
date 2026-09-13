import { HttpError } from "fresh";
import { Head } from "fresh/runtime";
import { SwarmView } from "@/islands/SwarmView.tsx";
import { read } from "@/lib/runs.ts";
import { define } from "@/utils.ts";

export default define.page(({ params }) => {
  const run = read(params.id);
  if (!run) throw new HttpError(404);
  return (
    <main id="main-content" class="wrap wrap-wide" tabIndex={-1}>
      <Head>
        <title>{run.topic} · FEDOT.MAS</title>
      </Head>
      <SwarmView run={run} />
    </main>
  );
});
