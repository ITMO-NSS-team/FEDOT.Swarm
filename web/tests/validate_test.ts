import { assertEquals, assertThrows } from "jsr:@std/assert@^1";
import { InvalidRequest, parseRequest } from "@/lib/validate.ts";
import { models } from "@/lib/types.ts";

const valid = {
  topic: "Should model weights be open?",
  model: models[0],
  personas: 10,
  rounds: 5,
  compose: true,
  ranked: true,
  seats: 0,
  concurrency: 2,
  usd: 0.002,
  tokens: 0,
  requests: 0,
};

Deno.test("a well-formed request passes through", () => {
  const parsed = parseRequest(valid);
  assertEquals(parsed.personas, 10);
  assertEquals(parsed.usd, 0.002);
});

Deno.test("an uncapped run is refused", () => {
  assertThrows(
    () => parseRequest({ ...valid, usd: 0, tokens: 0, requests: 0 }),
    InvalidRequest,
  );
});

Deno.test("the arguments become a command line, so every field is bounded", () => {
  for (
    const bad of [
      { personas: 1 },
      { personas: 500 },
      { rounds: 0 },
      { rounds: 1000 },
      { seats: -1 },
      { concurrency: 0 },
      { usd: 99 },
    ]
  ) {
    assertThrows(() => parseRequest({ ...valid, ...bad }), InvalidRequest);
  }
});

Deno.test("a topic cannot smuggle a control character or an unknown model", () => {
  assertThrows(() => parseRequest({ ...valid, topic: "a" }), InvalidRequest);
  assertThrows(
    () => parseRequest({ ...valid, topic: "open\u0000weights" }),
    InvalidRequest,
  );
  assertThrows(
    () => parseRequest({ ...valid, model: "openrouter:something/else" }),
    InvalidRequest,
  );
});

Deno.test("numbers arriving as strings from a form are still bounded", () => {
  assertEquals(parseRequest({ ...valid, personas: "12" }).personas, 12);
  assertThrows(
    () => parseRequest({ ...valid, personas: "abc" }),
    InvalidRequest,
  );
});
