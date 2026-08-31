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

async function addGeneratedEntry(page: Parameters<MockAuthenticatedSidecar["install"]>[0], title: string) {
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill(title);
  await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(title, { exact: true })).toBeVisible();
}

test("keeps custom-field focus stable and guards navigation, cancel, and manual lock", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);

  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Generated unsaved draft");
  await page.getByRole("button", { name: "Add field", exact: true }).click();
  const label = page.getByLabel("Field label", { exact: true });
  const hundredCharacters = "x".repeat(100);
  await label.click();
  await page.keyboard.type(hundredCharacters);
  await expect(label).toHaveValue(hundredCharacters);
  await expect(label).toBeFocused();

  const duplicateIds = await page.locator("[id]").evaluateAll((elements) => {
    const counts = new Map<string, number>();
    for (const element of elements) counts.set(element.id, (counts.get(element.id) || 0) + 1);
    return Array.from(counts.entries()).filter(([, count]) => count > 1);
  });
  expect(duplicateIds).toEqual([]);

  await page.getByRole("button", { name: "Connections", exact: true }).click();
  await expect(page.getByRole("alertdialog", { name: "Discard unsaved changes?" })).toBeVisible();
  await page.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Generated unsaved draft");
  await expect(page.getByRole("button", { name: "Connections", exact: true })).toBeFocused();

  await page.getByRole("button", { name: "Lock now", exact: true }).click();
  await expect(page.getByRole("alertdialog", { name: "Discard unsaved changes?" })).toBeVisible();
  await page.getByRole("button", { name: "Keep editing", exact: true }).click();
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });

  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();
  await expect(page.getByLabel("Search vault")).toBeVisible();
  expect(sidecar.persistedEntries).toEqual([]);
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
});

test("a failed attachment batch leaves the persisted entry unchanged", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);
  const title = "Generated attachment account";
  await addGeneratedEntry(page, title);

  await page.getByRole("button", { name: `Open ${title}`, exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Must not partially save");
  await page.getByLabel("Choose attachments").setInputFiles([
    { name: "generated-one.txt", mimeType: "text/plain", buffer: Buffer.from("generated-one") },
    { name: "generated-two.txt", mimeType: "text/plain", buffer: Buffer.from("generated-two") },
    { name: "generated-fail-third.txt", mimeType: "text/plain", buffer: Buffer.from("generated-three") },
  ]);
  await page.getByRole("button", { name: "Save", exact: true }).click();

  await expect(page.getByRole("alert").filter({ hasText: "no changes were committed" }).first()).toBeVisible();
  expect(sidecar.writes).toEqual({ create: 1, update: 0, delete: 0 });
  expect(sidecar.persistedEntries).toHaveLength(1);
  expect(sidecar.persistedEntries[0].title).toBe(title);
  expect(sidecar.persistedEntries[0].attachments).toEqual([]);
});

test("removing an attachment and then cancelling performs zero writes", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);
  const title = "Generated retained attachment";
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill(title);
  await page.getByLabel("Choose attachments").setInputFiles({
    name: "generated-retained.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("generated retained content"),
  });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(title, { exact: true })).toBeVisible();
  expect(sidecar.persistedEntries[0].attachments).toHaveLength(1);

  await page.getByRole("button", { name: `Open ${title}`, exact: true }).click();
  await page.getByRole("button", { name: "Remove on save", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();

  expect(sidecar.writes).toEqual({ create: 1, update: 0, delete: 0 });
  expect(sidecar.persistedEntries[0].attachments).toHaveLength(1);
  expect(sidecar.persistedEntries[0].attachments[0].filename).toBe("generated-retained.txt");
});

test("history restore stays in the draft and cancel preserves the current version", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);
  const originalTitle = "Generated original history";
  const currentTitle = "Generated current history";
  await addGeneratedEntry(page, originalTitle);
  await page.getByRole("button", { name: `Open ${originalTitle}`, exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill(currentTitle);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(currentTitle, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: `Open ${currentTitle}`, exact: true }).click();
  await page.getByRole("button", { name: "Preview in draft", exact: true }).click();
  await page.getByRole("button", { name: "Load draft", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(originalTitle);
  expect(sidecar.persistedEntries[0].title).toBe(currentTitle);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();

  expect(sidecar.writes).toEqual({ create: 1, update: 1, delete: 0 });
  expect(sidecar.persistedEntries[0].title).toBe(currentTitle);
});

test("navigation is blocked during save and a double click commits only once", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 750);
  await sidecar.install(page);
  await createVault(page);
  const title = "Generated single transaction";
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill(title);
  const save = page.getByRole("button", { name: "Save", exact: true });
  await save.evaluate((element) => {
    (element as HTMLButtonElement).click();
    (element as HTMLButtonElement).click();
  });
  await expect(page.getByRole("button", { name: "Saving…", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Connections", exact: true }).click();
  await expect(page.getByText("Save in progress; please wait", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(title);
  await expect(page.getByText(title, { exact: true })).toBeVisible({ timeout: 3_000 });
  expect(sidecar.writes).toEqual({ create: 1, update: 0, delete: 0 });
  expect(sidecar.persistedEntries).toHaveLength(1);
});

test("automatic lock warns, clears the in-memory draft, and writes nothing", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(2);
  await sidecar.install(page);
  await createVault(page);
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Generated auto-lock draft");
  await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);

  await expect(page.getByRole("alert").filter({ hasText: "app will lock and clear it" })).toBeVisible({ timeout: 2_000 });
  await expect(page.getByRole("button", { name: "Unlock", exact: true })).toBeVisible({ timeout: 4_000 });
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
  const storage = await page.evaluate(() => JSON.stringify({ local: localStorage, session: sessionStorage }));
  expect(storage).not.toContain(testData.entryPassword);
});
