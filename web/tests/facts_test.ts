import { assertEquals } from "jsr:@std/assert@^1";
import { DatabaseSync } from "node:sqlite";
import { join } from "node:path";
import { cast, facts, lastStep, posts, topic, usage } from "@/lib/facts.ts";

/** The schema `fedotmas.engine.sqlite_store` creates, copied so a test needs no Python. */
function fixture(path: string) {
  const db = new DatabaseSync(path);
  db.exec(`CREATE TABLE facts (
    rowid_ INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL,
    value_json TEXT NOT NULL,
    producer TEXT NOT NULL,
    step INTEGER NOT NULL,
    meta_json TEXT NOT NULL
  );`);
  const insert = db.prepare(
    "INSERT INTO facts (tag, value_json, producer, step, meta_json) VALUES (?, ?, ?, ?, ?)",
  );
  insert.run(
    "topic",
    JSON.stringify("Should weights be open?"),
    "seed",
    -1,
    "{}",
  );
  insert.run("post", JSON.stringify("Weights are a risk."), "safety", 0, "{}");
  insert.run(
    "post",
    JSON.stringify("Weights are a market."),
    "economist",
    2,
    "{}",
  );
  db.close();
}

Deno.test("a store written by the engine reads back through the web layer", async (t) => {
  const dir = await Deno.makeTempDir();
  const path = join(dir, "run.db");
  fixture(path);

  await t.step("every fact, in commit order", () => {
    assertEquals(facts(path).map((f) => f.tag), ["topic", "post", "post"]);
  });
  await t.step("posts carry their producer and step", () => {
    assertEquals(posts(path), [
      { producer: "safety", step: 0, text: "Weights are a risk." },
      { producer: "economist", step: 2, text: "Weights are a market." },
    ]);
  });
  await t.step("the topic is the seeded fact", () => {
    assertEquals(topic(path), "Should weights be open?");
  });
  await t.step("the last step bounds the scrubber", () => {
    assertEquals(lastStep(path), 2);
  });

  await Deno.remove(dir, { recursive: true });
});

Deno.test("a run that has not committed yet reads as empty, not as an error", () => {
  const missing = "/nonexistent/never-written.db";
  assertEquals(facts(missing), []);
  assertEquals(posts(missing), []);
  assertEquals(lastStep(missing), -1);
  assertEquals(cast(`${missing}.spec.json`), {});
  assertEquals(usage(`${missing}.usage.jsonl`), []);
});

Deno.test("the cast comes out of the spec run.py persists before starting", async () => {
  const dir = await Deno.makeTempDir();
  const path = join(dir, "run.db.spec.json");
  await Deno.writeTextFile(
    path,
    JSON.stringify({
      preset: "swarm",
      fill: {
        personas: {
          safety: {
            prompt: "You are a safety researcher.",
            model: null,
            tools: [],
          },
        },
      },
    }),
  );
  assertEquals(cast(path), { safety: "You are a safety researcher." });
  await Deno.remove(dir, { recursive: true });
});

Deno.test("a half-written last line of the usage tape is skipped", async () => {
  const dir = await Deno.makeTempDir();
  const path = join(dir, "run.db.usage.jsonl");
  await Deno.writeTextFile(
    path,
    `{"index":0,"fired":3,"requests":2,"input_tokens":10,"output_tokens":4,"usd":0.1,"at":1}\n{"index":1,"fir`,
  );
  const ticks = usage(path);
  assertEquals(ticks.length, 1);
  assertEquals(ticks[0].requests, 2);
  await Deno.remove(dir, { recursive: true });
});
