import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

test("import pagination retains choices across pages without writing before confirmation", async ({ page }) => {
  test.setTimeout(60_000);
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("Confirm master password").fill(testData.masterPassword);
    await page.getByRole("button", { name: "Create and unlock" }).click();
    await page.getByRole("button", { name: "Import from browser", exact: true }).click();
    await sidecar.drain();
    const digest = async () => createHash("sha256").update(await readFile(join(sidecar.directory, "generated.vault"))).digest("hex");
    const before = await digest();
    const rows = Array.from({ length: 101 }, (_, index) => `Generated paged ${index + 1},https://paged-${index + 1}.example.invalid,generated-user,${testData.entryPassword}`);
    await page.getByLabel("Choose browser CSV file").setInputFiles({ name: "generated-paged.csv", mimeType: "text/csv", buffer: Buffer.from(["name,url,username,password", ...rows].join("\r\n")) });
    await expect(page.locator(".import-item-list > li")).toHaveCount(100);
    await page.getByLabel("Import Generated paged 1", { exact: true }).uncheck();
    await page.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(page.locator(".import-item-list > li")).toHaveCount(1);
    await page.getByLabel("Import Generated paged 101", { exact: true }).uncheck();
    await page.getByRole("button", { name: "Previous page", exact: true }).click();
    await expect(page.getByLabel("Import Generated paged 1", { exact: true })).not.toBeChecked();
    await sidecar.drain(); expect(await digest() === before).toBe(true);
    await page.getByLabel("I reviewed additions, duplicates, and skip reasons").check();
    await page.getByRole("button", { name: "Confirm import", exact: true }).click();
    await expect(page.getByText("99 added, 0 updated, 2 skipped.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Done", exact: true }).click();
    await expect(page.locator(".entry-row")).toHaveCount(99);
    await expect(page.getByRole("button", { name: "Open Generated paged 1", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Open Generated paged 101", exact: true })).toHaveCount(0);
  } finally { await sidecar.stop(); }
});
