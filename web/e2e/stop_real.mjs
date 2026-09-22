// Starts a small real PaperBench run through the form, stops it once the agents are working,
// then deletes it from Runs. Used to check that stopping kills the OpenCode process group
// inside the container. Usage: node stop_real.mjs [baseUrl]
import { chromium } from "@playwright/test";
import { resolve } from "node:path";

const base = process.argv[2] ?? "http://127.0.0.1:8000";
const data = resolve(
  new URL("../../benchmarks/paperbench/data/classifier-free-guidance/", import.meta.url)
    .pathname,
);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => {
  if (m.type() === "error") errors.push(`console: ${m.text()}`);
});
const field = (name) =>
  page.locator(
    `label.field:has(> span:text-is("${name}")) input, label.field:has(> span:text-is("${name}")) select`,
  );

await page.goto(base + "/");
await page.waitForSelector("form.compose");
await page.getByLabel("Title (optional)").fill("CFG (stop test)");
await page.locator('input[type="file"][accept*="pdf"]').setInputFiles(`${data}/paper.pdf`);
await page.locator('input[type="file"][accept*="json"]').setInputFiles(
  `${data}/rubric_branch.json`,
);
await field("Agents").fill("2");
await field("Rounds").fill("2");
await field("Minutes per round").fill("3");
await field("Steps per round").fill("10");
await field("Agents at once").fill("2");
await page.getByLabel("Limit in USD").fill("0.1");
await page.getByLabel("Write the cast").uncheck();
await page.getByRole("button", { name: "Start the swarm" }).click();
await page.waitForURL(/\/paperbench\//, { timeout: 60000 });
const id = page.url().split("/").at(-1);
console.log("run", id);

const started = Date.now();
let phase = "";
while (Date.now() - started < 8 * 60 * 1000) {
  await page.waitForTimeout(10000);
  phase = (await page.locator(".paper-progress .hint").first().textContent().catch(() => "")) ?? "";
  const working = await page.locator(".swarm-live").first().textContent().catch(() => "");
  console.log(Math.round((Date.now() - started) / 1000) + "s |", phase.trim(), "|", (working ?? "").trim());
  if (/round/i.test(phase) && (working ?? "").trim()) break;
}
console.log("STOP_NOW");
await page.getByRole("button", { name: "Stop the run" }).click();
await page.locator(".meter .status-badge").first().waitFor();
for (let i = 0; i < 30; i++) {
  const badge = (await page.locator(".meter .status-badge").first().textContent()) ?? "";
  if (badge.trim() === "stopped") break;
  await page.waitForTimeout(1000);
}
console.log("badge", (await page.locator(".meter .status-badge").first().textContent())?.trim());
console.log("STOPPED");
await page.waitForTimeout(3000);
await page.goto(base + "/runs");
page.on("dialog", (d) => d.accept());
const row = page.locator("tbody tr", { hasText: "CFG (stop test)" }).first();
await row.getByRole("button", { name: "Delete" }).click();
await page.waitForTimeout(3000);
const left = await page.locator("tbody tr", { hasText: "CFG (stop test)" }).count();
console.log("rows left with that title", left);
console.log(errors.length ? errors.join("\n") : "no browser errors");
await browser.close();
