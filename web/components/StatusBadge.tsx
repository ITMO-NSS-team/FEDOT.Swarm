import type { RunState } from "@/lib/types.ts";

const label: Record<RunState, string> = {
  starting: "Starting",
  running: "Running",
  done: "Finished",
  failed: "Failed",
  stopped: "Stopped",
};

export function StatusBadge({ state }: { state: RunState }) {
  return <span class={`status-badge status-${state}`}>{label[state]}</span>;
}
