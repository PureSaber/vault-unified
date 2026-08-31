import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

const hiddenTechnicalTerms = [
  "Argon2id",
  "AES-GCM",
  "sidecar",
  "tombstone",
  "preview token",
  "dirty",
  "local_atomic",
  "Share ID",
];

async function expectTermsHidden(page: import("@playwright/test").Page) {
  const visibleText = await page.locator("body").innerText();
  for (const term of hiddenTechnicalTerms) {
    expect(visibleText, `default content exposed ${term}`).not.toContain(term);
  }
}

async function expectUniqueIds(page: import("@playwright/test").Page) {
  const duplicates = await page.locator("[id]").evaluateAll((elements) => {
    const ids = elements.map((element) => element.id);
    return ids.filter((id, index) => ids.indexOf(id) !== index);
  });
  expect(duplicates).toEqual([]);
}

test("keeps the beginner path compact and progressively reveals connection details", async ({ page }, testInfo) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Get started with Vault Unified" })).toBeVisible();
  await expectTermsHidden(page);

  await page.getByRole("button", { name: "Technical details", exact: true }).click();
  await expect(page.getByText(/Vault Format v3/)).toBeVisible();
  await expect(page.getByText(/Argon2id/)).toBeVisible();
  await page.getByRole("button", { name: "Hide technical details", exact: true }).click();

  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();

  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await expect(navigation.getByRole("button")).toHaveCount(5);
  for (const label of ["Passwords", "Security & recovery", "Connections", "Settings", "Lock now"]) {
    await expect(navigation.getByRole("button", { name: label, exact: true })).toBeVisible();
  }
  await expect(navigation.getByRole("button", { name: "Add", exact: true })).toHaveCount(0);
  await expect(navigation.getByRole("button", { name: "Sync", exact: true })).toHaveCount(0);
  await expect(navigation.getByRole("button", { name: "Conflicts", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add first password", exact: true })).toBeVisible();
  await expect(page.getByText(/Backup has not been set up/)).toBeVisible();
  await expectTermsHidden(page);
  await expectUniqueIds(page);

  await navigation.getByRole("button", { name: "Security & recovery", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Security & recovery", exact: true })).toBeVisible();
  const vaultStatus = page.locator(".status-row").filter({ hasText: "Vault" });
  await expect(vaultStatus).toContainText("Encrypted");
  await expectTermsHidden(page);
  await expectUniqueIds(page);

  await navigation.getByRole("button", { name: "Connections", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Optional password services" })).toBeVisible();
  await expect(page.getByLabel("Server address", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Access token", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Database file", { exact: true })).toHaveCount(0);

  const bitwardenCard = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Bitwarden" }) });
  await bitwardenCard.getByRole("button", { name: "Set up this connection", exact: true }).click();
  await expect(page.getByLabel("Server address", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Access token", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Database file", { exact: true })).toHaveCount(0);
  await page.getByLabel("Server address", { exact: true }).fill("https://generated.example.invalid");
  await page.getByRole("button", { name: "Save configuration", exact: true }).click();
  await page.getByRole("button", { name: "Test connection", exact: true }).click();
  const connectionWizard = page.locator(".connection-wizard");
  await expect(connectionWizard.getByText("Connection test passed", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Preview first import", exact: true }).click();
  await expect(page.getByText("Read-only preview", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Confirm and enable connection", exact: true }).click();
  await expect(page.getByText(/Connection enabled/)).toBeVisible();
  await expectTermsHidden(page);
  await expectUniqueIds(page);

  await navigation.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByText("Interface language", { exact: true })).toBeVisible();
  await expect(page.getByText("About & version", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Access token", { exact: true })).toHaveCount(0);
  await expectUniqueIds(page);

  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    accessibility.violations
      .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
      .map(({ id, impact, help }) => ({ id, impact, help })),
  ).toEqual([]);

  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach("beginner-settings-generated-data", { body: screenshot, contentType: "image/png" });
});

test("searches and reaches the end of a 1000-entry generated vault", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1000);
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));

  await page.goto("/");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();

  const search = page.getByLabel("Search vault");
  await search.fill("person-1000@example.invalid");
  await expect(page.getByRole("button", { name: "Open Generated account 1000", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Generated account 0001", exact: true })).toHaveCount(0);

  await search.fill("");
  const lastEntry = page.getByRole("button", { name: "Open Generated account 1000", exact: true });
  await lastEntry.scrollIntoViewIfNeeded();
  await expect(lastEntry).toBeVisible();
  await expect(page.getByRole("list", { name: "Vault entries" }).getByRole("listitem")).toHaveCount(1000);
});
