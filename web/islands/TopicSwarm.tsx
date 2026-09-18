import { useEffect, useState } from "preact/hooks";
import { type Snapshot, SwarmView } from "@/components/SwarmView.tsx";
import { usePoll } from "@/lib/poll.ts";
import { live, type RunState, terminal } from "@/lib/types.ts";

interface Props {
  base: string;
  fallbackTopic: string;
  rounds: number;
  initialState: RunState;
  cap: string;
}

/** The free-topic run page: one poller feeding the graph view. */
export function TopicSwarm(
  { base, fallbackTopic, rounds, initialState, cap }: Props,
) {
  const [scrub, setScrub] = useState<number | null>(null);
  const [active, setActive] = useState(live(initialState));
  const url = `${base}/graph${scrub === null ? "" : `?step=${scrub}`}`;
  const { data, error, refresh } = usePoll<Snapshot>(url, active);

  useEffect(() => {
    if (data && terminal(data.state)) setActive(false);
  }, [data?.state]);

  const stop = async () => {
    const response = await fetch(base, { method: "DELETE" });
    const body = await response.json().catch(() => ({}));
    refresh();
    return body.detail ?? body.error ?? null;
  };

  return (
    <SwarmView
      snapshot={data}
      failure={error}
      fallbackTopic={fallbackTopic}
      rounds={rounds}
      initialState={initialState}
      cap={cap}
      scrub={scrub}
      onScrub={setScrub}
      onStop={stop}
    />
  );
}
