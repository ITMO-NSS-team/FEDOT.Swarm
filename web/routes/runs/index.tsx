import { list } from "@/lib/runs.ts";
import { StatusBadge } from "@/components/StatusBadge.tsx";
import { define } from "@/utils.ts";

const money = (value: unknown) =>
  typeof value === "number"
    ? (value < 0.01 ? `$${value.toFixed(6)}` : `$${value.toFixed(4)}`)
    : "—";

export default define.page(() => {
  const runs = list();
  return (
    <main id="main-content" class="wrap" tabIndex={-1}>
      <div class="lede">
        <h1>Runs</h1>
        <p>
          Every swarm this server has started, with what it cost and why it
          ended.
        </p>
      </div>
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
    </main>
  );
});
