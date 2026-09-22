import { assertEquals } from "jsr:@std/assert@^1";
import { join } from "node:path";
import { isText, listFiles, safeJoin } from "@/lib/files.ts";

Deno.test("safeJoin keeps a relative path under its root", () => {
  const root = "/tmp/ws/hawk";
  assertEquals(safeJoin(root, "src/a.py"), "/tmp/ws/hawk/src/a.py");
  assertEquals(safeJoin(root, "a.py"), "/tmp/ws/hawk/a.py");
});

Deno.test("safeJoin refuses anything that leaves the root", () => {
  const root = "/tmp/ws/hawk";
  for (
    const bad of [
      "",
      "/etc/passwd",
      "../dove/a.py",
      "src/../../a.py",
      "./a.py",
      "a\0.py",
      "\\..\\a.py",
    ]
  ) {
    assertEquals(safeJoin(root, bad), null, bad);
  }
});

Deno.test("listFiles walks sorted and skips the housekeeping directories", () => {
  const dir = Deno.makeTempDirSync();
  Deno.mkdirSync(join(dir, "src"));
  Deno.mkdirSync(join(dir, ".git"));
  Deno.mkdirSync(join(dir, "__pycache__"));
  Deno.writeTextFileSync(join(dir, "src", "b.py"), "print(2)\n");
  Deno.writeTextFileSync(join(dir, "a.py"), "print(1)\n");
  Deno.writeTextFileSync(join(dir, ".git", "HEAD"), "ref\n");
  Deno.writeTextFileSync(join(dir, "__pycache__", "a.pyc"), "x");
  assertEquals(listFiles(dir).map((f) => f.path), ["a.py", "src/b.py"]);
  assertEquals(listFiles(dir, 1).length, 1);
});

Deno.test("isText spots a NUL byte", () => {
  assertEquals(isText(new TextEncoder().encode("hello\n")), true);
  assertEquals(isText(new Uint8Array([0x25, 0x50, 0x44, 0x46, 0, 1])), false);
});
