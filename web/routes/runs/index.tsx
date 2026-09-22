import { ConfirmDelete } from "@/islands/ConfirmDelete.tsx";
import { RunsRefresh } from "@/islands/RunsRefresh.tsx";
import { list } from "@/lib/runs.ts";
import { list as listPapers, type PaperRun } from "@/lib/paperbench.ts";
import { StatusBadge } from "@/components/StatusBadge.tsx";
import { terminal } from "@/lib/types.ts";
import { Head } from "fresh/runtime";
import { define } from "@/utils.ts";

const money = (value: unknown) =>
  typeof value === "number"
    ? (value === 0
      ? "$0"
      : value < 0.01
      ? `$${value.toFixed(5)}`
      : `$${value.toFixed(3)}`)
    : "—";

function spent(run: PaperRun): number | null {
  const total = run.report?.budget?.usd;
  const workers = run.report?.usage?.workers?.usd;
  if (typeof total === "number") return total;
  return typeof workers === "number" ? workers : null;
}

export default define.page(() => {
  const runs = list();
  const papers = listPapers();
  const byId = new Map(papers.map((p) => [p.id, p]));
  const children = new Map<string, number>();
  for (const p of papers) {
    if (p.parentId) {
      children.set(p.parentId, (children.get(p.parentId) ?? 0) + 1);
    }
  }
  const active = [...runs, ...papers].some((r) => !terminal(r.state));
  return (
    <main id="main-content" class="wrap" tabIndex={-1}>
      <Head>
        <title>Runs · FEDOT.Swarm</title>
        <link rel="icon" type="image/svg+xml" href="/icon-runs.svg" />
      </Head>
      <RunsRefresh active={active} />
      <div class="lede">
        <h1>Runs</h1>
        <p>
          Every swarm this server has started, with what it cost and how it
          ended. Finished PaperBench runs keep their workspaces, so any of them
          can be explored or reproduced.
          {active ? " This page refreshes while a run is in progress." : ""}
        </p>
      </div>

      <h2>PaperBench swarms</h2>
      {papers.length === 0
        ? (
          <p class="empty">
            Nothing yet. <a href="/">Compose a swarm</a>{" "}
            against PaperBench to start one.
          </p>
        )
        : (
          <div class="table-scroll">
            <table class="results">
              <thead>
                <tr>
                  <th>Paper</th>
                  <th>Voices</th>
                  <th>Rounds</th>
                  <th>Score</th>
                  <th>Spent</th>
                  <th>Lineage</th>
                  <th>State</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {papers.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <a href={`/paperbench/${run.id}`}>{run.paper}</a>
                      <span class="row-note">
                        {run.workers === "opencode"
                          ? "OpenCode agents"
                          : "prompt voices"}
                        {run.compose ? ", composed cast" : ", plain cast"}
                        {" · "}
                        {run.model.split("/").at(-1)}
                        {" · "}
                        {new Date(run.startedAt).toLocaleString()}
                      </span>
                    </td>
                    <td>{run.personas}</td>
                    <td>
                      {run.report?.roundsRun ?? run.progress?.round ?? "—"} of
                      {" "}
                      {run.rounds}
                    </td>
                    <td>
                      {run.report
                        ? `${Math.round(run.report.score * 100)}%`
                        : "—"}
                    </td>
                    <td>{money(spent(run))}</td>
                    <td>
                      {run.parentId && byId.has(run.parentId) && (
                        <span class="row-note">
                          from{" "}
                          <a href={`/paperbench/${run.parentId}`}>
                            {run.parentId.slice(0, 8)}
                          </a>
                        </span>
                      )}
                      {children.get(run.id)
                        ? (
                          <span class="row-note">
                            {children.get(run.id)} reproduced
                          </span>
                        )
                        : null}
                      {!run.parentId && !children.get(run.id) ? "—" : null}
                    </td>
                    <td>
                      <StatusBadge state={run.state} />
                    </td>
                    <td>
                      <ConfirmDelete
                        action={`/paperbench/${run.id}/delete`}
                        what={`the run on ${run.paper}`}
                        running={!terminal(run.state)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

      <h2>Free-topic swarms</h2>
      {runs.length === 0
        ? (
          <p class="empty">
            Nothing yet. <a href="/">Compose a swarm</a> to start one.
          </p>
        )
        : (
          <div class="table-scroll">
            <table class="results">
              <thead>
                <tr>
                  <th>Topic</th>
                  <th>Cast</th>
                  <th>Rounds</th>
                  <th>Requests</th>
                  <th>Spent</th>
                  <th>Ended on</th>
                  <th>State</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <a href={`/swarm/${run.id}`}>{run.topic}</a>
                      <span class="row-note">
                        {run.compose ? "composed" : "handwritten"}
                        {run.ranked ? ", a feed each" : ""}
                        {run.seats ? `, ${run.seats} seats` : ""}
                      </span>
                    </td>
                    <td>{run.personas}</td>
                    <td>{String(run.report?.rounds ?? "—")} of {run.rounds}</td>
                    <td>{String(run.report?.requests ?? "—")}</td>
                    <td>{money(run.report?.usd)}</td>
                    <td>{String(run.report?.reason ?? "—")}</td>
                    <td>
                      <StatusBadge state={run.state} />
                    </td>
                    <td>
                      <ConfirmDelete
                        action={`/runs/${run.id}/delete`}
                        what={`the swarm on "${run.topic}"`}
                        running={!terminal(run.state)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </main>
  );
});
