import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

async function createVault(
  page: Parameters<MockAuthenticatedSidecar["install"]>[0],
  locale: "en" | "zh" = "en",
) {
  await page.addInitScript((selectedLocale) => localStorage.setItem("vault_locale", selectedLocale), locale);
  await page.goto("/");
  await page.getByLabel(locale === "zh" ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel(locale === "zh" ? "再次输入主密码" : "Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: locale === "zh" ? "创建并解锁" : "Create and unlock" }).click();
}

test("offers the system path picker before the advanced manual fallback", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  await page.goto("/");

  await page.getByRole("button", { name: "Restore backup", exact: true }).click();
  await expect(page.getByRole("button", { name: "Choose file", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Encrypted backup file path", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Enter path manually (advanced)", exact: true }).click();
  const manual = page.getByRole("textbox", { name: "Encrypted backup file path", exact: true });
  await expect(manual).toBeVisible();
  await manual.fill("C:\\generated-tests\\backup.vault.bak");
});

test("keeps login basics first and edits advanced data through a summary", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);

  await page.getByRole("button", { name: "Add password", exact: true }).click();
  const type = page.getByLabel("Content type", { exact: true });
  await expect(type.locator("option")).toHaveText(["Login", "Secure note"]);
  await expect(page.getByLabel("Website or app name", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Username", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate password", exact: true })).toBeVisible();
  await expect(page.getByLabel("Website address", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Notes", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Authenticator key (TOTP key)", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Custom fields", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Attachments", exact: true })).toHaveCount(0);

  const passwordBox = await page.getByLabel("Password", { exact: true }).boundingBox();
  const generatorBox = await page.getByRole("button", { name: "Generate password", exact: true }).boundingBox();
  expect(passwordBox).not.toBeNull();
  expect(generatorBox).not.toBeNull();
  expect(Math.abs((passwordBox?.y || 0) - (generatorBox?.y || 0))).toBeLessThan(8);

  await page.getByLabel("Website or app name", { exact: true }).fill("Generated progressive account");
  await page.getByLabel("Username", { exact: true }).fill("progressive@example.invalid");
  await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
  await page.getByRole("button", { name: "More options", exact: true }).click();
  await page.getByLabel("Add a tag", { exact: true }).fill("personal");
  await page.getByLabel("Add a tag", { exact: true }).press("Enter");
  await page.getByRole("textbox", { name: "Authenticator key (TOTP key)", exact: true }).fill(testData.entryPassword);
  await page.getByRole("button", { name: "Add custom field", exact: true }).click();
  await page.getByLabel("Field name", { exact: true }).fill("Account number");
  await page.getByLabel("Field content", { exact: true }).fill("generated-value");
  await page.getByRole("button", { name: "Collapse more options", exact: true }).click();
  await expect(page.getByText(/More content already saved: 1 tag\(s\).*authenticator key.*1 custom field/)).toBeVisible();

  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Generated progressive account", { exact: true })).toBeVisible();
  expect(sidecar.persistedEntries[0].tags).toEqual(["personal"]);
  expect(sidecar.persistedEntries[0].totp_secret).toBe(testData.entryPassword);
  expect(sidecar.persistedEntries[0].custom_fields).toEqual([
    { label: "Account number", value: "generated-value", concealed: false },
  ]);
});

test("secure notes use a dedicated simple form", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);

  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Content type", { exact: true }).selectOption("secure_note");
  await expect(page.getByRole("heading", { name: "Add secure note", exact: true })).toBeVisible();
  await expect(page.getByLabel("Note title", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Username", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Password", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Website address", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Generate password", exact: true })).toHaveCount(0);

  await page.getByLabel("Note title", { exact: true }).fill("Generated secure note");
  await page.getByLabel("Notes", { exact: true }).fill("Generated note content only");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect(sidecar.persistedEntries[0].entry_type).toBe("secure_note");
  expect(sidecar.persistedEntries[0].username).toBe("");
  expect(sidecar.persistedEntries[0].password).toBe("");
  expect(sidecar.persistedEntries[0].url).toBe("");
});

test("advanced validation expands the collapsed section before any write", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);

  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("Website or app name", { exact: true }).fill("Generated validation account");
  await page.getByRole("button", { name: "More options", exact: true }).click();
  await page.getByRole("button", { name: "Add custom field", exact: true }).click();
  await page.getByRole("button", { name: "Collapse more options", exact: true }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();

  const validation = page.getByRole("alert").filter({ hasText: "Every custom field needs a field name." });
  await expect(validation).toBeVisible();
  await expect(validation).toBeFocused();
  await expect(page.getByRole("button", { name: "Collapse more options", exact: true })).toHaveAttribute("aria-expanded", "true");
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
});

test("preserves an existing compatibility type without exposing its internal enum in Chinese", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  sidecar.seedCompatibilityEntry("ssh_key");
  await sidecar.install(page);
  await createVault(page, "zh");

  await page.getByRole("button", { name: "打开 Generated compatibility item", exact: true }).click();
  await expect(page.getByText("SSH 密钥（兼容）", { exact: true })).toBeVisible();
  expect(await page.locator("body").innerText()).not.toContain("ssh_key");
  await expect(page.getByLabel("网站或应用名称", { exact: true })).toHaveValue("Generated compatibility item");
  await expect(page.getByText(/已有更多内容：2 个标签.*1 个自定义字段/)).toBeVisible();
  await page.getByLabel("备注", { exact: true }).fill("更新后的兼容测试备注");
  await page.getByRole("button", { name: "保存", exact: true }).click();

  expect(sidecar.persistedEntries[0].entry_type).toBe("ssh_key");
  expect(sidecar.persistedEntries[0].password).toBe(testData.entryPassword);
  expect(sidecar.persistedEntries[0].tags).toEqual(["generated", "compatibility"]);
});

test("remains keyboard ordered and reachable at 800 by 600 with 200 percent zoom", async ({ page }, testInfo) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.setViewportSize({ width: 800, height: 600 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await createVault(page);
  await page.getByRole("button", { name: "Add password", exact: true }).click();

  const title = page.getByLabel("Website or app name", { exact: true });
  await title.focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Username", { exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password", { exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Show password", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Generate password", exact: true })).toBeFocused();

  const smallTargets = await page.locator("button:visible").evaluateAll((buttons) => buttons
    .map((button) => {
      const box = button.getBoundingClientRect();
      return { name: button.textContent?.trim() || button.getAttribute("aria-label") || "", width: box.width, height: box.height };
    })
    .filter((target) => target.width < 40 || target.height < 40));
  expect(smallTargets).toEqual([]);

  for (const zoom of [1.25, 1.5, 2]) {
    await page.evaluate((value) => { document.documentElement.style.zoom = String(value); }, zoom);
    await page.getByRole("button", { name: "More options", exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: "More options", exact: true })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow at ${zoom * 100}% zoom`).toBeLessThanOrEqual(1);
  }

  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    accessibility.violations
      .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
      .map(({ id, impact, help }) => ({ id, impact, help })),
  ).toEqual([]);

  await testInfo.attach("progressive-entry-800x600-200-percent-generated", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});
