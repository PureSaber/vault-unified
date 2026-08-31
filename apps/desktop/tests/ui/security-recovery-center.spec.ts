import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

async function createVault(page: import("@playwright/test").Page) {
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  await page.goto("/");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();
  await expect(page.getByRole("button", { name: "Security & recovery", exact: true })).toBeVisible();
}

test("shows conclusions first and completes backup verification with a cancellable restore preview", async ({ page }, testInfo) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);
  await page.getByRole("button", { name: "Security & recovery", exact: true }).click();

  const status = page.getByRole("heading", { name: "Current protection status" }).locator("..");
  await expect(status).toContainText("VaultEncrypted");
  await expect(status).toContainText("Auto-lock15 minutes");
  await expect(status).toContainText("Last successful backupNo backup yet");
  await expect(status).toContainText("Latest backup errorNone");
  await expect(status).toContainText("Recovery kitNot created");

  await page.getByLabel("Create encrypted backups while the app is unlocked").check();
  await page.getByRole("button", { name: "Enter path manually (advanced)" }).first().click();
  await page.getByLabel("Backup folder").fill(`C:\\isolated-vault-tests\\${testData.runId}\\safe-backups`);
  await page.getByRole("button", { name: "Save personal settings" }).click();
  await page.getByRole("button", { name: "Test backup location" }).click();
  await expect(page.getByText(/Writable, free space/)).toBeVisible();

  await page.getByRole("button", { name: "Back up now" }).click();
  await expect(status).not.toContainText("No backup yet");
  expect(sidecar.backupWrites.create).toBe(1);

  await page.getByRole("button", { name: "Verify latest backup" }).click();
  await expect(status).toContainText("Latest backup verificationPassed");

  await page.getByRole("button", { name: "Manage backup history" }).click();
  await expect(page.getByText("b".repeat(64), { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Preview restore impact" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Restore this backup" });
  await expect(dialog).toContainText("VaultUnified-generated.vault");
  await expect(dialog).toContainText("v3");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  expect(sidecar.backupWrites.restore).toBe(0);
  await expect(page.getByRole("heading", { name: "Security & recovery" })).toBeVisible();

  await expect(page.getByRole("button", { name: "Restore from recovery kit" })).toBeVisible();
  await expect(page.getByText(/Plaintext export is a short-lived migration file, not a backup/)).toBeVisible();
  const ids = await page.locator("[id]").evaluateAll((elements) => elements.map((element) => element.id));
  expect(new Set(ids).size).toBe(ids.length);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter((item) => ["critical", "serious"].includes(item.impact || ""))).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("security-recovery-center.png"), fullPage: true });
});
