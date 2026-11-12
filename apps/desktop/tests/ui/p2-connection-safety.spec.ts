import type { Page, Route } from "@playwright/test";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off", video: "off" });
const button = (page: Page, name: string) => page.getByRole("button", { name, exact: true });
async function start(page: Page, conflicts = 0) {
  const sidecar = new MockAuthenticatedSidecar(900, 1000, "empty", conflicts);
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  await page.goto("/");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await button(page, "Create and unlock").click();
  await expect(page.getByLabel("Search vault")).toBeVisible();
  return sidecar;
}
async function gate(page: Page, path: string, response?: unknown) {
  let release!: () => void, entered!: () => void;
  const released = new Promise<void>(resolve => { release = resolve; });
  const ready = new Promise<void>(resolve => { entered = resolve; });
  await page.route(url => url.pathname === path, async route => {
    entered(); await released;
    if (response) await json(route, response); else await route.fallback();
  }, { times: 1 });
  return { ready, release };
}
async function json(route: Route, value: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
}
async function setupService(page: Page) {
  await button(page, "Connections").click();
  await page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Bitwarden", exact: true }) }).getByRole("button").click();
  await page.getByLabel("Server address", { exact: true }).fill("https://generated.example.invalid");
}
async function guarded(page: Page, target: string) {
  await button(page, target).click();
  await expect(page.getByRole("alertdialog", { name: "Discard unsaved changes?" })).toBeVisible();
  await button(page, "Keep editing").click();
}

