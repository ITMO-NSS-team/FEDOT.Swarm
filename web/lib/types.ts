/** What the web layer exchanges with the browser. The engine's own shapes live in Python;
 * these are the projections a screen needs, nothing more. */

/** One row of the fedotmas fact store, as written by `SqliteStore`. */
export interface Fact {
  tag: string;
  value: unknown;
  producer: string;
  step: number;
}

/** A voice in the room. The clock, the feed digests and the fold write no posts, so they
 * never enter the graph: what is drawn is the conversation, not the wiring. */
export type NodeKind = "persona" | "seat";

export interface GraphNode {
  name: string;
  kind: NodeKind;
  /** The character the spec gave it; empty for a seat nobody has filled yet. */
  prompt: string;
  posts: number;
  firstStep: number;
  lastStep: number;
}

/** `from` read `to`: one of `to`'s posts ranked into `from`'s feed. Directed, because the
 * ranking is per reader and is not symmetric. */
export interface GraphEdge {
  from: string;
  to: string;
  /** Share of the reader's feed window this author holds, 0..1. */
  weight: number;
  posts: number;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Edges the strongest-first cap left out. A big room has up to feedWidth edges per
   * reader, and sending every one of them is what makes the payload, not the drawing. */
  thinned: number;
  /** Highest step present in the store, so a client can scrub without refetching. */
  steps: number;
  /** True when the run gave every persona its own ranked feed. False means the edges are
   * affinity the run did not act on: everyone read one shared wall. */
  ranked: boolean;
  topic: string;
}

/** What an OpenCode voice reported for one round, beside the text it posted. */
export interface PostMeta {
  files: string[];
  cost: number;
  tokens: number;
  toolCalls: number;
  seconds: number;
  timedOut: boolean;
  error: string | null;
}

export interface Post {
  producer: string;
  step: number;
  text: string;
  meta?: PostMeta;
}

/** One line of the usage sidecar `run.py` appends to after every superstep. */
export interface UsageTick {
  index: number;
  fired: number;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  workers_usd?: number;
  at: number;
}

/** `lost` is a run this server no longer owns and whose process is gone: it was running when
 * the server restarted, and nothing will ever finish it. */
export type RunState =
  | "starting"
  | "running"
  | "done"
  | "failed"
  | "stopped"
  | "lost";

export const terminal = (state: RunState) =>
  state === "done" || state === "failed" || state === "stopped" ||
  state === "lost";

export const live = (state: RunState) =>
  state === "running" || state === "starting";

export interface RunRequest {
  topic: string;
  model: string;
  personas: number;
  rounds: number;
  compose: boolean;
  ranked: boolean;
  seats: number;
  concurrency: number;
  /** Zero means no cap on that axis; at least one may be set. */
  usd: number;
  tokens: number;
  requests: number;
}

export interface Run extends RunRequest {
  id: string;
  state: RunState;
  startedAt: number;
  endedAt: number | null;
  /** stderr tail, kept only to explain a failed state. */
  error: string | null;
  /** The report `run.py` writes when it finishes. */
  report: Record<string, unknown> | null;
  /** The child's pid, so a restarted server can tell a live run from a lost one. */
  pid?: number | null;
}

/** Who is working right now, as `workers.LiveBoard` writes it. */
export type LiveBoard = Record<
  string,
  { state: "working" | "idle"; round: number; since: number }
>;
