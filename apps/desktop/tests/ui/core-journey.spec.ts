import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test("creates, unlocks, edits a draft, searches, cancels, and locks", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Get started with Vault Unified" })).toBeVisible();

  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();
  await expect(page.getByLabel("Search vault")).toBeVisible();

  await page.getByRole("button", { name: "Lock now", exact: true }).click();
  await expect(page.getByRole("button", { name: "Unlock", exact: true })).toBeVisible();
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByLabel("Search vault")).toBeVisible();

  const accountTitle = `Generated account ${testData.runId.slice(0, 8)}`;
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Website or app name", { exact: true }).fill(accountTitle);
  await page.getByLabel("Username", { exact: true }).fill("beginner@example.invalid");
  await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
  await page.getByLabel("Website address", { exact: true }).fill("https://example.invalid/login");
  await page.getByLabel("Notes", { exact: true }).fill("Generated UI journey data only");
  await page.getByRole("button", { name: "Save", exact: true }).click();

  await expect(page.getByText(accountTitle, { exact: true })).toBeVisible();
  expect(sidecar.writes).toEqual({ create: 1, update: 0, delete: 0 });

  const search = page.getByLabel("Search vault");
  await search.fill("beginner@example.invalid");
  await expect(page.getByText(accountTitle, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: `Open ${accountTitle}`, exact: true }).click();
  const titleField = page.getByLabel("Website or app name", { exact: true });
  await expect(titleField).toHaveValue(accountTitle);
  await titleField.fill(`${accountTitle} cancelled draft`);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("alertdialog", { name: "Discard unsaved changes?" })).toBeVisible();
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();

  await expect(page.getByText(accountTitle, { exact: true })).toBeVisible();
  await expect(page.getByText(`${accountTitle} cancelled draft`, { exact: true })).toHaveCount(0);
  expect(sidecar.writes).toEqual({ create: 1, update: 0, delete: 0 });
  expect(sidecar.persistedEntries).toHaveLength(1);
  expect(sidecar.persistedEntries[0].title).toBe(accountTitle);

  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const seriousOrCritical = accessibility.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(
    seriousOrCritical.map(({ id, impact, help }) => ({ id, impact, help })),
  ).toEqual([]);

  const browserStorage = await page.evaluate(() => ({
    local: Object.values(localStorage),
    session: Object.values(sessionStorage),
  }));
  expect(JSON.stringify(browserStorage)).not.toContain(testData.bearerToken);
  expect(JSON.stringify(browserStorage)).not.toContain(testData.bootstrapSecret);

  await page.getByRole("button", { name: "Lock now", exact: true }).click();
  await expect(page.getByRole("button", { name: "Unlock", exact: true })).toBeVisible();
});
