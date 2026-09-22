// Walks the demo scenario in headless Chromium and saves screenshots: a debugging aid, not
// a test. Usage: node walk.mjs [baseUrl] [runId]
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const base = process.argv[2] ?? "http://127.0.0.1:5173";
const runId = process.argv[3] ?? null;
const out = new URL("./shots/", import.meta.url).pathname;
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => {
  if (m.type() === "error") errors.push(`console: ${m.text()}`);
});
page.on("response", (r) => {
  if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);
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

await page.goto(base + "/");
await page.waitForSelector("form.compose");
await shot("01-compose-paperbench");
await page.getByRole("button", { name: "Free topic" }).click();
await shot("02-compose-topic");
await page.getByRole("button", { name: "PaperBench" }).click();
// submit with nothing attached: the form must explain, not throw
await page.getByRole("button", { name: "Start the swarm" }).click();
await page.waitForSelector(".form-error");
console.log("compose error:", await page.locator(".form-error").textContent());
await shot("03-compose-validation");

await page.goto(base + "/runs");
await page.waitForSelector("main");
await shot("04-runs");

if (runId) {
  await page.goto(`${base}/paperbench/${runId}`);
  await page.waitForSelector(".swarm-canvas svg");
  await page.waitForTimeout(3000);
  await shot("05-run-live");
  const node = page.locator(".swarm-nodes .node").first();
  if (await node.count()) {
    await node.click();
    await page.waitForTimeout(500);
    await shot("06-run-voice-card");
  }
  for (const tab of ["Voices", "Rubric", "Files", "Run details"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(1500);
    await shot(`07-run-${tab.toLowerCase().replace(" ", "-")}`);
  }
}

console.log(errors.length ? errors.join("\n") : "no browser errors");
await browser.close();
