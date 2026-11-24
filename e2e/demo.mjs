// End-to-end browser check of the PUBLIC DEMO build (DEMO_MODE on the API,
// NEXT_PUBLIC_DEMO_MODE on the site). Same local stand-ins as run.mjs.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const APP = process.env.E2E_APP_URL ?? "http://localhost:3000";
const SHOTS = new URL("./screenshots/demo-", import.meta.url).pathname;
mkdirSync(new URL("./screenshots/", import.meta.url).pathname, { recursive: true });

const results = [];
let page;
const step = async (name, fn) => {
  try {
    await fn();
    results.push({ name, ok: true });
    console.log(`PASS  ${name}`);
  } catch (e) {
    await page.screenshot({ path: `${SHOTS}FAIL-${results.length + 1}.png`, fullPage: true }).catch(() => {});
    results.push({ name, ok: false });
    console.log(`FAIL  ${name}\n      ${String(e).slice(0, 400)}`);
  }
};

const browser = await chromium.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", headless: true });
const consoleErrors = [];
const ctxA = await browser.newContext({ viewport: { width: 1360, height: 900 } });
const ctxO = await browser.newContext({ viewport: { width: 1360, height: 900 } });
const admin = await ctxA.newPage();
const owner = await ctxO.newPage();
for (const p of [admin, owner]) {
  p.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  p.on("response", (r) => r.status() === 404 && console.log("  404:", r.url()));
}
page = owner;
const expectText = (text, p, timeout = 20000) => p.getByText(text, { exact: false }).first().waitFor({ timeout });
const shot = (n, p) => p.screenshot({ path: `${SHOTS}${n}.png`, fullPage: true });

await step("Public site shows the demo banner and the demo entry point", async () => {
  await owner.goto(APP);
  await expectText("Public demo.", owner);
  await owner.getByRole("link", { name: "Try the live demo" }).click();
  await owner.waitForURL("**/demo");
  await expectText("owner@houstoncomfort.example", owner);
  await expectText("admin@bileksa-demo.example", owner);
  await shot("01-demo-page", owner);
});

await step("Visitor enters as the business owner and sees a populated dashboard", async () => {
  await owner.getByRole("button", { name: "Enter as business owner" }).click();
  await owner.waitForURL("**/app");
  await expectText("Houston Comfort HVAC", owner);
  await expectText("Total calls", owner);
  await owner.goto(`${APP}/app/calls`);
  await expectText("Emergency", owner);
  await owner.goto(`${APP}/app/leads`);
  await owner.locator("a[href^='/app/lead?id=']").first().click();
  await expectText("Timeline", owner);
  await owner.goto(`${APP}/app/usage`);
  await expectText("Professional", owner);
  await shot("02-owner-dashboard", owner);
});

await step("Live browser voice is offered while the budget lasts", async () => {
  await owner.goto(`${APP}/app/try`);
  await expectText("Live voice", owner);
  await owner.getByRole("button", { name: "Start call" }).waitFor();
  await shot("03-try-live", owner);
});

await step("Simulated emergency call runs the real pipeline and lands in call history", async () => {
  await owner.getByRole("combobox").selectOption("emergency");
  await owner.getByRole("button", { name: "Run simulated call" }).click();
  await expectText("Summary:", owner);
  await expectText("Simulated call:", owner);
  await shot("04-try-simulation", owner);
  await owner.getByRole("link", { name: "Call history" }).last().click();
  await expectText("Simulated call:", owner);
});

await step("Visitor enters as the BILEKSA admin without an authenticator app", async () => {
  await admin.goto(`${APP}/demo`);
  await admin.getByRole("button", { name: "Enter as bileksa admin" }).click();
  await admin.waitForURL("**/admin");
  await expectText("Bayou City Air (demo)", admin);
  await expectText("Houston Comfort HVAC", admin);
  await shot("05-admin-clients", admin);
});

await step("Admin demo controls: the budget ceiling holds and exhausting it switches to simulation", async () => {
  await admin.getByRole("link", { name: "Demo controls" }).click();
  await expectText("Spent this month", admin);
  // the form can't go above the operator's ceiling (the API rejects it too; see test_demo.py)
  if ((await admin.getByLabel("Monthly voice budget (USD)").getAttribute("max")) !== "5")
    throw new Error("budget ceiling not applied");
  await admin.getByLabel("Monthly voice budget (USD)").fill("0");
  await admin.getByRole("button", { name: "Save", exact: true }).click();
  await expectText("Budget saved", admin);
  await expectText("budget has been used", admin);
  await owner.goto(`${APP}/app/try`);
  await expectText("Live voice is unavailable right now", owner);
  if (await owner.getByRole("button", { name: "Start call" }).count()) throw new Error("live call still offered");
  await shot("06-try-fallback", owner);
});

await step("Phone forwarding and owner invitations are blocked in the demo", async () => {
  await admin.goto(`${APP}/admin`);
  await admin.locator("a[href^='/admin/client?id=']").filter({ hasText: "Houston Comfort HVAC" }).first().click();
  await expectText("onboarding steps complete", admin);
  await admin.getByLabel("Invite the client owner by email").fill("someone@example.com");
  await admin.getByRole("button", { name: "Send invitation" }).click();
  await expectText("demo", admin);
  await admin.getByRole("button", { name: "Phone & Vapi", exact: true }).click();
  await admin.getByLabel("Client's business number").fill("7135550188");
  await admin.getByRole("button", { name: /Assign Vapi number|Update/ }).click();
  await expectText("not part of the public demo", admin);
});

await step("Reset restores the demo and removes visitor changes", async () => {
  await admin.goto(`${APP}/admin/demo`);
  await admin.getByRole("button", { name: "Reset now" }).click();
  await expectText("Demo data reset", admin);
  await owner.goto(`${APP}/app/calls`);
  await expectText("Total", owner).catch(() => {});
  await owner.waitForLoadState("networkidle");
  if (await owner.getByText("Simulated call:").count()) throw new Error("simulated call survived the reset");
});

await browser.close();
const failed = results.filter((r) => !r.ok);
// 403/409/422 are triggered on purpose above (blocked invite/phone, budget ceiling).
const realErrors = consoleErrors.filter((e) => !e.includes("favicon") && !/status of (403|409|422)/.test(e));
console.log(`\n${results.length - failed.length}/${results.length} demo workflows passed; browser console errors: ${realErrors.length}`);
realErrors.slice(0, 5).forEach((e) => console.log("  console:", e.slice(0, 200)));
process.exit(failed.length ? 1 : 0);
