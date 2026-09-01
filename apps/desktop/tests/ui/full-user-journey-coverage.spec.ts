import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

async function createVault(page: Page, locale: "en" | "zh" = "en") {
  await page.addInitScript((selectedLocale) => {
    localStorage.setItem("vault_locale", selectedLocale);
  }, locale);
  await page.goto("/");
  const passwordLabel = locale === "zh" ? "主密码" : "Master password";
  const confirmationLabel = locale === "zh" ? "再次输入主密码" : "Confirm master password";
  const createLabel = locale === "zh" ? "创建并解锁" : "Create and unlock";
  await page.getByLabel(passwordLabel, { exact: true }).fill(testData.masterPassword);
  await page.getByLabel(confirmationLabel, { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: createLabel, exact: true }).click();
  await expect(page.getByRole("navigation")).toBeVisible();
}

async function openSyncDetails(page: Page) {
  await page.getByRole("button", { name: "Connections", exact: true }).click();
  await page.getByRole("button", { name: "Review sync details", exact: true }).click();
  await page.getByRole("button", { name: "Preview bidirectional sync", exact: true }).click();
}

test("one-entry path copies, auto-hides a reveal, edits, and searches", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1);
  await sidecar.install(page);
  await createVault(page);

  const row = page.getByRole("listitem").filter({ hasText: "Generated account 0001" });
  await row.getByRole("button", { name: "Copy password", exact: true }).click();
  await expect(page.getByText("Password copied to clipboard", { exact: true })).toBeVisible();
  expect(sidecar.copyWrites.password).toBe(1);

  await page.clock.install();
  await row.locator("summary").click();
  await row.getByRole("button", { name: "Show password", exact: true }).click();
  await expect(row.locator(".entry-password-preview")).toHaveText(testData.entryPassword);
  await page.clock.fastForward(30_100);
  await expect(row.locator(".entry-password-preview")).not.toHaveText(testData.entryPassword);

  await row.getByRole("button", { name: "Show password", exact: true }).click();
  await expect(row.locator(".entry-password-preview")).toHaveText(testData.entryPassword);
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(row.locator(".entry-password-preview")).not.toHaveText(testData.entryPassword);

  await row.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Website or app name", { exact: true }).fill("Generated account edited");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Generated account edited", { exact: true })).toBeVisible();
  expect(sidecar.writes.update).toBe(1);

  await page.getByLabel("Search vault").fill("account edited");
  await expect(page.getByRole("button", { name: "Open Generated account edited", exact: true })).toBeVisible();
});

test("100-entry search rejects stale results and recovers from timeout and disconnection", async ({ page }) => {
  test.info().annotations.push({ type: "expected-request-failures", description: "2" });
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 100);
  sidecar.setEntryListBehavior("person-0001@example.invalid", { delayMs: 900 });
  sidecar.setEntryListBehavior("generated-timeout", {
    status: 504,
    detail: `Generated API timeout: ${"retry after reconnecting ".repeat(12)}`,
  });
  sidecar.setEntryListBehavior("generated-offline", { abort: true });
  await sidecar.install(page);
  await createVault(page);
  await expect(page.getByRole("list", { name: "Vault entries" }).getByRole("listitem")).toHaveCount(100);

  const search = page.getByLabel("Search vault");
  const slowRequest = page.waitForRequest((request) =>
    new URL(request.url()).searchParams.get("q") === "person-0001@example.invalid",
  );
  await search.fill("person-0001@example.invalid");
  await slowRequest;
  await search.fill("person-0100@example.invalid");
  await expect(page.getByRole("button", { name: "Open Generated account 0100", exact: true })).toBeVisible();
  await page.waitForTimeout(1_000);
  await expect(page.getByRole("button", { name: "Open Generated account 0001", exact: true })).toHaveCount(0);

  await search.fill("generated-timeout");
  await expect(page.getByRole("alert").filter({ hasText: "Generated API timeout" })).toBeVisible();
  await search.fill("generated-offline");
  await expect(page.getByRole("alert").filter({ hasText: "Failed to fetch" })).toBeVisible();

  await search.fill("person-0050@example.invalid");
  await expect(page.getByRole("button", { name: "Open Generated account 0050", exact: true })).toBeVisible();
});

