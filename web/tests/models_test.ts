import { assertEquals } from "jsr:@std/assert@^1";
import { defaultModels, parseModels } from "@/lib/models.ts";

Deno.test("an unset or empty FEDOTMAS_MODELS yields the default pair", () => {
  assertEquals(parseModels(undefined), defaultModels);
  assertEquals(parseModels(""), defaultModels);
  assertEquals(parseModels(" , "), defaultModels);
});

Deno.test("a comma-separated list is trimmed and kept in order", () => {
  assertEquals(parseModels(" openrouter:a/b , openrouter:c/d,"), [
    "openrouter:a/b",
    "openrouter:c/d",
  ]);
});