test("saving freezes every entry field and nested editor action", async ({ page }) => {
  await start(page);
  await button(page, "Add password").click();
  await page.getByLabel("Website or app name", { exact: true }).fill("Generated frozen entry");
  await button(page, "More options").click();
  await button(page, "Add custom field").click();
  await page.getByLabel("Field name", { exact: true }).fill("Generated field");
  await button(page, "Save").click();
  await expect(page.getByLabel("Website or app name", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Field name", { exact: true })).toBeDisabled();
  await expect(button(page, "Add custom field")).toBeDisabled();
});

test("connection saves freeze source switches, inputs and advanced prefs", async ({ page }) => {
  await start(page); await setupService(page);
  const save = await gate(page, "/integrations/bitwarden");
  try {
    await button(page, "Save configuration").click(); await save.ready;
    await expect(page.getByLabel("Server address", { exact: true })).toBeDisabled();
    await expect(page.getByRole("region", { name: "Optional password services", exact: true }).locator(".connection-card").first().getByRole("button")).toBeDisabled();
    await button(page, "Settings").click();
    await expect(page.getByRole("heading", { name: "Connections", exact: true })).toBeVisible();
  } finally { save.release(); }
  await expect(button(page, "Save configuration")).toBeEnabled();
  await button(page, "Connection advanced settings").last().click();
  const advanced = page.getByRole("region", { name: "Connection advanced settings" });
  await advanced.getByLabel("Sync in the background after saving a password").check();
  const prefs = await gate(page, "/sync/preferences");
  try {
    await advanced.getByRole("button", { name: "Save configuration", exact: true }).click(); await prefs.ready;
    await expect(advanced.getByLabel("Sync in the background after saving a password")).toBeDisabled();
    await expect(advanced.getByLabel("Default sync location")).toBeDisabled();
  } finally { prefs.release(); }
});

test("connection configuration and computer setup drafts aggregate navigation and lock guards", async ({ page }) => {
  await start(page, 1); await setupService(page);
  await guarded(page, "Settings"); await guarded(page, "Lock now"); await guarded(page, "Review changes");
  await page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Proton Pass", exact: true }) }).getByRole("button").click();
  await page.getByLabel("Access token", { exact: false }).fill("generated-token-draft");
  await page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Bitwarden", exact: true }) }).getByRole("button").click();
  await expect(page.getByLabel("Server address", { exact: true })).toHaveValue("https://generated.example.invalid");
  await button(page, "Save configuration").click();
  await expect(button(page, "Save configuration")).toBeEnabled();
  await guarded(page, "Passwords");
  await button(page, "Set up computer sync").click();
  await page.getByLabel("This computer's name", { exact: true }).fill("Generated draft device");
  await guarded(page, "Passwords");
  await expect(page.getByLabel("This computer's name", { exact: true })).toHaveValue("Generated draft device");
});

async function conflicts(page: Page) {
  const state = { generation: 4, maskedRequests: 0, rejectMasked: false };
  await page.route(url => url.pathname === "/personal-sync/status", route => json(route, { connected: true, generation: state.generation, label: "Generated device", automatic: false, conflicts: 4, devices: [] }));
  await page.route(url => url.pathname === "/personal-sync/conflicts", async route => {
    const reveal = new URL(route.request().url()).searchParams.get("reveal") === "true";
    if (!reveal) state.maskedRequests++;
    if (!reveal && state.rejectMasked) { await route.abort(); return; }
    await json(route, payload(state.generation, reveal));
  });
  await button(page, "Connections").click();
  await button(page, "Review computer sync conflicts").click();
  await expect(page.getByRole("radio")).toHaveCount(4);
  return state;
}
function payload(generation: number, reveal: boolean) {
  return { generation, items: ["a1", "a2", "b1", "b2"].map(id => ({ id, object: id[0], title: `Generated object ${id[0]}`, path: [id.endsWith("1") ? "password" : "notes"], kind: "field", device: "Generated other device", local: { present: true, value: reveal ? testData.entryPassword : "••••••••" }, remote: { present: true, value: reveal ? testData.entryPassword + "-remote" : "••••••••" } })) };
}
const local = (page: Page) => page.getByRole("radio", { name: /^Keep this computer/ });
async function expectRedacted(page: Page) {
  expect(await page.locator("body").evaluate((node, secret) => node.textContent?.includes(secret), testData.entryPassword)).toBe(false);
}

test("conflict choices survive reveal, hide, timer, blur, collapse and object changes; apply only visible object", async ({ page }) => {
  await start(page); const state = await conflicts(page); await page.clock.install();
  await local(page).first().check();
  await button(page, "Reveal conflict values").click();
  await expect(button(page, "Hide conflict values")).toBeVisible();
  await expect(local(page).first()).toBeChecked();
  await button(page, "Hide conflict values").click(); await expectRedacted(page);
  await expect(local(page).first()).toBeChecked();
  await button(page, "Reveal conflict values").click(); await expect(button(page, "Hide conflict values")).toBeVisible();
  await page.clock.fastForward(45_001); await expectRedacted(page); await expect(local(page).first()).toBeChecked();
  await button(page, "Reveal conflict values").click(); await expect(button(page, "Hide conflict values")).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event("blur"))); await expectRedacted(page);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.getByLabel("Entry to review").selectOption("b"); await local(page).first().check();
  await page.getByLabel("Entry to review").selectOption("a"); await expect(local(page).first()).toBeChecked();
  await button(page, "Reveal conflict values").click(); await expect(button(page, "Hide conflict values")).toBeVisible();
  await button(page, "Close conflict review").click(); await expectRedacted(page);
  await guarded(page, "Passwords");
  await button(page, "Review computer sync conflicts").click(); await expect(local(page).first()).toBeChecked();
  await local(page).last().check();
  let submitted: Record<string, string> = {};
  await page.route(url => url.pathname === "/personal-sync/resolve", async route => { submitted = route.request().postDataJSON().choices; state.generation++; await json(route, {}); });
  await button(page, "Confirm selected values").click(); await page.getByRole("alertdialog").getByRole("button", { name: "Confirm", exact: true }).click();
  await expect.poll(() => Object.keys(submitted).sort()).toEqual(["a1", "a2"]);
  await expect(local(page).first()).not.toBeChecked();
});

test("hide immediately removes revealed values without depending on a masked API request", async ({ page }) => {
  await start(page); const state = await conflicts(page);
  await button(page, "Reveal conflict values").click(); await expect(button(page, "Hide conflict values")).toBeVisible();
  state.rejectMasked = true;
  await button(page, "Hide conflict values").click();
  await expectRedacted(page); expect(state.maskedRequests).toBe(1);
});

test("a reveal response arriving after blur cannot put plaintext back in the page", async ({ page }) => {
  await start(page); await conflicts(page);
  const reveal = await gate(page, "/personal-sync/conflicts", payload(4, true));
  try {
    await button(page, "Reveal conflict values").click(); await reveal.ready;
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    const response = page.waitForResponse(value => value.url().includes("/personal-sync/conflicts?reveal=true"));
    reveal.release(); await response;
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expectRedacted(page);
  } finally { reveal.release(); }
});