test("Chinese novice path handles long text, emoji, reduced motion, forced colors, and 1000 by 700", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.setViewportSize({ width: 1000, height: 700 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await createVault(page, "zh");

  const longTitle = `中文账户🚀${"很长的名称".repeat(14)}`;
  const longUsername = `${"长用户名".repeat(18)}@example.invalid`;
  const longUrl = `https://example.invalid/${"very-long-generated-path/".repeat(10)}`;
  await page.getByRole("button", { name: "添加密码", exact: true }).click();
  await page.getByLabel("网站或应用名称", { exact: true }).fill(longTitle);
  await page.getByLabel("用户名", { exact: true }).fill(longUsername);
  await page.getByLabel("密码", { exact: true }).fill(testData.entryPassword);
  await page.getByLabel("网站地址", { exact: true }).fill(longUrl);
  await page.getByLabel("备注", { exact: true }).fill("中文、emoji 🎉 和换行错误布局测试");
  await page.evaluate(() => { document.documentElement.style.zoom = "1.5"; });
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText(longTitle, { exact: true })).toBeVisible();

  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    accessibility.violations
      .filter((violation) => ["critical", "serious"].includes(violation.impact || ""))
      .map(({ id, impact, help }) => ({ id, impact, help })),
  ).toEqual([]);

  await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
  expect(await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
  expect(await page.evaluate(() => window.matchMedia("(forced-colors: active)").matches)).toBe(true);
  await expect(page.getByRole("button", { name: "立即锁定", exact: true })).toBeVisible();
});

test("keyboard focus traps, wraps, escapes, and returns to the destructive trigger", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1);
  await sidecar.install(page);
  await page.setViewportSize({ width: 800, height: 600 });
  await createVault(page);

  const row = page.getByRole("listitem").filter({ hasText: "Generated account 0001" });
  const more = row.locator("summary");
  await more.focus();
  await page.keyboard.press("Space");
  const deleteButton = row.getByRole("button", { name: "Delete", exact: true });
  await expect(deleteButton).toBeVisible();
  await deleteButton.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("alertdialog", { name: "Delete entry" });
  const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
  const confirm = dialog.getByRole("button", { name: "Delete", exact: true });
  await expect(cancel).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(confirm).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(cancel).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(deleteButton).toBeFocused();
  expect(sidecar.writes.delete).toBe(0);
});

test("restore failure keeps the active vault unchanged and unlocked", async ({ page }) => {
  test.info().annotations.push({ type: "expected-request-failures", description: "1" });
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1, {
    restoreApplyFailure: true,
  });
  await sidecar.install(page);
  await createVault(page);
  const before = sidecar.persistedEntries;

  await page.getByRole("button", { name: "Security & recovery", exact: true }).click();
  const backupCenter = page.getByLabel("Manual backup and restore");
  await backupCenter.getByRole("button", { name: "Enter path manually (advanced)", exact: true }).click();
  await backupCenter.getByLabel("Folder for this manual backup (does not enable automatic backups)").fill(
    `C:\\isolated-vault-tests\\${testData.runId}\\${"generated-long-folder\\".repeat(10)}`,
  );
  await backupCenter.getByRole("button", { name: "Create encrypted backup now", exact: true }).click();
  await page.getByRole("button", { name: "Manage backup history", exact: true }).click();
  await page.getByRole("button", { name: "Preview restore impact", exact: true }).click();
  const dialog = page.getByRole("alertdialog", { name: "Restore this backup" });
  await dialog.getByRole("button", { name: "Restore this backup", exact: true }).click();

  await expect(
    backupCenter.getByRole("alert").filter({ hasText: "active vault is unchanged" }),
  ).toBeVisible();
  expect(sidecar.backupWrites.restore).toBe(0);
  expect(sidecar.persistedEntries).toEqual(before);
  await page.getByRole("button", { name: "Passwords", exact: true }).click();
  await expect(page.getByText("Generated account 0001", { exact: true })).toBeVisible();
});

test("stale sync execution is rejected and unavailable sources remain explicit", async ({ page }) => {
  test.info().annotations.push({ type: "expected-request-failures", description: "1" });
  const staleSidecar = new MockAuthenticatedSidecar(900, 0, "stale");
  await staleSidecar.install(page);
  await createVault(page);
  await openSyncDetails(page);
  await page.getByLabel("I reviewed these 1 deletion operations").check();
  await page.getByRole("button", { name: "Confirm and execute", exact: true }).click();
  await expect(
    page.getByLabel("Sync status").getByRole("alert").filter({ hasText: "preview expired or state changed" }),
  ).toBeVisible();
  expect(staleSidecar.syncWrites.execute).toBe(0);
  await expect(page.getByRole("heading", { name: "Sync plan awaiting confirmation" })).toHaveCount(0);

  await page.reload();
  const unavailableSidecar = new MockAuthenticatedSidecar(900, 0, "unavailable");
  await unavailableSidecar.install(page);
  await createVault(page);
  await openSyncDetails(page);
  await expect(page.getByText("Generated source is temporarily unavailable", { exact: true })).toBeVisible();
  await expect(page.getByText("KeePassXC", { exact: true })).toBeVisible();
  await expect(page.locator(".result-panel")).toContainText("Unavailable sources: 1");
  await expect(page.getByRole("alert")).toContainText("could not be checked");
  expect(unavailableSidecar.syncWrites.execute).toBe(0);
});
