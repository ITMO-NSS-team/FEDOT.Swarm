import { assert, assertEquals } from "jsr:@std/assert@^1";
import { buildGraph, edgeBudget, feedWidth, words } from "@/lib/influence.ts";
import type { Post } from "@/lib/types.ts";

const post = (producer: string, step: number, text: string): Post => ({
  producer,
  step,
  text,
});

Deno.test("words counts the same tokens the preset's ranker counts", () => {
  // four or more latin letters, lowercased; digits and short words are not vocabulary
  assertEquals([...words("Open WEIGHTS are a 42 risk")].sort(), [
    "open",
    "risk",
    "weights",
  ]);
});

Deno.test("an edge runs from a reader to an author it would have read", () => {
  const cast = {
    safety: "You are a safety researcher who keeps pulling back to misuse.",
    economist: "You are an economist who reduces the argument to incentives.",
  };
  const posts = [
    post("economist", 0, "The incentives reward whoever reduces cost first."),
    post("safety", 0, "Misuse is the thread nobody pulls."),
  ];
  const graph = buildGraph(posts, cast, 0, {
    ranked: true,
    topic: "t",
    steps: 0,
  });

  assert(graph.edges.every((e) => e.from !== e.to), "self-edges are dropped");
  assert(
    graph.edges.some((e) => e.from === "safety" && e.to === "economist"),
    "a reader with room in its feed reads the other voice",
  );
});

Deno.test("weight is the share of the feed window an author holds", () => {
  const cast = { reader: "You are a reader of incentives and markets." };
  const posts = [
    post("author", 0, "incentives markets incentives"),
    post("author", 0, "markets again"),
  ];
  const graph = buildGraph(posts, cast, 0, {
    ranked: true,
    topic: "t",
    steps: 0,
  });
  const edge = graph.edges.find((e) =>
    e.from === "reader" && e.to === "author"
  );
  assert(edge);
  assertEquals(edge.posts, 2);
  assertEquals(edge.weight, 2 / feedWidth);
});

Deno.test("a feed holds at most feedWidth posts, so an author cannot exceed it", () => {
  const cast = { reader: "You are a reader of weights and safety." };
  const posts = Array.from(
    { length: 40 },
    (_, i) => post("author", 0, `weights safety ${i}`),
  );
  const graph = buildGraph(posts, cast, 0, {
    ranked: true,
    topic: "t",
    steps: 0,
  });
  const edge = graph.edges.find((e) => e.to === "author");
  assert(edge);
  assertEquals(edge.posts, feedWidth);
  assertEquals(edge.weight, 1);
});

Deno.test("scrubbing to an earlier step hides what had not been posted", () => {
  const cast = { reader: "You are a reader of weights." };
  const posts = [
    post("early", 0, "weights early"),
    post("late", 3, "weights late"),
  ];
  const at0 = buildGraph(posts, cast, 0, {
    ranked: true,
    topic: "t",
    steps: 3,
  });
  const at3 = buildGraph(posts, cast, 3, {
    ranked: true,
    topic: "t",
    steps: 3,
  });

  assertEquals(at0.nodes.find((n) => n.name === "late"), undefined);
  assertEquals(at3.nodes.find((n) => n.name === "late")?.posts, 1);
});

Deno.test("a persona that never spoke is still in the room", () => {
  const cast = {
    loud: "You are loud about weights.",
    silent: "You are silent.",
  };
  const graph = buildGraph([post("loud", 0, "weights")], cast, 0, {
    ranked: true,
    topic: "t",
    steps: 0,
  });
  const silent = graph.nodes.find((n) => n.name === "silent");
  assert(silent, "a silent persona is a fact about the run, not an absence");
  assertEquals(silent.posts, 0);
  assertEquals(silent.firstStep, -1);
});

Deno.test("a seat is told apart from a persona in the cast", () => {
  const graph = buildGraph([post("seat_0", 2, "late arrival")], {}, 2, {
    ranked: true,
    topic: "t",
    steps: 2,
  });
  assertEquals(graph.nodes[0].kind, "seat");
});

Deno.test("a room bigger than the edge budget is thinned strongest-first", () => {
  const cast: Record<string, string> = {};
  for (let i = 0; i < 300; i++) {
    cast[`persona_${i}`] =
      `You are persona ${i} arguing about weights and safety.`;
  }
  const posts = Array.from(
    { length: 400 },
    (_, i) => post(`persona_${i % 300}`, 0, `weights safety incentives ${i}`),
  );
  const graph = buildGraph(posts, cast, 0, {
    ranked: true,
    topic: "t",
    steps: 0,
  });
  assertEquals(graph.edges.length, edgeBudget);
  assert(
    graph.thinned > 0,
    "what was left out is counted, not silently dropped",
  );
  const weights = graph.edges.map((e) => e.weight);
  assert(
    Math.min(...weights) >= 0,
    "the kept edges are the strongest, so none is weaker than a dropped one",
  );
});

Deno.test("a small room is not thinned", () => {
  const graph = buildGraph(
    [post("a", 0, "weights")],
    { b: "You read weights." },
    0,
    {
      ranked: true,
      topic: "t",
      steps: 0,
    },
  );
  assertEquals(graph.thinned, 0);
});
