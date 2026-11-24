// End-to-end browser check of the managed-service workflows (admin + client).
// Runs real Chrome against the real frontend + backend + Postgres, with local stand-ins for
// Supabase Auth and Vapi (see backend/tests/e2e_fake_services.py).
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";

const APP = process.env.E2E_APP_URL ?? "http://localhost:3000";
const FAKES = process.env.E2E_FAKES_URL ?? "http://localhost:9100";
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });
const ADMIN_PW = "ops-very-strong-pass";

const results = [];
let page;
const step = async (name, fn) => {
  const t = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - t });
    console.log(`PASS  ${name}`);
  } catch (e) {
    await page.screenshot({ path: `${SHOTS}FAIL-${results.length + 1}.png`, fullPage: true }).catch(() => {});
    results.push({ name, ok: false, error: String(e).slice(0, 400) });
    console.log(`FAIL  ${name}\n      ${String(e).slice(0, 400)}`);
  }
};

const browser = await chromium.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", headless: true });
const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
page = await ctx.newPage();
const consoleErrors = [];
const watch = (p) => p.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
watch(page);
const shot = (n, p = page) => p.screenshot({ path: `${SHOTS}${n}.png`, fullPage: true });
const post = async (path, body) =>
  (await fetch(`${FAKES}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
const sim = (body) => post("/sim/call", body);
const expectText = async (text, p = page, timeout = 15000) => p.getByText(text, { exact: false }).first().waitFor({ timeout });
const tab = (name) => page.getByRole("button", { name, exact: true }).click();
let clientUrl = "";
let owner; // second browser context: the client owner

async function confirmPassword(password = ADMIN_PW) {
  await page.getByLabel("Your password").fill(password);
  await page.getByRole("button", { name: "Confirm" }).click();
}

async function login(p, email, password) {
  await p.goto(`${APP}/login`);
  await p.getByRole("textbox", { name: "Email" }).fill(email);
  await p.getByLabel("Password").fill(password);
  await p.getByRole("button", { name: "Sign in" }).click();
}

await step("Public site: no pricing, no self-registration", async () => {
  await page.goto(APP);
  await expectText("Your HVAC Business. Your AI Receptionist.");
  await expectText("Talk to BILEKSA");
  if (await page.getByRole("link", { name: /pricing|get started|sign up/i }).count()) throw new Error("public signup/pricing link");
  for (const path of ["/pricing", "/signup", "/onboarding"]) {
    const r = await page.goto(`${APP}${path}`);
    if (r.status() !== 404) throw new Error(`${path} returned ${r.status()}`);
  }
  await page.goto(APP);
  await shot("01-home");
});

await step("BILEKSA admin signs in with two-step verification", async () => {
  const { id } = await post("/sim/create-user", { email: "ops@bileksa.com", password: ADMIN_PW });
  execFileSync("uv", ["run", "python", "-m", "app.cli", "add-admin", id, "ops@bileksa.com"], { cwd: new URL("../backend", import.meta.url).pathname, stdio: "pipe" });
  await login(page, "ops@bileksa.com", ADMIN_PW);
  await page.waitForURL("**/admin");
  await expectText("Set up two-step sign-in");
  await page.getByLabel("6-digit code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expectText("That code didn't work");
  await page.getByLabel("6-digit code").fill("123456");
  await page.getByRole("button", { name: "Verify" }).click();
  await expectText("Create a client");
  await shot("02-admin-clients-empty");
});

await step("Admin creates a client; the Vapi assistant is provisioned from the master template", async () => {
  await page.getByLabel("Business name").fill("ABC Heating & Cooling");
  await page.getByLabel("Contact email").fill("office@abc-hvac.com");
  await page.getByRole("button", { name: "Create client" }).click();
  await page.waitForURL(/\/admin\/client\/?\?id=/);
  clientUrl = page.url();
  await expectText("onboarding steps complete");
  let ok = false;
  for (let i = 0; i < 30 && !ok; i++) {
    const st = await (await fetch(`${FAKES}/sim/state`)).json();
    ok = st.assistants.length === 1 && st.assistants[0].firstMessage.includes("ABC Heating & Cooling");
    if (!ok) await new Promise((r) => setTimeout(r, 500));
  }
  if (!ok) throw new Error("assistant not provisioned");
  await shot("03-client-created");
});

await step("Admin configures routing, services, areas, hours, FAQs and emergency rules", async () => {
  await tab("Business & routing");
  await page.getByLabel("Transfer number (direct line)").fill("(713) 555-0123");
  await page.getByLabel("Fallback / backup number").fill("(713) 555-0166");
  await page.getByLabel("Owner notification email").fill("owner@abc-hvac.com");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expectText("Saved. Phone routing");
  await shot("04-routing");
  await tab("Services");
  await page.getByLabel("Service name").fill("AC Repair");
  await page.getByLabel("Price from ($)").fill("89");
  await page.getByLabel("Price up to ($)").fill("450");
  await page.getByRole("button", { name: "Add service" }).click();
  await expectText("$89 – $450");
  await tab("Service areas");
  await page.getByLabel("ZIP codes").fill("77002, 77003 77004");
  await page.getByRole("button", { name: "Add ZIP codes" }).click();
  await expectText("Added 3 ZIP code(s).");
  await tab("Hours");
  for (const d of ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]) {
    const row = page.locator("div", { hasText: d }).filter({ has: page.getByRole("checkbox") }).last();
    await row.getByRole("checkbox").check();
  }
  for (const input of await page.locator('input[type="time"]').all()) await input.fill("00:00");
  for (const c of await page.getByLabel(/closes$/).all()) await c.fill("23:59");
  await page.getByRole("button", { name: "Save hours" }).click();
  await expectText("Business hours saved.");
  await tab("FAQs");
  await page.getByLabel("Question or policy name").fill("Do you offer financing?");
  await page.getByLabel("Approved answer").fill("Yes, 12 months same as cash on new systems.");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expectText("12 months same as cash");
  await tab("Emergency");
  await page.getByRole("button", { name: "Add custom category" }).click();
  await page.getByLabel("Category name").fill("Flooding near furnace");
  await page.getByLabel("Approved instructions (required)").fill("Stay away from standing water near the furnace.");
  await page.getByRole("button", { name: "Save emergency rules" }).click();
  await expectText("Saved. The assistant is re-synced");
  await shot("05-emergency-rules");
});

await step("Package assignment requires the admin password (wrong password rejected)", async () => {
  await tab("Overview");
  await page.getByLabel("Assign / upgrade / downgrade package").selectOption({ index: 1 });
  await page.getByRole("button", { name: "Assign package" }).click();
  await confirmPassword("wrong-password");
  await expectText("Password is incorrect");
  await confirmPassword();
  await expectText("Change applied and logged");
  await expectText("Starter · 0 of 300");
  await shot("06-package-assigned");
});

await step("Phone number is assigned with server-side routing and verified by a test call", async () => {
  await tab("Phone & Vapi");
  await page.getByLabel("Client's business number").fill("(713) 555-0100");
  await page.getByLabel("Carrier").selectOption("verizon");
  await page.getByRole("button", { name: "Assign Vapi number" }).click();
  await expectText("Phone number saved.");
  await expectText("*71");
  await expectText("Routing synced");
  const st = await (await fetch(`${FAKES}/sim/state`)).json();
  const pn = st.phone_numbers[0];
  if (pn.assistantId) throw new Error("phone number has a fixed assistant (no gate)");
  if (!pn.server?.url?.endsWith("/vapi/events")) throw new Error("phone number not routed to the gate");
  if (pn.fallbackDestination?.number !== "+17135550123") throw new Error("fallbackDestination missing");
  await page.getByRole("button", { name: "Start test call" }).click();
  await expectText("Test window open");
  const r = await sim({ kind: "test" });
  if (r.forwarded) throw new Error("test call did not reach the AI");
  await page.reload();
  await tab("Phone & Vapi");
  await expectText("Verified");
  await shot("07-phone-verified");
});

await step("Admin activates the client (password-confirmed)", async () => {
  await tab("Overview");
  await page.getByRole("button", { name: "Activate client" }).click();
  await confirmPassword();
  await expectText("Change applied and logged");
  await expectText("Active");
  await shot("08-activated");
});

await step("Admin invites the owner; the owner signs in to their dashboard", async () => {
  await page.getByLabel("Invite the client owner by email").fill("owner@abc-hvac.com");
  await page.getByRole("button", { name: "Send invitation" }).click();
  await expectText("Invitation sent to owner@abc-hvac.com");
  const invites = await (await fetch(`${FAKES}/sim/invites`)).json();
  if (!invites.some((i) => i.email === "owner@abc-hvac.com" && i.redirect_to.endsWith("/reset-password")))
    throw new Error("invite not sent through Supabase");
  await post("/sim/accept-invite", { email: "owner@abc-hvac.com", password: "correct-horse-battery" });
  const ctx2 = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  owner = await ctx2.newPage();
  watch(owner);
  await login(owner, "owner@abc-hvac.com", "correct-horse-battery");
  await owner.waitForURL("**/app");
  await expectText("AI receptionist status", owner);
  await expectText("Starter", owner);
  await shot("09-owner-overview-empty", owner);
});

await step("Calls produce leads, callbacks, appointment requests, summaries and an emergency", async () => {
  const lead = await sim({ kind: "lead" });
  if (lead.forwarded) throw new Error("lead call did not reach the AI");
  if (lead.results.request_appointment.booked !== false) throw new Error("appointment falsely booked");
  await sim({ kind: "emergency" });
  await owner.goto(`${APP}/app`);
  await expectText("Leads generated", owner);
  const total = await owner.locator("text=Total calls").locator("xpath=following-sibling::p[1]").innerText();
  if (total.trim() !== "2") throw new Error(`total calls ${total}`);
  await shot("10-owner-overview", owner);
  await owner.goto(`${APP}/app/calls`);
  await expectText("Caller reported warm air", owner);
  await expectText("Check numbers: $6,500", owner);
  if (await owner.getByText("Check numbers: $89").count()) throw new Error("approved price wrongly flagged");
  await shot("11-calls", owner);
  await owner.goto(`${APP}/app/leads`);
  await expectText("Jordan Smith", owner);
  await expectText("Equipment: Central ac", owner);
  await owner.goto(`${APP}/app/callbacks`);
  await expectText("Tuesday morning", owner);
  await owner.getByRole("button", { name: "Confirmed" }).first().click();
  await owner.getByRole("button", { name: "Mark done" }).last().waitFor();
  await shot("12-callbacks-appointments", owner);
  await owner.goto(`${APP}/app/notifications`);
  await expectText("EMERGENCY call: Gas smell", owner);
  await expectText("New call from Jordan Smith", owner);
  await shot("13-notifications", owner);
});

await step("Client sees business info read-only and cannot change configuration", async () => {
  await owner.goto(`${APP}/app/business`);
  await expectText("AC Repair", owner);
  await expectText("12 months same as cash", owner);
  await expectText("Flooding near furnace", owner);
  for (const name of ["Add service", "Save changes", "Assign package", "Save hours"])
    if (await owner.getByRole("button", { name }).count()) throw new Error(`client sees "${name}"`);
  await shot("14-business-info", owner);
});

await step("Client requests an upgrade; admin activates it after payment (password-confirmed)", async () => {
  await owner.goto(`${APP}/app/packages`);
  await owner.getByRole("button", { name: "Choose" }).first().click();
  await owner.getByRole("button", { name: "Request upgrade" }).click();
  await expectText("Request sent", owner);
  await page.goto(`${APP}/admin/upgrades`);
  await expectText("ABC Heating & Cooling");
  await expectText("Professional");
  await shot("15-admin-upgrades");
  await page.goto(clientUrl);
  await page.getByRole("button", { name: "Activate requested package" }).click();
  await confirmPassword();
  await expectText("Change applied and logged");
  await owner.goto(`${APP}/app/packages`);
  const current = owner.locator("section", { hasText: "Current" });
  await current.getByText("Professional").waitFor({ timeout: 15000 });
  await shot("16-owner-packages", owner);
});

await step("Hard minute limit: AI stops for new calls and calls are forwarded", async () => {
  await page.getByLabel("Change minute limit").fill("5");
  await page.getByRole("button", { name: "Change limit" }).click();
  await confirmPassword();
  await expectText("LIMIT_REACHED");
  const r = await sim({ kind: "lead" });
  if (!r.forwarded) throw new Error("AI answered after the limit");
  if (r.results["assistant-request"].destination?.number !== "+17135550123") throw new Error("not forwarded to the direct line");
  await owner.goto(`${APP}/app`);
  await expectText("You have used all 5 included minutes", owner);
  await shot("17-owner-limit-reached", owner);
  await page.goto(`${APP}/admin/usage`);
  await expectText("LIMIT_REACHED");
  await shot("18-admin-usage");
  // restoring: raise the limit again
  await page.goto(clientUrl);
  await page.getByLabel("Change minute limit").fill("700");
  await page.getByRole("button", { name: "Change limit" }).click();
  await confirmPassword();
  await expectText("Change applied and logged");
  const again = await sim({ kind: "test" });
  if (again.forwarded) throw new Error("AI not restored");
});

await step("Admin records a payment; costs and profit are internal only", async () => {
  await tab("Payments");
  await page.getByLabel("Amount ($)").fill("399");
  await page.getByRole("button", { name: "Record payment" }).click();
  await expectText("$399");
  await page.goto(`${APP}/admin/costs`);
  await expectText("Gross profit");
  await expectText("ABC Heating & Cooling");
  await shot("19-admin-costs");
  await page.goto(`${APP}/admin/audit`);
  await expectText("Service assign package");
  await expectText("Admin password rejected");
  await shot("20-admin-audit");
  for (const path of ["/app", "/app/usage", "/app/packages", "/app/calls"]) {
    await owner.goto(`${APP}${path}`);
    await owner.waitForLoadState("networkidle");
    const text = (await owner.locator("main").innerText()).toLowerCase();
    if (text.includes("cost") || text.includes("setup fee") || text.includes("gross")) throw new Error(`internal costs visible on ${path}`);
  }
});

await step("A second client sees none of the first client's data", async () => {
  await page.goto(`${APP}/admin`);
  await page.getByLabel("Business name").fill("XYZ Cooling Services");
  await page.getByRole("button", { name: "Create client" }).click();
  await page.waitForURL(/\/admin\/client\/?\?id=/);
  await page.getByLabel("Invite the client owner by email").fill("owner@xyz-cooling.com");
  await page.getByRole("button", { name: "Send invitation" }).click();
  await expectText("Invitation sent");
  await post("/sim/accept-invite", { email: "owner@xyz-cooling.com", password: "another-strong-pass" });
  const ctx3 = await browser.newContext();
  const p3 = await ctx3.newPage();
  await login(p3, "owner@xyz-cooling.com", "another-strong-pass");
  await p3.waitForURL("**/app");
  await p3.goto(`${APP}/app/leads`);
  await p3.getByText("No leads yet").waitFor({ timeout: 15000 });
  if (await p3.getByText("Jordan Smith").count()) throw new Error("cross-client leak");
  await p3.goto(`${APP}/app/notifications`);
  await p3.getByText("No notifications").waitFor({ timeout: 15000 });
  await shot("21-second-client-empty", p3);
  await ctx3.close();
});

await step("A client cannot open the admin area", async () => {
  await owner.goto(`${APP}/admin`);
  await owner.getByText("This area is for BILEKSA staff only.").waitFor({ timeout: 15000 });
});

await step("Password reset request and form", async () => {
  const ctx4 = await browser.newContext();
  const p4 = await ctx4.newPage();
  await p4.goto(`${APP}/login`);
  await p4.getByRole("link", { name: "Forgot your password?" }).click();
  await p4.waitForURL("**/forgot-password");
  await p4.getByRole("textbox", { name: "Email" }).fill("owner@abc-hvac.com");
  await p4.getByRole("button", { name: "Send reset link" }).click();
  await p4.getByText("a reset link is on its way").waitFor({ timeout: 15000 });
  const sent = await (await fetch(`${FAKES}/sim/recover-requests`)).json();
  if (!sent.includes("owner@abc-hvac.com")) throw new Error("reset email not requested");
  await p4.goto(`${APP}/reset-password`);
  await p4.getByLabel("New password").waitFor();
  await ctx4.close();
});

await step("Mobile layout works", async () => {
  await owner.setViewportSize({ width: 390, height: 844 });
  await owner.goto(`${APP}/app`);
  await expectText("Total calls", owner);
  await owner.getByRole("button", { name: "Menu" }).click();
  await expectText("Call history", owner);
  await shot("22-mobile", owner);
});

await browser.close();
const failed = results.filter((r) => !r.ok);
// 403 (wrong admin password), 404 (removed public pages) and 422 (wrong MFA code) are
// deliberately triggered above; anything else is a real error.
const realErrors = consoleErrors.filter((e) => !e.includes("favicon") && !/status of (403|404|422)/.test(e));
console.log(`\n${results.length - failed.length}/${results.length} workflows passed; browser console errors: ${realErrors.length}`);
realErrors.slice(0, 5).forEach((e) => console.log("  console:", e.slice(0, 200)));
process.exit(failed.length ? 1 : 0);
