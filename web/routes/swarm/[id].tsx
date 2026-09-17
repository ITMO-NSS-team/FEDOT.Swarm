import { HttpError } from "fresh";
import { Head } from "fresh/runtime";
import { SwarmView } from "@/islands/SwarmView.tsx";
import { read } from "@/lib/runs.ts";
import { define } from "@/utils.ts";

function money(value: number) {
  return value < 0.01 ? `$${value.toFixed(6)}` : `$${value.toFixed(4)}`;
}

const cap = (run: { usd: number; tokens: number; requests: number }) =>
  run.usd
    ? money(run.usd)
    : run.tokens
    ? `${run.tokens.toLocaleString("en")} tokens`
    : `${run.requests} requests`;

export default define.page(({ params }) => {
  const run = read(params.id);
  if (!run) throw new HttpError(404);
  return (
    <main id="main-content" class="wrap wrap-wide" tabIndex={-1}>
      <Head>
        <title>{run.topic} · FEDOT.MAS</title>
      </Head>
      <SwarmView
        base={`/api/runs/${run.id}`}
        fallbackTopic={run.topic}
        rounds={run.rounds}
        initialState={run.state}
        cap={cap(run)}
        canStop
      />
    </main>
  );
});
