import { list } from "@/lib/runs.ts";
import { list as listPapers } from "@/lib/paperbench.ts";
import { StatusBadge } from "@/components/StatusBadge.tsx";
import { define } from "@/utils.ts";

const money = (value: unknown) =>
  typeof value === "number"
    ? (value < 0.01 ? `$${value.toFixed(6)}` : `$${value.toFixed(4)}`)
    : "—";

export default define.page(() => {
  const runs = list();
  const papers = listPapers();
  return (
    <main id="main-content" class="wrap" tabIndex={-1}>
      <div class="lede">
        <h1>Runs</h1>
        <p>
          Every swarm this server has started, with what it cost and why it
          ended.
        </p>
      </div>

      <h2>Free-topic swarms</h2>
      {runs.length === 0
        ? (
          <p class="empty">
            Nothing yet. <a href="/">Compose a swarm</a> to start one.
          </p>
        )
        : (
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
                </tr>
              ))}
            </tbody>
          </table>
        )}

      <h2>PaperBench swarms</h2>
      {papers.length === 0
        ? (
          <p class="empty">
            Nothing yet. <a href="/">Compose a swarm</a> against PaperBench to
            start one.
          </p>
        )
        : (
          <table class="results">
            <thead>
              <tr>
                <th>Paper</th>
                <th>Personas</th>
                <th>Score</th>
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
                      {run.compose ? "composed cast" : "identical attempts"}
                    </span>
                  </td>
                  <td>{run.personas}</td>
                  <td>
                    {run.report ? `${Math.round(run.report.score * 100)}%` : "—"}
                  </td>
                  <td>
                    <StatusBadge state={run.state} />
                  </td>
                  <td>
                    <form
                      method="post"
                      action={`/paperbench/${run.id}/delete`}
                      f-client-nav={false}
                    >
                      <button
                        type="submit"
                        class="icon-btn danger"
                        aria-label="Delete"
                        title="Delete"
                      >
                        ×
                      </button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </main>
  );
});
