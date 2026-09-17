import { useEffect, useState } from "preact/hooks";
import type { PaperRun } from "@/lib/paperbench.ts";

const live = (state: PaperRun["state"]) =>
  state === "running" || state === "starting";

const stepLabel: Record<string, string> = {
  parsing: "Reading PDF",
  swarm: "Writing code",
  judge: "Reviewing code",
};

function duration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function PaperResult({ run: initial }: { run: PaperRun }) {
  const [run, setRun] = useState(initial);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState<string | null>(null);

  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setCopied(path);
      setTimeout(
        () => setCopied((current) => current === path ? null : current),
        1500,
      );
    } catch {
      // Clipboard access can be blocked; the path is still visible as plain text.
    }
  };

  useEffect(() => {
    if (!live(run.state)) return;
    const timer = setInterval(async () => {
      const response = await fetch(`/api/paperbench/${run.id}`);
      if (response.ok) setRun(await response.json());
    }, 2000);
    return () => clearInterval(timer);
  }, [run.id, run.state]);

  const toggle = (id: string) => {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };

  const report = run.report;
  const percent = report ? Math.round(report.score * 100) : null;
  const progress = run.progress;

  return (
    <div class="panel paper-result">
      <header class="paper-head">
        <div>
          <p class="project-title-tag">{run.paper}</p>
          <span class={`status-badge status-${run.state}`}>{run.state}</span>
        </div>
        {percent !== null && (
          <div class="meter">
            <p class="meter-label">Score</p>
            <p class="meter-amount">{percent}%</p>
          </div>
        )}
      </header>

      {run.state === "failed" && (
        <p class="form-error" role="status">
          {run.error ?? "The run failed."}
        </p>
      )}

      {live(run.state) && (
        <div class="paper-progress">
          <div class="progress-track">
            <div
              class="progress-fill"
              style={{ width: `${progress?.percent ?? 0}%` }}
            />
          </div>
          <p class="hint">
            {progress ? stepLabel[progress.step] ?? progress.step : "Starting…"}
            · cut off after {Math.round(run.timeoutSeconds / 60)} min
          </p>
        </div>
      )}

      {report && (
        <>
          <p class="paper-caveat">
            Code-Dev · {report.branch}{" "}
            — one branch of the rubric, not a full PaperBench score.
          </p>
          <p class="hint">
            {report.roundsRun != null ? `${report.roundsRun} rounds · ` : ""}
            {report.swarmSeconds != null
              ? `Swarm: ${duration(report.swarmSeconds)}`
              : ""}
            {" · Judge: "}
            {report.judgeSeconds != null ? duration(report.judgeSeconds) : "—"}
            {report.compose
              ? ` · cast composed in ${report.compose.attempts} attempt${
                report.compose.attempts === 1 ? "" : "s"
              }${report.compose.fellBack ? " (fell back to a plain cast)" : ""}`
              : ""}
          </p>
          {report.usage?.judge && (
            <p class="hint">
              Judge (not covered by the spend meter above):{" "}
              {report.usage.judge.requests} req,{" "}
              {report.usage.judge.inputTokens + report.usage.judge.outputTokens}
              {" "}
              tok
            </p>
          )}
          {report.cast && report.cast.length > 1 && (
            <section class="paper-cast">
              <h2>Voices</h2>
              <ul class="checklist">
                {report.cast
                  .slice()
                  .sort((a, b) => b.score - a.score)
                  .map((member, index) => (
                    <li
                      key={member.id}
                      class={index === 0 ? "pass" : undefined}
                    >
                      <div class="check-row">
                        <span class="check-mark">
                          {index === 0 ? "★" : ""}
                        </span>
                        <span class="check-req">
                          {member.id}
                          {member.angle ? ` — ${member.angle}` : ""}
                        </span>
                        <span class="file-lines">
                          {Math.round(member.score * 100)}%
                        </span>
                      </div>
                    </li>
                  ))}
              </ul>
              <p class="hint">
                The kept code is the highest-scoring voice's last post; the
                files and checklist below are its code.
              </p>
            </section>
          )}
          <div class="paper-columns">
            <section>
              <h2>Files</h2>
              <ul class="file-list">
                {(report.files ?? []).map((file) => (
                  <li key={file.path}>
                    <div class="file-info">
                      <span class="file-name">{file.path}</span>
                      <span class="file-lines">{file.lines} lines</span>
                    </div>
                    <button
                      type="button"
                      class="copy-path"
                      onClick={() => copyPath(file.absPath)}
                    >
                      {copied === file.absPath ? "Copied" : "Copy path"}
                    </button>
                  </li>
                ))}
                {!report.files && (
                  <li class="empty">
                    This report predates per-file listing.
                  </li>
                )}
              </ul>
            </section>
            <section>
              <h2>Rubric checklist</h2>
              <ul class="checklist">
                {report.leaves.map((leaf) => {
                  const open = expanded.has(leaf.id);
                  return (
                    <li
                      key={leaf.id}
                      class={leaf.passed ? "pass" : "fail"}
                    >
                      <button
                        type="button"
                        class="check-row"
                        aria-expanded={open}
                        onClick={() => toggle(leaf.id)}
                      >
                        <span class="check-mark">
                          {leaf.passed ? "✓" : "×"}
                        </span>
                        <span class="check-req">{leaf.requirements}</span>
                      </button>
                      {open && <p class="check-reason">{leaf.reason}</p>}
                    </li>
                  );
                })}
              </ul>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
