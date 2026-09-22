import { expect, type Page, test } from "@playwright/test";
import { rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const control = process.env.FAKE_CONTROL!;
const flag = (name: string, on: boolean) => {
  if (on) writeFileSync(join(control, name), "");
  else rmSync(join(control, name), { force: true });
};

const data = resolve(
  new URL("../../benchmarks/paperbench/data/classifier-free-guidance/", import.meta.url)
    .pathname,
);

/** A form field by the text of its label, which also carries a hint the accessible name
 * would otherwise include. */
const field = (page: Page, name: string) =>
  page.locator(
    `label.field:has(> span:text-is("${name}")) input, label.field:has(> span:text-is("${name}")) select`,
  );

/** Fills the PaperBench form with the bundled paper and starts it under the fake runner. */
async function start(page: Page, extra: Record<string, string> = {}) {
  await page.goto("/");
  await page.waitForSelector("form.compose");
  await page.getByLabel("Title (optional)").fill("CFG e2e");
  await page.locator('input[type="file"][accept*="pdf"]').setInputFiles(
    `${data}/paper.pdf`,
  );
  await page.locator('input[type="file"][accept*="json"]').setInputFiles(
    `${data}/rubric_branch.json`,
  );
  await field(page, "Agents").fill("2");
  await field(page, "Rounds").fill("2");
  for (const [label, value] of Object.entries(extra)) {
    await field(page, label).fill(value);
  }
  await page.getByRole("button", { name: "Start the swarm" }).click();
  await page.waitForURL(/\/paperbench\//);
  return page.url().split("/").at(-1)!;
}

test("the form refuses a run without a paper or without a cap", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Start the swarm" }).click();
  await expect(page.locator(".form-error")).toHaveText(/Attach the paper's PDF/);
  await page.locator('input[type="file"][accept*="pdf"]').setInputFiles(
    `${data}/paper.pdf`,
  );
  await page.getByLabel("Limit in USD").fill("0");
  await page.getByRole("button", { name: "Start the swarm" }).click();
  await expect(page.locator(".form-error")).toHaveText(/rubric|limit above zero/);
  await expect(page.getByRole("button", { name: "Start the swarm" })).toBeEnabled();
});

test("a run goes from live to finished and can be explored", async ({ page }) => {
  const id = await start(page);
  await expect(page.locator(".meter .status-badge")).toHaveText("running");
  await expect(page.locator(".paper-progress .hint")).toHaveText(/Reading the PDF|Writing code|Reviewing/);
  await expect(page.locator(".meter .status-badge")).toHaveText("done", { timeout: 30_000 });
  await expect(page.locator(".meter-score .meter-amount")).toHaveText(/\d+%/);
  await expect(page.locator(".paper-result")).toContainText("Kept: the workspace of coder_0");

  await page.getByRole("tab", { name: "Voices" }).click();
  await expect(page.locator(".paper-explore tbody tr")).toHaveCount(2);
  await expect(page.locator(".row-kept")).toContainText("coder_0");

  await page.getByRole("tab", { name: "Rubric" }).click();
  await expect(page.locator(".checklist li")).toHaveCount(70);
  await page.getByRole("button", { name: "Failed only" }).click();
  await expect(page.locator(".checklist li.pass")).toHaveCount(0);
  await page.locator(".checklist li .check-row").first().click();
  await expect(page.locator(".check-reason")).toBeVisible();

  await page.getByRole("tab", { name: "Files" }).click();
  await expect(page.locator(".file-tree button")).not.toHaveCount(0);
  await page.locator(".file-tree button", { hasText: "cfg_lm/cfg.py" }).click();
  await expect(page.locator(".code-view")).toContainText("def ");
  await field(page, "Root").selectOption("ws/coder_1");
  await page.getByRole("button", { name: /^Rounds/ }).click();
  await expect(page.locator(".rounds li")).toHaveCount(2);

  await page.getByRole("tab", { name: "Run details" }).click();
  await expect(page.locator(".command pre")).toContainText("benchmarks/paperbench/run.py");
  await expect(page.locator(".details")).toContainText("Started from the Compose form");

  const zip = await page.request.get(`/api/paperbench/${id}/download?root=solution`);
  expect(zip.status()).toBe(200);
  expect(zip.headers()["content-type"]).toContain("application/zip");
  const escape = await page.request.get(`/api/paperbench/${id}/file?root=solution&path=../../web.sqlite3`);
  expect(escape.status()).toBe(404);
});

test("reproduce starts a child run that points back at its parent", async ({ page }) => {
  const id = await start(page);
  await expect(page.locator(".meter .status-badge")).toHaveText("done", { timeout: 30_000 });
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Reproduce this run" }).click();
  await page.waitForURL((url) => /\/paperbench\//.test(url.pathname) && !url.pathname.endsWith(id));
  await page.getByRole("tab", { name: "Run details" }).click();
  await expect(page.locator(".details")).toContainText(`Reproduced from CFG e2e (${id})`);
  await expect(page.locator(".meter .status-badge")).toHaveText("done", { timeout: 30_000 });
  await page.goto("/runs");
  await expect(page.locator("tbody")).toContainText("1 reproduced");
});

test("stop ends a run and delete asks first", async ({ page }) => {
  flag("slow", true);
  await start(page);
  flag("slow", false);
  await expect(page.locator(".meter .status-badge")).toHaveText("running");
  await page.getByRole("button", { name: "Stop the run" }).click();
  await expect(page.locator(".meter .status-badge")).toHaveText("stopped", {
    timeout: 15_000,
  });
  await page.goto("/runs");
  const rows = page.locator("tbody tr");
  const before = await rows.count();
  const row = rows.filter({
    has: page.locator(".status-badge", { hasText: "Stopped" }),
  }).first();
  await expect(row).toBeVisible();
  page.once("dialog", (d) => d.dismiss());
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(rows).toHaveCount(before);
  page.once("dialog", (d) => d.accept());
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(before - 1);
  await expect(page.locator("tbody")).not.toContainText("Stopped");
});

test("a failed run shows a redacted log tail", async ({ page }) => {
  flag("fail", true);
  try {
    const id = await start(page);
    await expect(page.locator(".meter .status-badge")).toHaveText("failed", { timeout: 20_000 });
    const text = await page.locator(".paper-result .form-error").textContent();
    expect(text).toContain("[redacted]");
    expect(text).not.toContain("deadbeef");
    const api = await page.request.get(`/api/paperbench/${id}`);
    expect((await api.text()).includes("deadbeef")).toBe(false);
  } finally {
    flag("fail", false);
  }
});
