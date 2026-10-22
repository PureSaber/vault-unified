import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

test("duplicate review cancels without writes and merges chosen fields into a recoverable result", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("Confirm master password").fill(testData.masterPassword);
    await page.getByRole("button", { name: "Create and unlock", exact: true }).click();
    for (const [title, password] of [["Generated duplicate A", testData.entryPassword], ["Generated duplicate B", testData.masterPassword]]) {
      await page.getByRole("button", { name: "Add password", exact: true }).click();
      await page.getByLabel("Website or app name", { exact: true }).fill(title);
      await page.getByLabel("Username", { exact: true }).fill("generated-user");
      await page.getByLabel("Password", { exact: true }).fill(password);
      await page.getByLabel("Website address", { exact: true }).fill("https://merge.example.invalid/login");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByRole("button", { name: `Open ${title}`, exact: true })).toBeVisible();
    }
    await page.getByText("Filters and bulk organization", { exact: true }).click();
    await page.getByLabel("Duplicates only", { exact: true }).check();
    await expect(page.getByRole("button", { name: "Open Generated duplicate B", exact: true })).toBeVisible();
    // Wait for the duplicate filter request before selecting its result.
    await expect(page.getByRole("button", { name: "Compare and merge", exact: true })).toBeDisabled();
    await page.getByLabel("Select Generated duplicate A", { exact: true }).check();
    await page.getByLabel("Select Generated duplicate B", { exact: true }).check();
    await page.getByRole("button", { name: "Compare and merge", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Compare and merge accounts" });
    await expect(dialog.getByRole("button", { name: "Preview merge", exact: true })).toBeEnabled();
    expect((await dialog.innerText()).includes(testData.entryPassword)).toBe(false);
    const quality = await new AxeBuilder({ page }).analyze();
    expect(quality.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await dialog.screenshot({ path: testInfo.outputPath("duplicate-merge-generated.png") });
    await dialog.getByRole("button", { name: "Preview merge", exact: true }).click();
    await expect(dialog.getByText("2 saved versions and 0 attachments will be retained.")).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("button", { name: "Open Generated duplicate B", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Compare and merge", exact: true }).click();
    await dialog.getByRole("group", { name: "Password", exact: true }).getByRole("radio", { name: "2. Generated duplicate B", exact: true }).check();
    await dialog.getByRole("button", { name: "Preview merge", exact: true }).click();
    await dialog.getByRole("button", { name: "Confirm merge", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await page.getByLabel("Duplicates only", { exact: true }).uncheck();
    await page.getByRole("button", { name: "Open Generated duplicate A", exact: true }).click();
    await page.getByRole("article").getByRole("button", { name: "Edit", exact: true }).click();
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue(testData.masterPassword);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByLabel("Entry location", { exact: true }).selectOption("trash");
    await expect(page.getByRole("button", { name: "Open Generated duplicate B", exact: true })).toBeVisible();
  } finally { await sidecar.stop(); }
});
