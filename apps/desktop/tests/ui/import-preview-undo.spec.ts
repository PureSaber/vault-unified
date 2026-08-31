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

function generatedImport(existingTitle: string): string {
  const base = {
    username: "generated-import-user@example.invalid",
    url: "https://import.example.invalid/login",
    notes: "Generated import fixture only",
    tags: [],
    entry_type: "login",
    custom_fields: [],
    totp_secret: "",
    attachments: [],
  };
  return JSON.stringify({
    schema: "vault-unified-transfer",
    version: 1,
    entries: [
      { ...base, title: existingTitle, password: testData.entryPassword },
      { ...base, title: "Generated possible duplicate", password: `${testData.entryPassword}-changed` },
      {
        ...base,
        title: "Generated new import",
        username: "generated-new-user@example.invalid",
        url: "https://new.example.invalid/login",
        password: `${testData.entryPassword}-new`,
      },
    ],
  });
}

test("previews duplicates without secrets, cancels with zero writes, applies once, and undoes", async ({ page }, testInfo) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);

  const existingTitle = "Generated existing import account";
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill(existingTitle);
  await page.getByLabel("Username", { exact: true }).fill("generated-import-user@example.invalid");
  await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
  await page.getByLabel("URL", { exact: true }).fill("https://import.example.invalid/login");
  await page.getByLabel("Notes", { exact: true }).fill("Generated import fixture only");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(existingTitle, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Security & recovery", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Import passwords" })).toBeVisible();
  const content = generatedImport(existingTitle);
  const input = page.getByLabel("Choose JSON / CSV file");
  await input.setInputFiles({
    name: "generated-import.json",
    mimeType: "application/json",
    buffer: Buffer.from(content),
  });

  await expect(page.getByText("Identical, skipped by default", { exact: true })).toBeVisible();
  await expect(page.getByText("Possible duplicate; choose an action", { exact: true })).toBeVisible();
  await expect(page.getByText("Generated new import", { exact: true })).toBeVisible();
  expect(await page.locator("body").innerText()).not.toContain(testData.entryPassword);
  expect(sidecar.importWrites).toEqual({ apply: 0, undo: 0 });
  expect(sidecar.persistedEntries).toHaveLength(1);
  await testInfo.attach("generated-import-preview", {
    body: await page.locator(".import-wizard").screenshot(),
    contentType: "image/png",
  });

  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    accessibility.violations
      .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
      .map(({ id, impact, help }) => ({ id, impact, help })),
  ).toEqual([]);

  await page.getByRole("button", { name: "Cancel import" }).click();
  await expect(page.getByText("Choose JSON / CSV file", { exact: true })).toBeVisible();
  expect(sidecar.importWrites).toEqual({ apply: 0, undo: 0 });
  expect(sidecar.persistedEntries).toHaveLength(1);

  await page.getByLabel("Choose JSON / CSV file").setInputFiles({
    name: "generated-import.json",
    mimeType: "application/json",
    buffer: Buffer.from(content),
  });
  const resolution = page.getByLabel("What to do");
  await resolution.selectOption({ label: `Update existing: ${existingTitle}` });
  const apply = page.getByRole("button", { name: "Confirm import" });
  await expect(apply).toBeDisabled();
  await page.getByLabel("I reviewed additions, duplicates, and skip reasons").check();
  await apply.dblclick();

  await expect(page.getByRole("heading", { name: "Import result" })).toBeVisible();
  await expect(page.getByText("1 added, 1 updated, 1 skipped.", { exact: true })).toBeVisible();
  expect(sidecar.importWrites).toEqual({ apply: 1, undo: 0 });
  expect(sidecar.persistedEntries).toHaveLength(2);
  expect(sidecar.persistedEntries.map((entry) => entry.title).sort()).toEqual([
    "Generated new import",
    "Generated possible duplicate",
  ]);
  expect(await page.locator("body").innerText()).not.toContain(testData.entryPassword);

  await page.getByRole("button", { name: "Undo this import" }).click();
  await expect(page.getByText("This import has been undone.", { exact: true })).toBeVisible();
  expect(sidecar.importWrites).toEqual({ apply: 1, undo: 1 });
  expect(sidecar.persistedEntries).toHaveLength(1);
  expect(sidecar.persistedEntries[0].title).toBe(existingTitle);

  const duplicateIds = await page.locator("[id]").evaluateAll((elements) => {
    const counts = new Map<string, number>();
    for (const element of elements) counts.set(element.id, (counts.get(element.id) || 0) + 1);
    return Array.from(counts.entries()).filter(([, count]) => count > 1);
  });
  expect(duplicateIds).toEqual([]);
});
