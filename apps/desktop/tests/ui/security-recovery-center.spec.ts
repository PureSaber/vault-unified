import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
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
  await expect(status).toContainText("Automatic-backup locationNot set");
  await expect(status).toContainText("Next automatic backupNot enabled");
  await expect(page.getByText("Settings are saved; automatic backups are currently off.")).toBeVisible();
  const oneTimeBackup = page.getByLabel("One-time backup and restore");
  await expect(oneTimeBackup).toBeVisible();
  await expect(oneTimeBackup).toContainText("without remembering this temporary folder or enabling the automatic schedule above");

  await page.getByLabel("Create encrypted backups while the app is unlocked").check();
  await page.getByRole("button", { name: "Enter path manually (advanced)" }).first().click();
  await page.getByLabel("Automatic-backup folder").fill(`C:\\isolated-vault-tests\\${testData.runId}\\safe-backups`);
  await expect(page.getByText("Changes not saved")).toBeVisible();
  await expect(page.getByRole("button", { name: "Back up to this folder now" })).toBeDisabled();
  await page.getByRole("button", { name: "Test automatic-backup location" }).click();
  await expect(page.getByText(/Writable, free space/)).toBeVisible();
  await page.getByRole("button", { name: "Save auto-lock and automatic-backup settings" }).click();
  await expect(page.getByText("Automatic-backup settings are saved and enabled.")).toBeVisible();
  await expect(status).toContainText(`Automatic-backup locationC:\\isolated-vault-tests\\${testData.runId}\\safe-backups`);
  await expect(status).not.toContainText("Next automatic backupNot enabled");

  await page.getByRole("button", { name: "Back up to this folder now" }).click();
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

test("offers emergency recovery before authentication and preserves the in-app handoff", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);

  await page.getByRole("button", { name: "Lock now", exact: true }).click();
  const recoveryEntry = page.getByRole("button", { name: "Use emergency recovery kit", exact: true });
  await expect(recoveryEntry).toHaveCount(1);
  await recoveryEntry.click();
  await expect(page.getByRole("heading", { name: "Recover from an emergency kit", exact: true })).toBeVisible();
  await expect(page.locator("#recovery-kit-path-label")).toHaveText("Recovery-kit file path");
  await expect(page.getByRole("button", { name: "Choose file", exact: true })).toBeVisible();
  await expect(page.getByLabel("Recovery code", { exact: true })).toHaveAttribute("type", "password");
  await expect(page.getByLabel("New master password", { exact: true })).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Back", exact: true }).click();

  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await page.getByRole("button", { name: "Security & recovery", exact: true }).click();
  await page.getByRole("button", { name: "Restore from recovery kit", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Recover from an emergency kit", exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/#recovery-kit$/);
  await expect(page.locator("#recovery-kit-path-label")).toHaveText("Recovery-kit file path");
  await expect(page.getByRole("button", { name: "Choose file", exact: true })).toBeVisible();
});
