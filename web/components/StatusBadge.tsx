import type { RunState } from "@/lib/types.ts";

const label: Record<RunState, string> = {
  starting: "Starting",
  running: "Running",
  done: "Finished",
  failed: "Failed",
  stopped: "Stopped",
  lost: "Lost",
};

const title: Partial<Record<RunState, string>> = {
  lost:
    "The server restarted while this run was in progress; its process is gone.",
};

export function StatusBadge({ state }: { state: RunState }) {
  return (
    <span class={`status-badge status-${state}`} title={title[state]}>
      {label[state]}
    </span>
  );
}
