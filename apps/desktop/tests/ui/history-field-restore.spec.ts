import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

test("selective history restore keeps other current fields and saves one complete draft", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("Confirm master password").fill(testData.masterPassword);
    await page.getByRole("button", { name: "Create and unlock", exact: true }).click();
    await page.getByRole("button", { name: "Add password", exact: true }).click();
    await page.getByLabel("Website or app name", { exact: true }).fill("Generated old title");
    await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: "Open Generated old title", exact: true }).click();
    await page.getByRole("article").getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Website or app name", { exact: true }).fill("Generated new title");
    await page.getByLabel("Password", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: "Open Generated new title", exact: true }).click();
    await page.getByRole("article").getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByRole("button", { name: "More options", exact: true }).click();
    await page.getByRole("button", { name: "Preview in draft", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Compare and restore history fields" });
    await expect(dialog.getByLabel("Name", { exact: true })).toBeChecked();
    await expect(dialog.getByLabel("Password", { exact: true })).toBeChecked();
    expect((await dialog.innerText()).includes(testData.entryPassword)).toBe(false);
    expect((await dialog.innerText()).includes(testData.masterPassword)).toBe(false);
    await dialog.getByLabel("Name", { exact: true }).uncheck();
    const quality = await new AxeBuilder({ page }).analyze();
    expect(quality.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await dialog.screenshot({ path: testInfo.outputPath("history-field-selection.png") });
    await dialog.getByRole("button", { name: "Show Password", exact: true }).click();
    expect((await dialog.innerText()).includes(testData.entryPassword)).toBe(true);
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    expect((await dialog.innerText()).includes(testData.entryPassword)).toBe(false);
    await dialog.getByRole("button", { name: "Load draft", exact: true }).click();
    await expect(page.getByLabel("Website or app name", { exact: true })).toHaveValue("Generated new title");
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue(testData.entryPassword);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: "Open Generated new title", exact: true }).click();
    await page.getByRole("article").getByRole("button", { name: "Edit", exact: true }).click();
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue(testData.entryPassword);
    await page.getByRole("button", { name: "More options", exact: true }).click();
    await page.getByRole("button", { name: "Preview in draft", exact: true }).first().click();
    await expect(dialog.getByLabel("Password", { exact: true })).toBeChecked();
    await dialog.getByRole("button", { name: "Cancel", exact: true }).press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue(testData.entryPassword);
  } finally { await sidecar.stop(); }
});
