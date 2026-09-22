import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Simulation } from "@/lib/force.ts";
import { feedWidth } from "@/lib/influence.ts";
import {
  type Graph,
  type GraphNode,
  live as isLive,
  type LiveBoard,
  type Post,
  type RunState,
  type UsageTick,
} from "@/lib/types.ts";

/** What `/graph` returns for either kind of run. */
export interface Snapshot {
  graph: Graph;
  step: number;
  state: RunState;
  report: Record<string, unknown> | null;
  error: string | null;
  usage: UsageTick[];
  posts: Post[];
  live?: LiveBoard;
}

export function money(value: number) {
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(6)}` : `$${value.toFixed(4)}`;
}

function ago(since: number) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - since));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export interface SwarmViewProps {
  snapshot: Snapshot | null;
  failure: string | null;
  /** Shown as the room's subject until the graph's own `topic` fact loads. */
  fallbackTopic: string;
  rounds: number;
  /** The state the caller already knows, shown until the first poll lands. */
  initialState: RunState;
  /** Precomputed, since what a run is capped by differs by registry. */
  cap: string;
  /** The round being shown, or null to follow the newest. */
  scrub: number | null;
  onScrub: (step: number | null) => void;
  onStop?: () => Promise<string | null>;
  onOpenWorkspace?: (voice: string) => void;
  /** Extra panels appended to the side column. */
  children?: ComponentChildren;
}

/** The influence graph, the spend meter, the scrubber and the feed. Pure presentation: the
 * island that owns the poller decides what snapshot this shows. */
export function SwarmView(
  {
    snapshot,
    failure,
    fallbackTopic,
    rounds,
    initialState,
    cap,
    scrub,
    onScrub,
    onStop,
    onOpenWorkspace,
    children,
  }: SwarmViewProps,
) {
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<number | null>(null);
  const [stopping, setStopping] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [, redraw] = useState(0);

  const simulation = useRef(new Simulation());
  const svg = useRef<SVGSVGElement>(null);
  const dragging = useRef<string | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const state = snapshot?.state ?? initialState;
  const graph = snapshot?.graph;
  const following = scrub === null;
  // graph.steps is the highest committed superstep, -1 before the first one lands
  const committed = Math.max(0, (graph?.steps ?? -1) + 1);
  const roundsDone = Math.min(rounds, committed);
  const shown = draft ?? snapshot?.step ?? -1;

  useEffect(() => {
    if (!graph) return;
    simulation.current.sync(
      graph.nodes.map((n) => n.name),
      graph.edges.map((e) => ({ from: e.from, to: e.to, weight: e.weight })),
    );
  }, [graph]);

  useEffect(() => {
    let frame = 0;
    let idle = 0;
    const loop = () => {
      const sim = simulation.current;
      if (sim.energy > 0.05 || dragging.current) {
        idle = 0;
        sim.tick();
        redraw((n) => n + 1);
      } else {
        idle++;
      }
      // once the layout has settled, wake up rarely instead of every frame
      frame = idle > 30
        ? setTimeout(() => {
          frame = requestAnimationFrame(loop);
        }, 250) as unknown as number
        : requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(frame);
    };
  }, []);

  const byName = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const node of graph?.nodes ?? []) map.set(node.name, node);
    return map;
  }, [graph]);

  const lastPost = useMemo(() => {
    const map = new Map<string, Post>();
    for (const post of snapshot?.posts ?? []) map.set(post.producer, post);
    return map;
  }, [snapshot?.posts]);

  const spent = snapshot?.usage.at(-1);
  const written = (graph?.nodes ?? []).reduce((n, node) => n + node.posts, 0);
  const saturated = written > feedWidth;
  const thinned = graph?.thinned ?? 0;
  const spoke = (graph?.nodes ?? []).filter((n) => n.posts > 0).length;
  const box = simulation.current.extent();
  const detail = selected ? byName.get(selected) : undefined;
  const detailLive = detail ? snapshot?.live?.[detail.name] : undefined;
  const detailPost = detail ? lastPost.get(detail.name) : undefined;
  const working = Object.entries(snapshot?.live ?? {}).filter(([, v]) =>
    v.state === "working"
  );

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

  const scrubTo = (value: number) => {
    setDraft(value);
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      onScrub(value);
      setDraft(null);
    }, 150);
  };

  const stop = async () => {
    if (!onStop || stopping) return;
    setStopping(true);
    try {
      setNotice(await onStop());
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Could not stop the run",
      );
    } finally {
      setStopping(false);
    }
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
          <g class="swarm-nodes" role="listbox" aria-label="Voices">
            {(graph?.nodes ?? []).map((node) => {
              const point = simulation.current.points.get(node.name);
              if (!point) return null;
              const radius = 4 + 2.4 * Math.sqrt(node.posts);
              const busy = snapshot?.live?.[node.name]?.state === "working";
              return (
                <g
                  key={node.name}
                  transform={`translate(${point.x} ${point.y})`}
                  class={`node node-${node.kind}${
                    selected === node.name ? " node-selected" : ""
                  }${node.posts === 0 ? " node-silent" : ""}${
                    busy ? " node-busy" : ""
                  }`}
                  tabIndex={selected === node.name ||
                      (!selected && node.posts > 0)
                    ? 0
                    : -1}
                  role="option"
                  aria-selected={selected === node.name}
                  aria-label={`${node.name}, ${node.posts} posts${
                    busy ? ", working" : ""
                  }`}
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
                  {busy && <circle r={radius + 4} class="node-halo" />}
                  <circle r={radius} />
                  {(node.posts > 2 || selected === node.name || busy) && (
                    <text y={radius + 11}>{node.name}</text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        <div class="swarm-title">
          <h1>Influence graph</h1>
          <p className="truncate">{graph?.topic ?? fallbackTopic}</p>
          {!snapshot && !failure && (
            <p class="swarm-count skeleton-text">Loading the room</p>
          )}
          {graph && graph.nodes.length > 0 && (
            <p class="swarm-count">
              {spoke} of {graph.nodes.length} have spoken, {written}{" "}
              {written === 1 ? "post" : "posts"}{" "}
              in all. The activity throttle admits a few voices a round whatever
              the cast holds.
            </p>
          )}
          {working.length > 0 && (
            <p class="swarm-live">
              Working now:{" "}
              {working.map(([name, v]) => `${name} (${ago(v.since)})`).join(
                ", ",
              )}
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
          <span class="legend-item legend-busy">Inside a session now</span>
          <span class="legend-note">
            An edge runs from a reader to an author whose post ranked into its
            feed. Size is posts made, thickness is the share of the window held.
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
                    ? `rounds ${detail.firstStep + 1}–${detail.lastStep + 1}`
                    : "not yet"}
                </dd>
              </div>
            </dl>
            {detailLive && (
              <p class="swarm-activity">
                {detailLive.state === "working"
                  ? `Working in its workspace for ${
                    ago(detailLive.since)
                  } (round ${detailLive.round + 1}).`
                  : `Idle since round ${detailLive.round + 1} ended.`}
              </p>
            )}
            {detailPost?.meta && (
              <dl class="swarm-meta">
                <div>
                  <dt>Last round</dt>
                  <dd>
                    {detailPost.meta.files.length}{" "}
                    {detailPost.meta.files.length === 1 ? "file" : "files"}
                    {" · "}
                    {detailPost.meta.toolCalls} tool calls
                  </dd>
                </div>
                <div>
                  <dt>Cost</dt>
                  <dd>
                    {money(detailPost.meta.cost)}
                    {" · "}
                    {detailPost.meta.tokens.toLocaleString("en")} tok
                  </dd>
                </div>
                <div>
                  <dt>Took</dt>
                  <dd>
                    {Math.round(detailPost.meta.seconds)}s
                    {detailPost.meta.timedOut ? ", timed out" : ""}
                    {detailPost.meta.error ? `, ${detailPost.meta.error}` : ""}
                  </dd>
                </div>
              </dl>
            )}
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
            {onOpenWorkspace && detail.kind === "persona" && (
              <button
                type="button"
                class="secondary-button swarm-open"
                onClick={() => onOpenWorkspace(detail.name)}
              >
                Open workspace
              </button>
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
                    <dd>{roundsDone} of {rounds}</dd>
                  </div>
                </dl>
                {spent.workers_usd !== undefined && spent.workers_usd > 0 && (
                  <p class="meter-cap">
                    Coding agents billed {money(spent.workers_usd)}{" "}
                    by OpenCode's own count.
                  </p>
                )}
              </>
            )
            : (
              <dl class="meter-grid">
                <div>
                  <dt>Rounds</dt>
                  <dd>{roundsDone} of {rounds}</dd>
                </div>
              </dl>
            )}
          <p class="meter-cap">Cap: {cap}</p>
          {snapshot?.report != null && snapshot.report.reason !== undefined && (
            <p class="meter-reason">
              Ended on <strong>{String(snapshot.report.reason)}</strong>.
            </p>
          )}
          {onStop && isLive(state) && (
            <button
              type="button"
              class="secondary-button"
              disabled={stopping}
              onClick={stop}
            >
              {stopping ? "Stopping…" : "Stop the run"}
            </button>
          )}
          {notice && <p class="meter-reason" role="status">{notice}</p>}
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
                  if (on) {
                    setDraft(null);
                    onScrub(null);
                  } else {
                    onScrub(Math.max(0, snapshot?.step ?? 0));
                  }
                }}
              />
              <span>Follow</span>
            </label>
          </header>
          <input
            type="range"
            min={0}
            max={Math.max(0, committed - 1)}
            value={Math.max(0, shown)}
            disabled={following || committed === 0}
            onInput={(e) =>
              scrubTo(Number((e.target as HTMLInputElement).value))}
          />
          <p class="hint">
            {committed === 0
              ? "No round has been committed yet."
              : `Round ${
                Math.max(0, shown) + 1
              } of ${committed}. The graph is rebuilt from the posts committed by that round.`}
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
                <span class="feed-step">round {post.step + 1}</span>
                {post.meta && (
                  <span class="feed-step">
                    {post.meta.files.length} files · {money(post.meta.cost)}
                    {post.meta.timedOut ? " · timed out" : ""}
                  </span>
                )}
                <p>{post.text}</p>
              </li>
            ))}
            {!snapshot && (
              <li class="feed-empty skeleton-text">Loading the feed</li>
            )}
            {snapshot && !snapshot.posts.length && (
              <li class="feed-empty">Nothing posted yet.</li>
            )}
          </ol>
        </section>

        {(failure || snapshot?.error) && (
          <p class="form-error" role="status">{failure ?? snapshot?.error}</p>
        )}

        {children}
      </aside>
    </div>
  );
}
