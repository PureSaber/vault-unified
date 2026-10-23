import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { startGeneratedSidecar } from "./live-sidecar";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

async function createVault(page: Page) {
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  const created = page.waitForResponse(response => response.url().endsWith("/auth/create"));
  await page.getByRole("button", { name: "Create and unlock", exact: true }).click();
  return (await (await created).json()).token as string;
}

test("read-only details show template metadata, recovery codes and plain custom fields from the real API", async ({ page }) => {
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    const token = await createVault(page);
    const headers = { "X-Vault-Bootstrap": testData.bootstrapSecret, "X-Vault-Client": "vault-unified-desktop", Authorization: `Bearer ${token}` };
    const commit = async (fields: Record<string, unknown>) => {
      const response = await page.request.post(`${sidecar.apiUrl}/entries/commit`, { headers, data: {
        transaction_id: randomUUID(), entry_id: null, expected_updated_at: null, username: "", password: "", url: "", notes: "", tags: [],
        template_data: {}, website_rules: { match: "exact", additional_urls: [], excluded_urls: [] }, custom_fields: [], totp_secret: "",
        add_attachments: [], remove_attachment_ids: [], restore_history_id: null, ...fields,
      } });
      expect(response.ok()).toBe(true);
    };
    const firstCode = `${testData.entryPassword}-first-code`;
    const hiddenValue = `${testData.entryPassword}-hidden-field`;
    await commit({ title: "Generated recovery codes", entry_type: "recovery_code", template_data: { recovery_codes: [
      { id: "generated-one", value: firstCode, used_at: "" },
      { id: "generated-two", value: `${testData.entryPassword}-second-code`, used_at: "2026-10-20T10:00:00+00:00" },
    ] } });
    await commit({ title: "Generated license", entry_type: "software_license", password: testData.entryPassword, template_data: { registered_to: "Generated Owner", expires_on: "2030-01-31" } });
    await commit({ title: "Generated custom login", entry_type: "login", username: "generated-user", password: testData.entryPassword, custom_fields: [
      { label: "Generated plain", value: "generated-visible-value", concealed: false },
      { label: "Generated hidden", value: hiddenValue, concealed: true },
    ] });
    await page.evaluate(() => window.dispatchEvent(new Event("vault-entries-changed")));
    await sidecar.drain();
    const detail = page.getByRole("article", { name: "Account details" });

    await page.getByRole("button", { name: "View recovery codes", exact: true }).click();
    const codes = detail.getByRole("region", { name: "Recovery codes" });
    await expect(codes.locator(".recovery-code-row")).toHaveCount(2);
    await expect(codes.locator(".recovery-code-row").nth(1)).toContainText("Used");
    await expect(page.locator("body")).not.toContainText(testData.entryPassword);
    await codes.getByRole("button", { name: "Show recovery code 1", exact: true }).click();
    await expect(codes.locator(".recovery-code-row").first().locator(".secret-value")).toHaveText(firstCode);
    await expect(page.locator("body")).not.toContainText(`${testData.entryPassword}-second-code`);
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    await expect(page.locator("body")).not.toContainText(testData.entryPassword);

    await page.getByRole("button", { name: "Open Generated license", exact: true }).click();
    await expect(detail.getByRole("heading", { name: "Generated license" })).toBeVisible();
    await expect(detail.locator("dl").filter({ hasText: "Registered to" })).toContainText("Generated Owner");
    await expect(detail.locator("dl").filter({ hasText: "Expiry date" })).toContainText("2030-01-31");
    await expect(page.locator("body")).not.toContainText(testData.entryPassword);

    await page.getByRole("button", { name: "Open Generated custom login", exact: true }).click();
    await expect(detail.getByRole("heading", { name: "Generated custom login" })).toBeVisible();
    await expect(detail.locator(".detail-fields > div").filter({ hasText: "Generated plain" }).locator("dd")).toHaveText("generated-visible-value");
    await expect(page.locator("body")).not.toContainText(hiddenValue);
    await detail.getByRole("button", { name: "Show Generated hidden", exact: true }).click();
    await expect(detail.getByText(hiddenValue, { exact: true })).toBeVisible();
    const axe = await new AxeBuilder({ page }).analyze();
    expect(axe.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await page.getByRole("button", { name: "Lock now", exact: true }).click();
    await expect(page.locator("body")).not.toContainText(testData.entryPassword);
  } finally { await sidecar.stop(); }
});

