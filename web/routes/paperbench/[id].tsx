import { HttpError } from "fresh";
import { Head } from "fresh/runtime";
import { PaperResult } from "@/islands/PaperResult.tsx";
import { SwarmView } from "@/islands/SwarmView.tsx";
import { read } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

function money(value: number) {
  return value < 0.01 ? `$${value.toFixed(6)}` : `$${value.toFixed(4)}`;
}

/** Every run has the wall-clock cap; only an openrouter run started with a nonzero
 * usd/tokens/requests also has a spend cap, on top of it rather than instead of it (see
 * `run.py`'s `WallClock`). */
function cap(
  run: { timeoutSeconds: number; backend: string; usd: number; tokens: number; requests: number },
) {
  const minutes = `${Math.round(run.timeoutSeconds / 60)} min`;
  if (run.backend !== "openrouter" || !(run.usd || run.tokens || run.requests)) {
    return `${minutes} per session`;
  }
  const spend = run.usd
    ? money(run.usd)
    : run.tokens
    ? `${run.tokens.toLocaleString("en")} tokens`
    : `${run.requests} requests`;
  return `${minutes} per session · ${spend}`;
}

export default define.page(({ params }) => {
  const run = read(params.id);
  if (!run) throw new HttpError(404);
  return (
    <main id="main-content" class="wrap wrap-wide" tabIndex={-1}>
      <Head>
        <title>{run.paper} · FEDOT.MAS</title>
      </Head>
      <SwarmView
        base={`/api/paperbench/${run.id}`}
        fallbackTopic={run.paper}
        rounds={run.rounds}
        initialState={run.state}
        cap={cap(run)}
        canStop
      >
        <PaperResult run={run} />
      </SwarmView>
    </main>
  );
});
