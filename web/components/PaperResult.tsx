import { Icon, type IconName } from "@/components/Icon.tsx";
import { useEffect, useState } from "preact/hooks";
import { FileBrowser } from "@/islands/FileBrowser.tsx";
import type { Lineage } from "@/islands/PaperSwarm.tsx";
import type { PaperProgress, PaperRun, PaperTrace } from "@/lib/paperbench.ts";
import { live as isLive, type LiveBoard, type Post } from "@/lib/types.ts";

const phaseLabel = (progress: PaperProgress | null, run: PaperRun) => {
  if (!progress) return "Starting";
  switch (progress.step) {
    case "parsing":
      return `Reading the PDF (${progress.engine ?? run.pdfEngine})`;
    case "swarm":
      return progress.stage === "compose"
        ? "Composing the cast"
        : `Writing code, round ${
          Math.min((progress.round ?? 0) + 1, run.rounds)
        } of ${run.rounds}`;
    case "judge":
      return "Reviewing the code";
    default:
      return progress.step;
  }
};

export function money(value: number | undefined | null) {
  if (value === undefined || value === null) return "—";
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(5)}` : `$${value.toFixed(3)}`;
}

function duration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

async function postJson(url: string): Promise<Record<string, unknown>> {
  const response = await fetch(url, { method: "POST" });
  const text = await response.text();
  let body: Record<string, unknown> = {};
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`Unexpected reply (${response.status})`);
  }
  if (!response.ok) {
    throw new Error(
      String(body.error ?? `Request failed (${response.status})`),
    );
  }
  return body;
}

interface SummaryProps {
  run: PaperRun;
  progress: PaperProgress | null;
  onExplore: (tab: string) => void;
}

/** The side-column card: phase or score, the kept voice, and the two actions a visitor
 * takes on a finished run. */
export function PaperSummary({ run, progress, onExplore }: SummaryProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const report = run.report;
  const percent = report ? Math.round(report.score * 100) : null;

  const reproduce = async () => {
    if (!confirm("Start the same run again on the same inputs?")) return;
    setBusy(true);
    setError(null);
    try {
      const body = await postJson(`/api/paperbench/${run.id}/reproduce`);
      location.href = `/paperbench/${(body.run as { id: string }).id}`;
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not start the run",
      );
      setBusy(false);
    }
  };

  return (
    <section class="panel paper-result">
      <header class="paper-head">
        <div>
          <p class="project-title-tag">{run.paper}</p>
          <p class="hint">
            {run.personas}{" "}
            {run.workers === "opencode" ? "coding agents" : "voices"}
            {" · "}
            {run.rounds} rounds · {run.compose ? "composed cast" : "plain cast"}
          </p>
        </div>
        {percent !== null && (
          <div class="meter meter-score">
            <p class="meter-label">Score</p>
            <p class="meter-amount">{percent}%</p>
          </div>
        )}
      </header>

      {(run.state === "failed" || run.state === "lost") && (
        <p class="form-error" role="status">
          {run.error ?? "The run failed."}
        </p>
      )}

      {isLive(run.state) && (
        <div class="paper-progress">
          <div class="progress-track">
            <div
              class="progress-fill"
              style={{ width: `${progress?.percent ?? 0}%` }}
            />
          </div>
          <p class="hint">{phaseLabel(progress, run)}</p>
        </div>
      )}

      {report && (
        <>
          <p class="paper-caveat">
            {report.leaves.filter((l) => l.passed).length} of{" "}
            {report.leaves.length} rubric leaves passed, by weight{" "}
            {percent}%. One Code Development branch, graded by reading, never by
            running.
          </p>
          {report.kept && (
            <p class="hint">
              Kept: the workspace of <strong>{report.kept.voice}</strong>
              {report.usage?.workers
                ? ` · agents billed ${money(report.usage.workers.usd)}`
                : ""}
              {report.swarmSeconds !== undefined
                ? ` · swarm ${duration(report.swarmSeconds)}`
                : ""}
              {report.judgeSeconds !== undefined
                ? `, judge ${duration(report.judgeSeconds)}`
                : ""}
            </p>
          )}
          <div class="paper-actions">
            <button
              type="button"
              class="secondary-button"
              onClick={() => onExplore("files")}
            >
              Browse the code
            </button>
            <a
              class="secondary-button"
              href={`/api/paperbench/${run.id}/download?root=solution`}
              download
            >
              Download zip
            </a>
          </div>
        </>
      )}
      {run.state !== "starting" && run.state !== "running" && (
        <div class="paper-actions">
          <button
            type="button"
            class="primary-button"
            disabled={busy}
            onClick={reproduce}
          >
            {busy ? "Starting…" : "Reproduce this run"}
          </button>
        </div>
      )}
      {error && <p class="form-error" role="alert">{error}</p>}
    </section>
  );
}

type Tab = "voices" | "rubric" | "files" | "details";

interface ExploreProps {
  run: PaperRun;
  lineage: Lineage;
  live: LiveBoard;
  posts: Post[];
  focus: { tab: string; root: string } | null;
}

/** The full-width explorer under the graph: who did what, the rubric verdicts, the files,
 * and everything needed to tell this run apart from another and run it again. */
export function PaperExplore(
  { run, lineage, live, posts, focus }: ExploreProps,
) {
  const [tab, setTab] = useState<Tab>("voices");
  const [root, setRoot] = useState("solution");
  const [filter, setFilter] = useState<"all" | "failed">("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!focus) return;
    setTab(focus.tab as Tab);
    setRoot(focus.root);
  }, [focus]);

  const report = run.report;
  const voices = new Set<string>();
  for (const member of report?.cast ?? []) voices.add(member.id);
  for (const post of posts) voices.add(post.producer);
  for (const name of Object.keys(live)) voices.add(name);
  const trace: Record<string, PaperTrace> = report?.trace ?? {};

  const roundsByVoice = new Map<string, Post[]>();
  for (const post of posts) {
    roundsByVoice.set(post.producer, [
      ...(roundsByVoice.get(post.producer) ?? []),
      post,
    ]);
  }

  const rows = [...voices].map((name) => {
    const member = report?.cast?.find((m) => m.id === name);
    const own = roundsByVoice.get(name) ?? [];
    const t = trace[name];
    return {
      name,
      score: member?.score,
      graded: member?.graded,
      rounds: t?.rounds ?? own.length,
      cost: t?.cost ?? own.reduce((n, p) => n + (p.meta?.cost ?? 0), 0),
      files: t?.filesChanged ??
        own.reduce((n, p) => n + (p.meta?.files.length ?? 0), 0),
      tools: t?.toolCalls ??
        own.reduce((n, p) => n + (p.meta?.toolCalls ?? 0), 0),
      timedOut: t?.timedOut ?? own.filter((p) => p.meta?.timedOut).length,
      state: live[name]?.state,
      kept: report?.kept?.voice === name,
    };
  }).sort((a, b) =>
    (b.score ?? -1) - (a.score ?? -1) || a.name.localeCompare(b.name)
  );

  const leaves = (report?.leaves ?? []).filter((leaf) =>
    filter === "all" || !leaf.passed
  );
  const toggle = (id: string) => {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard access can be blocked; the text is visible anyway
    }
  };

  const roots = [
    { key: "solution", label: "Kept solution" },
    ...[...voices].sort().map((v) => ({
      key: `ws/${v}`,
      label: `Workspace of ${v}`,
    })),
    { key: "inputs", label: "Inputs" },
  ];

  const tabs: { key: Tab; label: string; icon: IconName }[] = [
    { key: "voices", label: "Voices", icon: "voices" },
    { key: "rubric", label: "Rubric", icon: "rubric" },
    { key: "files", label: "Files", icon: "files" },
    { key: "details", label: "Run details", icon: "details" },
  ];

  return (
    <section id="explore" class="panel paper-explore">
      <header class="paper-explore-head">
        <h2>Explore the run</h2>
        <div class="tabs" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
            >
              <Icon name={t.icon} size={16} />
              <span>{t.label}</span>
            </button>
          ))}
        </div>
      </header>

      {tab === "voices" && (
        <div class="table-scroll">
          <table class="results results-flat">
            <thead>
              <tr>
                <th>Voice</th>
                <th>Score</th>
                <th>Rounds</th>
                <th>Files changed</th>
                <th>Tool calls</th>
                <th>Cost</th>
                <th>Now</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name} class={row.kept ? "row-kept" : undefined}>
                  <td>
                    {row.kept ? "★ " : ""}
                    {row.name}
                  </td>
                  <td>
                    {row.score === undefined
                      ? "—"
                      : row.graded === false
                      ? "not graded"
                      : `${Math.round(row.score * 100)}%`}
                  </td>
                  <td>{row.rounds}</td>
                  <td>{row.files}</td>
                  <td>{row.tools}</td>
                  <td>{money(row.cost)}</td>
                  <td>
                    {row.state === "working"
                      ? "working"
                      : row.timedOut
                      ? `${row.timedOut} timed out`
                      : "idle"}
                  </td>
                  <td>
                    <button
                      type="button"
                      class="link-button"
                      onClick={() => {
                        setRoot(`ws/${row.name}`);
                        setTab("files");
                      }}
                    >
                      Open workspace
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} class="empty">No voice has worked yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "rubric" && (
        <div class="rubric">
          {report
            ? (
              <>
                <div class="rubric-head">
                  <p class="hint">
                    {report.leaves.filter((l) => l.passed).length} passed,{" "}
                    {report.leaves.filter((l) => !l.passed).length}{" "}
                    failed. The judge read the kept workspace and answered leaf
                    by leaf.
                  </p>
                  <div class="segmented" role="group" aria-label="Filter">
                    <button
                      type="button"
                      aria-pressed={filter === "all"}
                      onClick={() => setFilter("all")}
                    >
                      All
                    </button>
                    <button
                      type="button"
                      aria-pressed={filter === "failed"}
                      onClick={() => setFilter("failed")}
                    >
                      Failed only
                    </button>
                  </div>
                </div>
                <ul class="checklist">
                  {leaves.map((leaf) => {
                    const open = expanded.has(leaf.id);
                    return (
                      <li key={leaf.id} class={leaf.passed ? "pass" : "fail"}>
                        <button
                          type="button"
                          class="check-row"
                          aria-expanded={open}
                          onClick={() =>
                            toggle(leaf.id)}
                        >
                          <span class="check-mark">
                            {leaf.passed ? "✓" : "×"}
                          </span>
                          <span class="check-req">{leaf.requirements}</span>
                          <span class="file-lines">w {leaf.weight}</span>
                        </button>
                        {open && <p class="check-reason">{leaf.reason}</p>}
                      </li>
                    );
                  })}
                </ul>
              </>
            )
            : <p class="empty">The rubric is graded when the run finishes.</p>}
        </div>
      )}

      {tab === "files" && (
        <FileBrowser id={run.id} roots={roots} root={root} onRoot={setRoot} />
      )}

      {tab === "details" && (
        <div class="details">
          <h3>Command</h3>
          {report?.command
            ? (
              <div class="command">
                <pre>{report.command}</pre>
                <button
                  type="button"
                  class="secondary-button"
                  onClick={() => copy(report.command!)}
                >
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            )
            : <p class="hint">Recorded when the run finishes.</p>}

          <h3>Inputs</h3>
          <dl class="kv">
            <div>
              <dt>Paper</dt>
              <dd>
                {run.inputs?.paperName ?? run.paper}
                {run.inputs?.kind === "pdf" && (
                  <>
                    {" · "}
                    <a
                      href={`/api/paperbench/${run.id}/download?root=inputs&path=paper.pdf`}
                    >
                      paper.pdf
                    </a>
                  </>
                )}
                {run.inputs?.paperSha256 && (
                  <span class="hash">
                    sha256 {run.inputs.paperSha256.slice(0, 16)}…
                  </span>
                )}
              </dd>
            </div>
            <div>
              <dt>Rubric</dt>
              <dd>
                {report?.leaves.length ?? "?"} leaves
                {run.inputs?.kind !== "bundled" && (
                  <>
                    {" · "}
                    <a
                      href={`/api/paperbench/${run.id}/download?root=inputs&path=rubric_branch.json`}
                    >
                      rubric_branch.json
                    </a>
                  </>
                )}
                {run.inputs?.rubricSha256 && (
                  <span class="hash">
                    sha256 {run.inputs.rubricSha256.slice(0, 16)}…
                  </span>
                )}
              </dd>
            </div>
            <div>
              <dt>PDF engine</dt>
              <dd>
                {String(report?.inputs?.engine ?? run.pdfEngine)}
                {report?.inputs?.fallbackFrom
                  ? ` (fell back from ${report.inputs.fallbackFrom})`
                  : ""}
              </dd>
            </div>
          </dl>

          <h3>Parameters</h3>
          <dl class="kv">
            <div>
              <dt>Workers</dt>
              <dd>
                {run.workers === "opencode"
                  ? `OpenCode agents, ${run.roundMinutes} min and ${run.steps} steps per round`
                  : "one prompt per round"}
              </dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{run.model}</dd>
            </div>
            <div>
              <dt>Cast</dt>
              <dd>
                {run.personas} voices, {run.rounds} rounds,{" "}
                {run.compose ? "composed" : "handwritten"}
                {run.ranked ? ", a feed each" : ", one shared wall"}
                {run.seats ? `, ${run.seats} free seats` : ""}
              </dd>
            </div>
            <div>
              <dt>Seed</dt>
              <dd>
                {run.seed}. The seed fixes which voices the activity sampler
                wakes each round, not what the model writes.
              </dd>
            </div>
            <div>
              <dt>Cap</dt>
              <dd>
                {run.usd ? `$${run.usd}` : ""}
                {run.tokens ? `${run.tokens} tokens` : ""}
                {run.requests ? `${run.requests} requests` : ""}
                {report?.budget
                  ? ` · spent ${
                    money(Number(report.budget.usd ?? 0))
                  } by token count${
                    report.budget.stopped ? ", cap reached" : ""
                  }`
                  : ""}
              </dd>
            </div>
            <div>
              <dt>Concurrency</dt>
              <dd>{run.concurrency} voices at once</dd>
            </div>
          </dl>

          {report?.usage && (
            <>
              <h3>Usage</h3>
              <div class="table-scroll">
                <table class="results results-flat">
                  <thead>
                    <tr>
                      <th>Phase</th>
                      <th>Requests</th>
                      <th>Tokens in</th>
                      <th>Tokens out</th>
                      <th>Billed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(["swarm", "workers", "judge"] as const).map((phase) => {
                      const u = report.usage?.[phase];
                      if (!u) return null;
                      return (
                        <tr key={phase}>
                          <td>
                            {phase === "swarm"
                              ? "Composer, queen, prompt voices"
                              : phase === "workers"
                              ? "OpenCode agents"
                              : "Judge"}
                          </td>
                          <td>{u.requests}</td>
                          <td>{u.inputTokens.toLocaleString("en")}</td>
                          <td>{u.outputTokens.toLocaleString("en")}</td>
                          <td>{u.usd !== undefined ? money(u.usd) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h3>Lineage</h3>
          <p class="hint">
            {lineage.parent
              ? (
                <>
                  Reproduced from{" "}
                  <a href={`/paperbench/${lineage.parent.id}`}>
                    {lineage.parent.paper} ({lineage.parent.id})
                  </a>.
                </>
              )
              : "Started from the Compose form."}
          </p>
          {lineage.children.length > 0 && (
            <ul class="lineage">
              {lineage.children.map((child) => (
                <li key={child.id}>
                  <a href={`/paperbench/${child.id}`}>{child.id}</a>{" "}
                  <span class={`status-badge status-${child.state}`}>
                    {child.state}
                  </span>
                  {child.score !== null && ` ${Math.round(child.score * 100)}%`}
                </li>
              ))}
            </ul>
          )}

          {report?.errors && report.errors.length > 0 && (
            <>
              <h3>Errors during the run</h3>
              <ul class="lineage">
                {report.errors.map((e, i) => (
                  <li key={i}>
                    round {e.step + 1}, {e.producer}: {e.error}
                  </li>
                ))}
              </ul>
            </>
          )}

          <h3>Where it lives</h3>
          <p class="hint">
            Run {run.id}. Started {new Date(run.startedAt).toLocaleString()}
            {run.endedAt
              ? `, ended ${new Date(run.endedAt).toLocaleString()}`
              : ""}
            {report?.workdir ? `. Workdir: ${report.workdir}` : ""}
          </p>
        </div>
      )}
    </section>
  );
}