test("only a user-created backup clears the reminder; per-write copies do not (real API)", async ({ page }) => {
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    const token = await createVault(page);
    const headers = { "X-Vault-Bootstrap": testData.bootstrapSecret, "X-Vault-Client": "vault-unified-desktop", Authorization: `Bearer ${token}` };
    const reminder = page.getByText("Backup has not been set up.", { exact: false });
    await expect(reminder).toBeVisible();
    // The reminder text never changes, so wait for the reload it triggers to land.
    const refresh = async () => {
      const settings = page.waitForResponse(response => response.url().endsWith("/personal/settings") && response.ok());
      await page.evaluate(() => window.dispatchEvent(new Event("vault-security-status-changed")));
      await settings;
    };

    await page.getByRole("button", { name: "Add password", exact: true }).click();
    await page.getByLabel("Website or app name", { exact: true }).fill("Generated backup subject");
    await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("button", { name: "Open Generated backup subject", exact: true })).toBeVisible();
    await sidecar.drain();
    const summary = await (await page.request.get(`${sidecar.apiUrl}/backups`, { headers })).json();
    // The precondition that hid the reminder before: the summary reports a time from an atomic copy.
    expect(summary.backups.map((record: { kind: string }) => record.kind)).toContain("local_atomic");
    expect(summary.health.last_success_at).not.toBe("");
    await refresh(); await sidecar.drain();
    await expect(reminder).toBeVisible();

    // A user-started backup (the "Create encrypted backup now" action) to its default folder.
    const created = await page.request.post(`${sidecar.apiUrl}/backups/create`, { headers, data: {} });
    expect(created.ok()).toBe(true);
    await refresh(); await sidecar.drain();
    await expect(reminder).toHaveCount(0);
  } finally { await sidecar.stop(); }
});

async function addAccounts(page: Page, names: string[]) {
  for (const name of names) {
    await page.getByRole("button", { name: "Add password", exact: true }).click();
    await page.getByLabel("Website or app name", { exact: true }).fill(name);
    await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("button", { name: `Open ${name}`, exact: true })).toBeVisible();
  }
}

test("bulk selection survives refreshes but keeps only rows that stay visible (real API)", async ({ page }) => {
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    await createVault(page);
    await addAccounts(page, ["Generated keep A", "Generated keep B"]);
    await sidecar.drain();
    const first = page.getByLabel("Select Generated keep A", { exact: true });
    const second = page.getByLabel("Select Generated keep B", { exact: true });
    await first.check(); await second.check();
    const reloaded = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/entries") && response.ok());
    await page.evaluate(() => window.dispatchEvent(new Event("vault-entries-changed")));
    await reloaded; await sidecar.drain();
    await expect(first).toBeChecked();
    await expect(second).toBeChecked();
    // A search that hides a row removes it from what a bulk action would touch.
    await page.getByLabel("Search vault").fill("keep A");
    await expect(second).toHaveCount(0);
    await page.getByLabel("Search vault").fill("");
    await expect(second).toBeVisible();
    await expect(second).not.toBeChecked();
    await expect(first).toBeChecked();
    // Unfavoriting under "Favorites only" hides the row but keeps it in the server list.
    const row = page.locator(".entry-row").filter({ hasText: "Generated keep A" });
    await row.locator("summary").click();
    await row.getByRole("button", { name: "Favorite", exact: true }).click();
    await expect(row.getByLabel("Favorite", { exact: true })).toBeVisible();
    await page.getByRole("group", { name: "Filters and bulk organization" }).locator("summary").click();
    await page.getByLabel("Favorites only", { exact: true }).check();
    await row.locator("summary").click();
    await row.getByRole("button", { name: "Unfavorite", exact: true }).click();
    await expect(first).toHaveCount(0);
    await sidecar.drain();
    await page.getByLabel("Favorites only", { exact: true }).uncheck();
    await expect(first).toBeVisible();
    await expect(first).not.toBeChecked();
    await expect(page.getByRole("button", { name: "Select current list", exact: true })).toBeVisible();
  } finally { await sidecar.stop(); }
});

