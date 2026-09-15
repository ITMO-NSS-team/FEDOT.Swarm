import type { Graph, GraphEdge, GraphNode, NodeKind, Post } from "@/lib/types.ts";

/** Mirrors `SwarmPreset.feed_width` and `FEED_WIDTH` in `benchmarks/swarm/run.py`. A reader's
 * feed holds this many posts, so it is also the denominator of an edge's weight. */
export const feedWidth = 12;

/** How many edges a snapshot carries. A reader holds at most `feedWidth` of them, so a room
 * of 200 can produce 2400: past this the weakest are dropped and counted instead, which keeps
 * the payload and the SVG element count bounded by the cap rather than by the cast. */
export const edgeBudget = 2000;

/** The same tokens `fedotmas_meta.presets._swarm._words` counts: lowercase runs of four or
 * more latin letters. Ported rather than imported because the ranking has to be recomputed
 * here for steps the run has already passed. */
export function words(text: string): Set<string> {
  return new Set(text.toLowerCase().match(/[a-z]{4,}/g) ?? []);
}

function overlap(a: Set<string>, b: Set<string>): number {
  let n = 0;
  for (const word of b) if (a.has(word)) n++;
  return n;
}

const seat = /^seat_\d+$/;

function kindOf(name: string, cast: Record<string, string>): NodeKind {
  if (name in cast) return "persona";
  if (seat.test(name)) return "seat";
  return "persona";
}

/** Who read whom, as of `step`.
 *
 * An edge runs from a reader to an author whose post `by_interest` would have placed in that
 * reader's feed window: rank every post committed so far by how much of the reader's own
 * vocabulary it uses, recent first among equals, keep the top `feedWidth`. That is the
 * ranking the preset applies per round, recomputed here so the graph can be scrubbed.
 *
 * Self-edges are dropped. A persona does read its own posts, but a loop says nothing about
 * the room.
 */
export function buildGraph(
  posts: Post[],
  cast: Record<string, string>,
  step: number,
  options: {
    ranked: boolean;
    topic: string;
    steps: number;
    maxEdges?: number;
  },
): Graph {
  const upto = posts.filter((p) => p.step <= step);
  const nodes = new Map<string, GraphNode>();

  const ensure = (name: string) => {
    let node = nodes.get(name);
    if (!node) {
      node = {
        name,
        kind: kindOf(name, cast),
        prompt: cast[name] ?? "",
        posts: 0,
        firstStep: Infinity,
        lastStep: -1,
      };
      nodes.set(name, node);
    }
    return node;
  };

  // every voice the spec named, whether or not it has spoken yet: a silent persona is a fact
  // about the run, not an absence
  for (const name of Object.keys(cast)) ensure(name);
  for (const post of upto) {
    const node = ensure(post.producer);
    node.posts++;
    node.firstStep = Math.min(node.firstStep, post.step);
    node.lastStep = Math.max(node.lastStep, post.step);
  }
  for (const node of nodes.values()) {
    if (node.firstStep === Infinity) node.firstStep = -1;
  }

  const postWords = upto.map((p) => words(p.text));
  const edges: GraphEdge[] = [];

  for (const reader of nodes.values()) {
    if (!reader.prompt) continue; // an unseated seat has no vocabulary to rank with
    const mine = words(reader.prompt);
    const ranked = upto
      .map((post, i) => ({ post, i, score: overlap(mine, postWords[i]) }))
      .sort((a, b) => b.score - a.score || b.i - a.i)
      .slice(0, feedWidth);

    const byAuthor = new Map<string, number>();
    for (const { post } of ranked) {
      if (post.producer === reader.name) continue;
      byAuthor.set(post.producer, (byAuthor.get(post.producer) ?? 0) + 1);
    }
    for (const [author, count] of byAuthor) {
      edges.push({
        from: reader.name,
        to: author,
        posts: count,
        weight: count / feedWidth,
      });
    }
  }

  const cap = options.maxEdges ?? edgeBudget;
  const kept = edges.length <= cap
    ? edges
    : [...edges].sort((a, b) => b.weight - a.weight).slice(0, cap);

  return {
    nodes: [...nodes.values()].sort((a, b) => a.name.localeCompare(b.name)),
    edges: kept,
    thinned: edges.length - kept.length,
    steps: options.steps,
    ranked: options.ranked,
    topic: options.topic,
  };
}
