import { assertEquals, assertThrows } from "jsr:@std/assert@^1";
import { InvalidRequest } from "@/lib/validate.ts";
import {
  DEFAULT_MAX_TOKENS,
  isPdf,
  parsePaperScalars,
  sanitizeTexPath,
  uploadLabel,
  validateRubricBranch,
} from "@/lib/paper_upload.ts";

const scalars = {
  timeoutSeconds: 600,
  personas: 3,
  rounds: 4,
  ranked: true,
  seats: 0,
  compose: true,
  model: "haiku",
};

const branch = {
  id: "branch",
  requirements: "The model has been implemented",
  weight: 1,
  sub_tasks: [
    { id: "a", requirements: "Noise is sampled", weight: 2, sub_tasks: [] },
    { id: "b", requirements: "Loss is computed", weight: 1, sub_tasks: [] },
  ],
};

Deno.test("scalars pass through, from JSON booleans or form strings alike", () => {
  assertEquals(parsePaperScalars(scalars).personas, 3);
  const fromForm = parsePaperScalars({
    ...scalars,
    timeoutSeconds: "600",
    personas: "3",
    ranked: "true",
    compose: "1",
  });
  assertEquals(fromForm.ranked, true);
  assertEquals(fromForm.compose, true);
});

Deno.test("scalar bounds match the run the form offers", () => {
  for (
    const bad of [
      { timeoutSeconds: 30 },
      { timeoutSeconds: 9999 },
      { personas: 0 },
      { personas: 13 },
      { rounds: 0 },
      { seats: -1 },
      { model: "nope" },
      { backend: "nope" },
      { backend: "openrouter", usd: -1 },
      { backend: "openrouter", tokens: 999_999_999 },
    ]
  ) {
    assertThrows(
      () => parsePaperScalars({ ...scalars, ...bad }),
      InvalidRequest,
    );
  }
});

Deno.test("the backend picks which model list is valid, and defaults to claude-code", () => {
  const claudeCode = parsePaperScalars(scalars);
  assertEquals(claudeCode.backend, "claude-code");
  assertEquals(claudeCode.model, "haiku");

  const openrouter = parsePaperScalars({
    ...scalars,
    backend: "openrouter",
    model: "openrouter:qwen/qwen3.7-flash",
    usd: 0.01,
  });
  assertEquals(openrouter.backend, "openrouter");
  assertEquals(openrouter.model, "openrouter:qwen/qwen3.7-flash");

  // an openrouter model id is not a claude-code alias, and vice versa
  assertThrows(
    () =>
      parsePaperScalars({
        ...scalars,
        backend: "claude-code",
        model: "openrouter:qwen/qwen3.7-flash",
      }),
    InvalidRequest,
  );
  assertThrows(
    () => parsePaperScalars({ ...scalars, backend: "openrouter", model: "haiku" }),
    InvalidRequest,
  );
});

Deno.test("an openrouter run is refused without a spend cap; claude-code needs none", () => {
  assertThrows(
    () =>
      parsePaperScalars({
        ...scalars,
        backend: "openrouter",
        model: "openrouter:qwen/qwen3.7-flash",
      }),
    InvalidRequest,
  );
  // any one of the three axes satisfies it
  for (const axis of ["usd", "tokens", "requests"] as const) {
    const parsed = parsePaperScalars({
      ...scalars,
      backend: "openrouter",
      model: "openrouter:qwen/qwen3.7-flash",
      [axis]: 1,
    });
    assertEquals(parsed[axis], 1);
  }
  // claude-code has no metered cost, so it is never asked for one
  assertEquals(parsePaperScalars(scalars).usd, 0);
});

Deno.test("a spend cap is zeroed under claude-code, kept under openrouter", () => {
  const claudeCode = parsePaperScalars({ ...scalars, usd: 2, tokens: 1000 });
  assertEquals(claudeCode.usd, 0);
  assertEquals(claudeCode.tokens, 0);

  const openrouter = parsePaperScalars({
    ...scalars,
    backend: "openrouter",
    model: "openrouter:qwen/qwen3.7-flash",
    usd: 2,
    tokens: 1000,
  });
  assertEquals(openrouter.usd, 2);
  assertEquals(openrouter.tokens, 1000);
});

Deno.test("max tokens defaults, and is bounded, regardless of backend", () => {
  assertEquals(parsePaperScalars(scalars).maxTokens, DEFAULT_MAX_TOKENS);
  assertEquals(parsePaperScalars({ ...scalars, maxTokens: 12000 }).maxTokens, 12000);
  assertThrows(
    () => parsePaperScalars({ ...scalars, maxTokens: 10 }),
    InvalidRequest,
  );
  assertThrows(
    () => parsePaperScalars({ ...scalars, maxTokens: 999_999 }),
    InvalidRequest,
  );
});

Deno.test("a well-formed branch validates to its leaves", () => {
  const leaves = validateRubricBranch(branch);
  assertEquals(leaves.length, 2);
  assertEquals(leaves[0].id, "a");
});

Deno.test("a branch without leaves or with bad leaves is refused", () => {
  for (
    const bad of [
      [1],
      {},
      { requirements: "x", sub_tasks: [] },
      { ...branch, requirements: "  " },
      {
        ...branch,
        sub_tasks: [{ id: "", requirements: "r", weight: 1, sub_tasks: [] }],
      },
      {
        ...branch,
        sub_tasks: [{ id: "a", requirements: "r", weight: -1, sub_tasks: [] }],
      },
    ]
  ) {
    assertThrows(() => validateRubricBranch(bad), InvalidRequest);
  }
});

Deno.test("a .tex path normalizes to forward slashes, rooted, no traversal", () => {
  assertEquals(sanitizeTexPath("main.tex"), "main.tex");
  assertEquals(sanitizeTexPath("paper/sections/intro.tex"), "paper/sections/intro.tex");
  assertEquals(sanitizeTexPath("paper\\sections\\intro.tex"), "paper/sections/intro.tex");
});

Deno.test("a path is refused without the .tex extension or with traversal", () => {
  assertEquals(sanitizeTexPath("main.pdf"), null);
  assertEquals(sanitizeTexPath("readme"), null);
  assertEquals(sanitizeTexPath("../../etc/passwd.tex"), null);
  assertEquals(sanitizeTexPath("a/../b.tex"), null);
  assertEquals(sanitizeTexPath(".tex"), null);
});

Deno.test("a PDF is told apart from other files by its magic bytes, not its name", () => {
  const pdf = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x35]); // "%PDF-1.5"
  assertEquals(isPdf(pdf), true);
  assertEquals(isPdf(new Uint8Array([0x25, 0x50, 0x44])), false); // too short
  assertEquals(isPdf(new TextEncoder().encode("not a pdf at all")), false);
  assertEquals(isPdf(new Uint8Array()), false);
});

Deno.test("the label prefers the title, then the upload's folder or file name", () => {
  assertEquals(uploadLabel("My paper", "my-paper"), "My paper");
  assertEquals(uploadLabel("  ", "my-paper_v2"), "my paper v2");
  assertEquals(uploadLabel(null, null), "upload");
});