test("details reflect a custom field added in the editor without reselecting (real API)", async ({ page }) => {
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    await createVault(page);
    await page.getByRole("button", { name: "Add password", exact: true }).click();
    await page.getByLabel("Website or app name", { exact: true }).fill("Generated field later");
    await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: "Open Generated field later", exact: true }).click();
    const detail = page.getByRole("article", { name: "Account details" });
    await detail.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByRole("button", { name: "More options", exact: true }).click();
    await page.getByRole("button", { name: "Add custom field", exact: true }).click();
    await page.getByLabel("Field name", { exact: true }).fill("Generated added field");
    await page.getByLabel("Field content", { exact: true }).fill("generated-added-value");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(detail.getByRole("heading", { name: "Generated field later" })).toBeVisible();
    await expect(detail.locator(".detail-fields > div").filter({ hasText: "Generated added field" }).locator("dd")).toHaveText("generated-added-value");
    await sidecar.drain();
  } finally { await sidecar.stop(); }
});

test("sharing never preselects a stale or substituted account", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 3);
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  await page.route("http://127.0.0.1:43129/sharing/status", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ service: "", identity: "", shares: [], families: [], outbox: [] }) });
  });
  await page.goto("/");
  await createVault(page);
  await page.getByRole("button", { name: "Open Generated account 0002", exact: true }).click();
  await page.getByRole("article", { name: "Account details" }).getByRole("button", { name: "Share…", exact: true }).click();
  const account = page.getByRole("combobox", { name: "Personal account", exact: true });
  const chosen = () => account.evaluate(select => (select as HTMLSelectElement).selectedOptions[0]?.textContent || "");
  await expect.poll(chosen).toBe("Generated account 0002");
  await page.locator("nav.nav").getByRole("button", { name: "Passwords", exact: true }).click();
  await page.locator("nav.nav").getByRole("button", { name: "Sharing", exact: true }).click();
  await expect.poll(chosen).not.toBe("");
  expect(await chosen()).not.toBe("Generated account 0002");
});

test("a delayed reveal is discarded when the selection changes or the vault locks", async ({ page }) => {
  // The reveal held across "Lock now" completes with the revoked token's 401.
  test.info().annotations.push({ type: "expected-request-failures", description: "1" });
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 2);
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  await page.goto("/");
  await createVault(page);
  const detail = page.getByRole("article", { name: "Account details" });
  const hold = async () => {
    let release: () => void = () => {};
    let received = false;
    const held = new Promise<void>(resolve => { release = resolve; });
    await page.route("**/entries/*?reveal=true", async route => {
      if (route.request().method() !== "GET") return route.fallback();
      received = true; await held; await route.fallback();
    });
    return { release: () => release(), received: () => received };
  };
  await page.getByRole("button", { name: "Open Generated account 0001", exact: true }).click();
  let gate = await hold();
  await detail.getByRole("button", { name: "Show password", exact: true }).click();
  await expect.poll(gate.received).toBe(true);
  await page.getByRole("button", { name: "Open Generated account 0002", exact: true }).click();
  await expect(detail.getByRole("heading", { name: "Generated account 0002" })).toBeVisible();
  gate.release(); await page.unroute("**/entries/*?reveal=true");
  await expect(detail.locator(".secret-value")).toHaveText("••••••••••••");
  expect((await page.locator("body").textContent())?.includes(testData.entryPassword)).toBe(false);

  gate = await hold();
  await detail.getByRole("button", { name: "Show password", exact: true }).click();
  await expect.poll(gate.received).toBe(true);
  await page.getByRole("button", { name: "Lock now", exact: true }).click();
  await expect(detail).toHaveCount(0);
  gate.release(); await page.unroute("**/entries/*?reveal=true");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByRole("button", { name: "Open Generated account 0001", exact: true })).toBeVisible();
  expect((await page.locator("body").textContent())?.includes(testData.entryPassword)).toBe(false);
});