test("computer settings and setup independently guard navigation", async ({ page }) => {
  await start(page);
  await button(page, "Connections").click();
  await button(page, "Set up computer sync").click();
  await page.getByLabel("This computer's name", { exact: true }).fill("Generated new device");
  await guarded(page, "Settings"); await guarded(page, "Lock now");
  await button(page, "Cancel setup").click();
  await button(page, "Passwords").click();
  await page.route(url => url.pathname === "/personal-sync/status", route => json(route, { connected: true, generation: 1, label: "Generated device", automatic: false, devices: [] }));
  await button(page, "Connections").click();
  await page.getByLabel("This computer's name", { exact: true }).fill("Generated changed device");
  await guarded(page, "Passwords"); await guarded(page, "Lock now");
});

test("delayed connection success after automatic lock cannot publish a stale toast", async ({ page }) => {
  await start(page); await setupService(page);
  const save = await gate(page, "/integrations/bitwarden", { source: "bitwarden", label: "Bitwarden", configured: true, cli_installed: true, fields: [{ key: "server_url", secret: false, value: "https://generated.example.invalid" }] });
  try {
    await button(page, "Save configuration").click(); await save.ready;
    await page.evaluate(() => window.dispatchEvent(new CustomEvent("vault-personal-settings-changed", { detail: { lock_after_seconds: 1 } })));
    await expect(page.getByLabel("Master password", { exact: true })).toBeVisible();
    const observer = await page.evaluateHandle(() => {
      const result = { count: 0, observer: null as MutationObserver | null };
      result.observer = new MutationObserver(records => { for (const record of records) for (const node of record.addedNodes) if (node instanceof Element && (node.matches(".toast") || node.querySelector(".toast"))) result.count++; });
      result.observer.observe(document.body, { childList: true, subtree: true }); return result;
    });
    const response = page.waitForResponse(value => value.url().endsWith("/integrations/bitwarden"));
    save.release(); await response;
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    expect(await observer.evaluate(value => { value.observer?.disconnect(); return value.count; })).toBe(0);
    await observer.dispose();
  } finally { save.release(); }
});

test("connection code response arriving after blur stays concealed", async ({ page }) => {
  await start(page); await conflicts(page);
  await page.getByText("Connect another computer and view devices", { exact: true }).click();
  const reveal = await gate(page, "/personal-sync/code", { code: testData.entryPassword });
  try {
    await button(page, "Reveal connection code").click(); await reveal.ready;
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    const response = page.waitForResponse(value => value.url().endsWith("/personal-sync/code"));
    reveal.release(); await response;
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    expect(await page.getByLabel("Sync connection code", { exact: true }).count()).toBe(0);
  } finally { reveal.release(); }
});

for (const operation of ["generation", "QR import"] as const) test(`${operation} finishes the draft before Save can start`, async ({ page }) => {
  const sidecar = await start(page);
  await button(page, "Add password").click();
  await page.getByLabel("Website or app name", { exact: true }).fill(`Generated ${operation} gate`);
  const work = await gate(page, operation === "generation" ? "/entries/tools/generate" : "/entries/tools/totp/preview", operation === "generation" ? { password: testData.entryPassword } : { valid: true, code: "123456", remaining_seconds: 30, period: 30 });
  try {
    if (operation === "generation") await button(page, "Generate password").click();
    else {
      await button(page, "More options").click();
      await page.getByLabel("Choose authenticator QR image", { exact: true }).setInputFiles("tests/ui/fixtures/totp-rfc-test.png");
    }
    await work.ready;
    await expect(button(page, "Save")).toBeDisabled();
    // Programmatic submit also exercises handleSave's defensive guard.
    await page.locator(".entry-editor-card form").evaluate(form => (form as HTMLFormElement).requestSubmit());
    expect(sidecar.writes.create).toBe(0);
    work.release();
    await expect(button(page, "Save")).toBeEnabled();
    if (operation === "generation") expect(await page.getByLabel("Password", { exact: true }).inputValue() === testData.entryPassword).toBe(true);
    else await expect(page.getByLabel("Authenticator key (TOTP key)", { exact: true })).toHaveValue(/^otpauth:\/\/totp\/RFC/);
    await button(page, "Save").click();
    await expect.poll(() => sidecar.writes.create).toBe(1);
    if (operation === "generation") expect(sidecar.persistedEntries[0].password === testData.entryPassword).toBe(true);
    else expect(sidecar.persistedEntries[0].totp_secret.startsWith("otpauth://totp/RFC")).toBe(true);
  } finally { work.release(); }
});
