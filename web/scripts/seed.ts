import { join } from "node:path";
import { paperPaths } from "@/lib/paths.ts";
import type { PaperRun } from "@/lib/paperbench.ts";
import { Registry } from "@/lib/registry.ts";

/** Seeds the registry with a recorded run, so the Runs page of a fresh deployment is never
 * empty: `deno run -A scripts/seed.ts tests/fixtures/demo`. The fixture holds `run.json`
 * (the registry row), `report.json`, `status.json` and `workdir/`. */
const fixture = Deno.args[0];
if (!fixture) throw new Error("usage: seed.ts <fixture dir>");
const run = JSON.parse(
  Deno.readTextFileSync(join(fixture, "run.json")),
) as PaperRun;
const paths = paperPaths(run.id);
const registry = new Registry<PaperRun>("paper_runs", "paperbench");

function copyTree(from: string, to: string) {
  Deno.mkdirSync(to, { recursive: true });
  for (const entry of Deno.readDirSync(from)) {
    const source = join(from, entry.name);
    const target = join(to, entry.name);
    if (entry.isDirectory) copyTree(source, target);
    else if (entry.isFile) Deno.copyFileSync(source, target);
  }
}

const report = JSON.parse(Deno.readTextFileSync(join(fixture, "report.json")));
report.workdir = paths.workdir;
if (report.kept) report.kept.dir = join(paths.workdir, "solution");
for (const file of report.files ?? []) {
  file.absPath = join(paths.workdir, "solution", file.path);
}
Deno.mkdirSync(join(paths.report, ".."), { recursive: true });
Deno.writeTextFileSync(paths.report, JSON.stringify(report, null, 2));
Deno.copyFileSync(join(fixture, "status.json"), paths.status);
copyTree(join(fixture, "workdir"), paths.workdir);
registry.save({ ...run, state: "done", report, pid: null });
console.log(`seeded ${run.id} (${run.paper}) into ${paths.workdir}`);
