import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Simulation } from "@/lib/force.ts";
import { feedWidth } from "@/lib/influence.ts";
import type { Graph, GraphNode, Post, Run, RunState } from "@/lib/types.ts";

interface UsageTick {
  index: number;
  fired: number;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
}

interface Snapshot {
  graph: Graph;
  step: number;
  state: RunState;
  report: Record<string, unknown> | null;
  error: string | null;
  usage: UsageTick[];
  posts: Post[];
}

const live = (state: RunState) => state === "running" || state === "starting";

function money(value: number) {
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(6)}` : `$${value.toFixed(4)}`;
}

export function SwarmView({ run }: { run: Run }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [following, setFollowing] = useState(true);
  const [scrub, setScrub] = useState<number | null>(null);
  const [, redraw] = useState(0);

  const simulation = useRef(new Simulation());
  const svg = useRef<SVGSVGElement>(null);
  const dragging = useRef<string | null>(null);

  const step = scrub;
  const state = snapshot?.state ?? run.state;

  useEffect(() => {
    let stop = false;
    const pull = async () => {
      const query = step === null ? "" : `?step=${step}`;
      try {
        const response = await fetch(`/api/runs/${run.id}/graph${query}`);
        if (!response.ok) {
          throw new Error((await response.json()).error ?? "unavailable");
        }
        if (!stop) {
          setSnapshot(await response.json());
          setFailure(null);
        }
      } catch (error) {
        if (!stop) {
          setFailure(
            error instanceof Error ? error.message : "The run is unreachable",
          );
        }
      }
    };
    pull();
    // a superstep is seconds long and commits as one batch, so polling at this cadence
    // never shows a half-written round
    const timer = setInterval(() => {
      if (live(state)) pull();
    }, 2000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [run.id, step, state, following]);

  const graph = snapshot?.graph;

  useEffect(() => {
    if (!graph) return;
    simulation.current.sync(
      graph.nodes.map((n) => n.name),
      graph.edges.map((e) => ({ from: e.from, to: e.to, weight: e.weight })),
    );
  }, [graph]);

  useEffect(() => {
    let frame = 0;
    const loop = () => {
      const sim = simulation.current;
      if (sim.energy > 0.05 || dragging.current) {
        sim.tick();
        redraw((n) => n + 1);
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []);

  const byName = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const node of graph?.nodes ?? []) map.set(node.name, node);
    return map;
  }, [graph]);

  const spent = snapshot?.usage.at(-1);
  // below the feed window every reader holds every post, so the graph is complete by
  // construction and its shape means nothing yet
  const written = (graph?.nodes ?? []).reduce((n, node) => n + node.posts, 0);
  const saturated = written > feedWidth;

  const thinned = graph?.thinned ?? 0;
  const spoke = (graph?.nodes ?? []).filter((n) => n.posts > 0).length;
  const box = simulation.current.extent();
  const detail = selected ? byName.get(selected) : undefined;

  const heard = detail
    ? (graph?.edges ?? []).filter((e) => e.from === detail.name)
      .sort((a, b) => b.weight - a.weight).slice(0, 5)
    : [];
  const reach = detail
    ? (graph?.edges ?? []).filter((e) => e.to === detail.name).length
    : 0;

  const pointer = (event: PointerEvent) => {
    const element = svg.current;
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    const scale = box.width / rect.width;
    return {
      x: box.x + (event.clientX - rect.left) * scale,
      y: box.y + (event.clientY - rect.top) * (box.height / rect.height),
    };
  };

  const onMove = (event: PointerEvent) => {
    const name = dragging.current;
    if (!name) return;
    const at = pointer(event);
    const point = simulation.current.points.get(name);
    if (!at || !point) return;
    point.x = at.x;
    point.y = at.y;
    point.vx = 0;
    point.vy = 0;
    redraw((n) => n + 1);
  };

  const release = () => {
    const name = dragging.current;
    if (name) {
      const point = simulation.current.points.get(name);
      if (point) point.fixed = false;
    }
    dragging.current = null;
  };

  return (
    <div class="swarm">
      <div class="swarm-canvas">
        <svg
          ref={svg}
          viewBox={`${box.x} ${box.y} ${box.width} ${box.height}`}
          role="img"
          aria-label={`Influence graph of ${graph?.nodes.length ?? 0} agents`}
          onPointerMove={onMove}
          onPointerUp={release}
          onPointerLeave={release}
        >
          <defs>
            <pattern
              id="grid"
              width="24"
              height="24"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r="1" />
            </pattern>
          </defs>
          <rect
            x={box.x}
            y={box.y}
            width={box.width}
            height={box.height}
            fill="url(#grid)"
            class="swarm-grid"
          />
          <g class="swarm-edges">
            {(graph?.edges ?? []).map((edge) => {
              const a = simulation.current.points.get(edge.from);
              const b = simulation.current.points.get(edge.to);
              if (!a || !b) return null;
              const touched = selected === edge.from || selected === edge.to;
              if (selected && !touched) return null;
              return (
                <line
                  key={`${edge.from}->${edge.to}`}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  class={touched ? "edge edge-active" : "edge"}
                  stroke-width={0.6 + edge.weight * 3}
                />
              );
            })}
          </g>
          <g class="swarm-nodes">
            {(graph?.nodes ?? []).map((node) => {
              const point = simulation.current.points.get(node.name);
              if (!point) return null;
              const radius = 4 + 2.4 * Math.sqrt(node.posts);
              return (
                <g
                  key={node.name}
                  transform={`translate(${point.x} ${point.y})`}
                  class={`node node-${node.kind}${
                    selected === node.name ? " node-selected" : ""
                  }${node.posts === 0 ? " node-silent" : ""}`}
                  tabIndex={0}
                  role="button"
                  aria-label={`${node.name}, ${node.posts} posts`}
                  onClick={() =>
                    setSelected(selected === node.name ? null : node.name)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelected(selected === node.name ? null : node.name);
                    }
                  }}
                  onPointerDown={(e) => {
                    dragging.current = node.name;
                    point.fixed = true;
                    (e.currentTarget as Element).releasePointerCapture?.(
                      e.pointerId,
                    );
                  }}
                >
                  <circle r={radius} />
                  {(node.posts > 2 || selected === node.name) && (
                    <text y={radius + 11}>{node.name}</text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        <div class="swarm-title">
          <h1>Influence graph</h1>
          <p>{graph?.topic ?? run.topic}</p>
          {graph && graph.nodes.length > 0 && (
            <p class="swarm-count">
              {spoke} of {graph.nodes.length} have spoken, {written}{" "}
              {written === 1 ? "post" : "posts"}{" "}
              in all. The activity throttle admits a few voices a round whatever
              the cast holds.
            </p>
          )}
          {graph && !graph.ranked && (
            <p class="swarm-caveat">
              This run read one shared wall. The edges are affinity the run did
              not act on.
            </p>
          )}
          {graph && !saturated && (
            <p class="swarm-caveat">
              Fewer than {feedWidth}{" "}
              posts so far, so every feed holds everything and the graph is
              complete by construction. Shape appears once the room outgrows the
              window.
            </p>
          )}
        </div>

        <div class="swarm-legend">
          <span class="legend-title">Agents</span>
          <span class="legend-item legend-persona">Written into the cast</span>
          <span class="legend-item legend-seat">Seated mid-run</span>
          <span class="legend-item legend-silent">Never spoke</span>
          <span class="legend-note">
            An edge runs from a reader to an author whose post ranked into its
            feed. Size is posts made, thickness is the share of the window held.
            A voice matches its own vocabulary best, so a loud one crowds its
            own feed and reads fewer others.
            {thinned > 0 && ` The ${thinned} weakest edges are not drawn.`}
          </span>
        </div>

        {detail && (
          <aside class="swarm-detail">
            <header>
              <h2>{detail.name}</h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setSelected(null)}
              >
                ×
              </button>
            </header>
            <dl>
              <div>
                <dt>Role</dt>
                <dd>
                  {detail.kind === "seat" ? "Seated mid-run" : "In the cast"}
                </dd>
              </div>
              <div>
                <dt>Posts</dt>
                <dd>{detail.posts}</dd>
              </div>
              <div>
                <dt>Heard by</dt>
                <dd>{reach} {reach === 1 ? "agent" : "agents"}</dd>
              </div>
              <div>
                <dt>Spoke</dt>
                <dd>
                  {detail.posts
                    ? `rounds ${detail.firstStep}–${detail.lastStep}`
                    : "not yet"}
                </dd>
              </div>
            </dl>
            {detail.prompt && <p class="swarm-character">{detail.prompt}</p>}
            {heard.length > 0 && (
              <>
                <h3>Reads most</h3>
                <ul class="swarm-reads">
                  {heard.map((edge) => (
                    <li key={edge.to}>
                      <button
                        type="button"
                        onClick={() => setSelected(edge.to)}
                      >
                        {edge.to}
                      </button>
                      <span>{edge.posts} of {feedWidth}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </aside>
        )}
      </div>

      <aside class="swarm-side">
        <section class="panel meter">
          <header>
            <h2>Spent</h2>
            <span class={`status-badge status-${state}`}>{state}</span>
          </header>
          {spent
            ? (
              <>
                <p class="meter-amount">{money(spent.usd)}</p>
                <dl class="meter-grid">
                  <div>
                    <dt>Requests</dt>
                    <dd>{spent.requests}</dd>
                  </div>
                  <div>
                    <dt>In</dt>
                    <dd>{spent.input_tokens.toLocaleString("en")}</dd>
                  </div>
                  <div>
                    <dt>Out</dt>
                    <dd>{spent.output_tokens.toLocaleString("en")}</dd>
                  </div>
                  <div>
                    <dt>Rounds</dt>
                    <dd>{snapshot?.usage.length ?? 0} of {run.rounds}</dd>
                  </div>
                </dl>
              </>
            )
            : <p class="meter-waiting">No superstep has committed yet.</p>}
          <p class="meter-cap">
            Cap: {run.usd
              ? money(run.usd)
              : run.tokens
              ? `${run.tokens.toLocaleString("en")} tokens`
              : `${run.requests} requests`}
          </p>
          {snapshot?.report != null && (
            <p class="meter-reason">
              Ended on <strong>{String(snapshot.report.reason ?? "?")}</strong>.
            </p>
          )}
          {live(state) && (
            <button
              type="button"
              class="secondary-button"
              onClick={async () => {
                const response = await fetch(`/api/runs/${run.id}`, {
                  method: "DELETE",
                });
                const body = await response.json();
                setFailure(body.detail ?? null);
              }}
            >
              Stop the run
            </button>
          )}
        </section>

        <section class="panel scrubber">
          <header>
            <h2>Round</h2>
            <label class="follow">
              <input
                type="checkbox"
                checked={following}
                onChange={(e) => {
                  const on = (e.target as HTMLInputElement).checked;
                  setFollowing(on);
                  if (on) setScrub(null);
                }}
              />
              <span>Follow</span>
            </label>
          </header>
          <input
            type="range"
            min={0}
            max={Math.max(0, graph?.steps ?? 0)}
            value={snapshot?.step ?? 0}
            disabled={following}
            onInput={(e) =>
              setScrub(Number((e.target as HTMLInputElement).value))}
          />
          <p class="hint">
            Round {snapshot?.step ?? 0} of{" "}
            {graph?.steps ?? 0}. The graph is rebuilt from the posts committed
            by that round.
          </p>
        </section>

        <section class="panel feed">
          <header>
            <h2>Feed</h2>
          </header>
          <ol>
            {[...(snapshot?.posts ?? [])].reverse().map((post, i) => (
              <li key={`${post.producer}-${post.step}-${i}`}>
                <button
                  type="button"
                  onClick={() =>
                    setSelected(post.producer)}
                >
                  {post.producer}
                </button>
                <span class="feed-step">round {post.step}</span>
                <p>{post.text}</p>
              </li>
            ))}
            {!snapshot?.posts.length && (
              <li class="feed-empty">Nothing posted yet.</li>
            )}
          </ol>
        </section>

        {(failure || snapshot?.error) && (
          <p class="form-error" role="status">{failure ?? snapshot?.error}</p>
        )}
      </aside>
    </div>
  );
}
