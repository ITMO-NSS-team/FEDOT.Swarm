import { assertEquals, assertStringIncludes } from "jsr:@std/assert@^1";
import { pidAlive, redact } from "@/lib/registry.ts";

Deno.test("redact hides provider keys however they reach a log", () => {
  const traceback = [
    "Traceback (most recent call last):",
    "  File 'run.py', headers={'Authorization': 'Bearer sk-or-v1-abcdef0123456789abcdef'}",
    "OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789abcdef",
    'env: {"OPENCODE_SERVER_PASSWORD": "hunter2"}',
    "token: xyz",
  ].join("\n");
  const clean = redact(traceback);
  assertEquals(clean.includes("abcdef0123456789"), false);
  assertEquals(clean.includes("hunter2"), false);
  assertStringIncludes(clean, "OPENROUTER_API_KEY=[redacted]");
  assertStringIncludes(clean, "Traceback");
});

Deno.test("pidAlive is false for nothing and for a pid that is gone", () => {
  assertEquals(pidAlive(null), false);
  assertEquals(pidAlive(0), false);
  assertEquals(pidAlive(2_000_000_000), false);
  assertEquals(pidAlive(Deno.pid), true);
});
