import { assert, assertAlmostEquals, assertEquals } from "jsr:@std/assert@^1";
import { Simulation } from "@/lib/force.ts";

Deno.test("the same room lays out the same way twice", () => {
  const names = ["a", "b", "c", "d"];
  const links = [{ from: "a", to: "b", weight: 0.5 }];
  const one = new Simulation();
  const two = new Simulation();
  one.sync(names, links);
  two.sync(names, links);
  for (let i = 0; i < 60; i++) {
    one.tick();
    two.tick();
  }
  for (const name of names) {
    assertAlmostEquals(one.points.get(name)!.x, two.points.get(name)!.x, 1e-9);
    assertAlmostEquals(one.points.get(name)!.y, two.points.get(name)!.y, 1e-9);
  }
});

Deno.test("a round that seats a voice keeps everyone else where they were", () => {
  const sim = new Simulation();
  sim.sync(["a", "b"], []);
  for (let i = 0; i < 40; i++) sim.tick();
  const before = { ...sim.points.get("a")! };

  sim.sync(["a", "b", "seat_0"], []);
  assertEquals(sim.points.get("a")!.x, before.x);
  assertEquals(sim.points.get("a")!.y, before.y);
  assert(sim.points.has("seat_0"));
});

Deno.test("a voice that leaves the graph leaves the layout", () => {
  const sim = new Simulation();
  sim.sync(["a", "b"], [{ from: "a", to: "b", weight: 1 }]);
  sim.sync(["a"], [{ from: "a", to: "b", weight: 1 }]);
  assertEquals([...sim.points.keys()], ["a"]);
  assertEquals(sim.links.length, 0, "an edge to a missing voice is dropped");
});

Deno.test("the layout settles, so a quiet graph stops burning frames", () => {
  const sim = new Simulation();
  sim.sync(["a", "b", "c", "d", "e"], [
    { from: "a", to: "b", weight: 0.4 },
    { from: "b", to: "c", weight: 0.4 },
  ]);
  for (let i = 0; i < 600; i++) sim.tick();
  assert(sim.energy < 0.05, `energy stayed at ${sim.energy}`);
});

Deno.test("two voices at the same spot separate", () => {
  const sim = new Simulation();
  sim.sync(["a", "b"], []);
  for (const point of sim.points.values()) {
    point.x = 0;
    point.y = 0;
  }
  for (let i = 0; i < 30; i++) sim.tick();
  const [a, b] = [...sim.points.values()];
  assert(Math.hypot(a.x - b.x, a.y - b.y) > 1, "overlapping nodes push apart");
});

Deno.test("an empty room still has a viewBox", () => {
  const sim = new Simulation();
  const box = sim.extent();
  assert(box.width > 0 && box.height > 0);
});
