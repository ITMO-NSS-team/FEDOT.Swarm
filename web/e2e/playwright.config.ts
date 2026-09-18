import { defineConfig } from "@playwright/test";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

/** The front end under a fake runner: no model, no money, a recorded fixture replayed by
 * `fake_runner.sh`. The dev server gets its own port and an empty data directory. */
const here = resolve(new URL(".", import.meta.url).pathname);
// the config is loaded again in every worker, so the directory is fixed once through the
// environment the workers inherit
const dataDir = process.env.FEDOTMAS_E2E_DIR ??
  mkdtempSync(join(tmpdir(), "fedotmas-e2e-"));
process.env.FEDOTMAS_E2E_DIR = dataDir;
const control = join(dataDir, "control");
mkdirSync(control, { recursive: true });
process.env.FAKE_CONTROL = control;
const port = 5199;

export default defineConfig({
  testDir: here,
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1360, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `deno task dev --port ${port}`,
    cwd: resolve(here, ".."),
    url: `http://127.0.0.1:${port}/runs`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      FEDOTMAS_WEB_DATA_DIR: dataDir,
      FEDOTMAS_PAPERBENCH_WORKDIR: join(dataDir, "workdir"),
      FEDOTMAS_RUNNER: join(here, "fake_runner.sh"),
      FEDOTMAS_MAX_RUNNING: "3",
      FAKE_CONTROL: control,
    },
  },
});
