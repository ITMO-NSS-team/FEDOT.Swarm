import { useEffect, useState } from "preact/hooks";
import { type Snapshot, SwarmView } from "@/components/SwarmView.tsx";
import { PaperExplore, PaperSummary } from "@/components/PaperResult.tsx";
import type { PaperProgress, PaperRun } from "@/lib/paperbench.ts";
import { usePoll } from "@/lib/poll.ts";
import { live, terminal } from "@/lib/types.ts";

export interface Lineage {
  parent: { id: string; paper: string } | null;
  children: { id: string; state: string; score: number | null }[];
}

interface PaperSnapshot extends Snapshot {
  run: PaperRun;
  progress: PaperProgress | null;
}

interface Props {
  run: PaperRun;
  lineage: Lineage;
}

/** The PaperBench run page: one poller feeds the graph, the side summary and the explorer
 * below, so the badge, the phase and the score never disagree. */
export function PaperSwarm({ run: initial, lineage }: Props) {
  const base = `/api/paperbench/${initial.id}`;
  const [scrub, setScrub] = useState<number | null>(null);
  const [active, setActive] = useState(live(initial.state));
  const [focus, setFocus] = useState<{ tab: string; root: string } | null>(
    null,
  );
  const url = `${base}/graph${scrub === null ? "" : `?step=${scrub}`}`;
  const { data, error, refresh } = usePoll<PaperSnapshot>(url, active);

  useEffect(() => {
    if (data && terminal(data.state)) setActive(false);
  }, [data?.state]);

  const run = data?.run ?? initial;

  const stop = async () => {
    const response = await fetch(base, { method: "DELETE" });
    const body = await response.json().catch(() => ({}));
    refresh();
    return body.detail ?? body.error ?? null;
  };

  const openWorkspace = (voice: string) => {
    setFocus({ tab: "files", root: `ws/${voice}` });
    document.getElementById("explore")?.scrollIntoView({ behavior: "smooth" });
  };

  const cap = [
    `${run.roundMinutes} min per round`,
    run.usd
      ? `$${run.usd}`
      : run.tokens
      ? `${run.tokens.toLocaleString("en")} tokens`
      : `${run.requests} requests`,
  ].join(" · ");

  return (
    <>
      <SwarmView
        snapshot={data}
        failure={error}
        fallbackTopic={run.paper}
        rounds={run.rounds}
        initialState={initial.state}
        cap={cap}
        scrub={scrub}
        onScrub={setScrub}
        onStop={stop}
        onOpenWorkspace={openWorkspace}
      >
        <PaperSummary
          run={run}
          progress={data?.progress ?? run.progress ?? null}
          onExplore={(tab) => {
            setFocus({ tab, root: "solution" });
            document.getElementById("explore")?.scrollIntoView({
              behavior: "smooth",
            });
          }}
        />
      </SwarmView>
      <PaperExplore
        run={run}
        lineage={lineage}
        live={data?.live ?? {}}
        posts={data?.posts ?? []}
        focus={focus}
      />
    </>
  );
}
