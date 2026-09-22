import { useState } from "preact/hooks";

interface Props {
  action: string;
  what: string;
  running: boolean;
}

/** A delete that asks first, and says when it will also stop a run in progress. */
export function ConfirmDelete({ action, what, running }: Props) {
  const [busy, setBusy] = useState(false);
  return (
    <form
      method="post"
      action={action}
      f-client-nav={false}
      onSubmit={(e) => {
        const question = running
          ? `Stop and delete ${what}? Its workspaces, report and log will be removed.`
          : `Delete ${what}? Its workspaces, report and log will be removed.`;
        if (!confirm(question)) {
          e.preventDefault();
          return;
        }
        setBusy(true);
      }}
    >
      <button
        type="submit"
        class="icon-btn danger"
        aria-label={running ? "Stop and delete" : "Delete"}
        title={running ? "Stop and delete" : "Delete"}
        disabled={busy}
      >
        {busy ? "…" : "×"}
      </button>
    </form>
  );
}
