import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

async function createVault(page: Parameters<MockAuthenticatedSidecar["install"]>[0]) {
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  await page.goto("/");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();
  await expect(page.getByLabel("Search vault")).toBeVisible();
}

test("lists deletion items, requires review, and cancel performs zero writes", async ({ page }, testInfo) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "deletion");
  await sidecar.install(page);
  await createVault(page);

  await page.getByRole("button", { name: "Sync", exact: true }).click();
  await page.getByRole("button", { name: "Preview bidirectional sync" }).click();

  await expect(page.getByText("Generated deletion review", { exact: true })).toBeVisible();
  await expect(page.getByText("Will be deleted from Bitwarden", { exact: true })).toBeVisible();
  await expect(page.getByText("g***@example.invalid", { exact: false })).toBeVisible();
  await expect(page.getByText("sync.example.invalid", { exact: false })).toBeVisible();
  const execute = page.getByRole("button", { name: "Confirm and execute" });
  await expect(execute).toBeDisabled();
  expect(sidecar.syncWrites.execute).toBe(0);
  expect(await page.locator("body").innerText()).not.toContain(testData.entryPassword);

  await testInfo.attach("generated-sync-deletion-preview", {
    body: await page.locator("#sync-preview-heading").locator("..").screenshot(),
    contentType: "image/png",
  });

  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByText("Generated deletion review", { exact: true })).toHaveCount(0);
  expect(sidecar.syncWrites.execute).toBe(0);

  await page.getByRole("button", { name: "Preview bidirectional sync" }).click();
  await page.getByLabel("I reviewed these 1 deletion operations").check();
  await expect(execute).toBeEnabled();

  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    accessibility.violations
      .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
      .map(({ id, impact, help, nodes }) => ({
        id,
        impact,
        help,
        targets: nodes.map((node) => node.target),
      })),
  ).toEqual([]);

  await execute.click();
  await expect(page.getByText("Generated deletion review", { exact: true })).toBeVisible();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible();
  expect(sidecar.syncWrites.execute).toBe(1);
  expect(await page.locator("body").innerText()).not.toContain(testData.entryPassword);
});
