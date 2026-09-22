// Starts a real PaperBench run through the form, watches it in headless Chromium, and saves
// screenshots along the way. A debugging aid that spends money: keep the caps small.
// Usage: node run_real.mjs [baseUrl]
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const base = process.argv[2] ?? "http://127.0.0.1:5173";
const out = new URL("./shots/", import.meta.url).pathname;
mkdirSync(out, { recursive: true });
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
const shot = async (name) => {
  try {
    await page.screenshot({
      path: `${out}${name}.png`,
      fullPage: true,
      animations: "disabled",
      timeout: 15000,
    });
  } catch (error) {
    errors.push(`screenshot ${name}: ${error.message.split("\n")[0]}`);
  }
};
const field = (name) =>
  page.locator(
    `label.field:has(> span:text-is("${name}")) input, label.field:has(> span:text-is("${name}")) select`,
  );

await page.goto(base + "/");
await page.waitForSelector("form.compose");
await page.getByLabel("Title (optional)").fill("Classifier-Free Guidance (smoke)");
await page.locator('input[type="file"][accept*="pdf"]').setInputFiles(`${data}/paper.pdf`);
await page.locator('input[type="file"][accept*="json"]').setInputFiles(
  `${data}/rubric_branch.json`,
);
await field("Agents").fill("2");
await field("Rounds").fill("2");
await field("Minutes per round").fill("3");
await field("Steps per round").fill("14");
await field("Agents at once").fill("2");
await page.getByLabel("Limit in USD").fill("0.3");
await page.getByLabel("Write the cast").uncheck();
await shot("10-compose-filled");
await page.getByRole("button", { name: "Start the swarm" }).click();
await page.waitForURL(/\/paperbench\//, { timeout: 60000 });
const id = page.url().split("/").at(-1);
console.log("run", id);

const started = Date.now();
let shots = 0;
let state = "running";
while (Date.now() - started < 25 * 60 * 1000) {
  await page.waitForTimeout(20000);
  const badge = await page.locator(".meter .status-badge").first().textContent().catch(() => "?");
  const phase = await page.locator(".paper-progress .hint").first().textContent().catch(() => "");
  const working = await page.locator(".swarm-live").first().textContent().catch(() => "");
  console.log(Math.round((Date.now() - started) / 1000) + "s", badge, "|", phase?.trim(), "|", working?.trim());
  state = (badge ?? "").trim();
  if (shots < 4 && (working || phase)) {
    await shot(`11-live-${shots}`);
    shots++;
    if (shots === 2) {
      const node = page.locator(".swarm-nodes .node").first();
      if (await node.count()) {
        await node.click();
        await page.waitForTimeout(500);
        await shot("12-live-voice-card");
      }
    }
  }
  if (["done", "failed", "stopped", "lost"].includes(state)) break;
}
await page.waitForTimeout(2500);
await shot("13-finished");
for (const tab of ["Voices", "Rubric", "Files", "Run details"]) {
  await page.getByRole("tab", { name: tab }).click();
  await page.waitForTimeout(1500);
  await shot(`14-${tab.toLowerCase().replace(" ", "-")}`);
}
await page.goto(base + "/runs");
await page.waitForSelector("main");
await shot("15-runs");
console.log("final state", state);
console.log(errors.length ? errors.join("\n") : "no browser errors");
await browser.close();
