import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

// Real API tokens and plaintext imports must never enter a retained trace.
test.use({ trace: "off", screenshot: "off" });

const cell = (value: string) => `"${value.replaceAll('"', '""')}"`;
const content = () => [
  ["name", "url", "username", "password", "note"],
  ["Generated browser account", "https://browser.example.invalid/login", "generated-user", testData.entryPassword, "Generated note, 中文\nsecond line"],
  ["Generated browser account", "https://browser.example.invalid/login", "generated-user", testData.entryPassword, "Generated note, 中文\nsecond line"],
  ["Generated invalid record", "javascript:generated()", "generated-user", testData.entryPassword, ""],
].map((row) => row.map(cell).join(",")).join("\r\n");

test("Chrome import uses real preview, cancel, duplicate detection, apply, and undo", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("Confirm master password").fill(testData.masterPassword);
    await page.getByRole("button", { name: "Create and unlock" }).click();
    await page.getByRole("button", { name: "Import from browser", exact: true }).click();
    await expect(page.getByLabel("Import source")).toHaveValue("chrome");
    await expect(page.getByText(/Google Password Manager → Settings/)).toBeVisible();
    const upload = async () => page.getByLabel("Choose browser CSV file").setInputFiles({
      name: "generated-chrome.csv", mimeType: "text/csv", buffer: Buffer.from("\ufeff" + content()),
    });
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Choose browser CSV file", exact: true }).press("Enter");
    await (await chooser).setFiles({ name: "generated-chrome.csv", mimeType: "text/csv", buffer: Buffer.from(content()) });
    await expect(page.getByText("Recognized a Chrome / Edge password file.", { exact: false })).toBeVisible();
    await expect(page.getByText("Identical, skipped by default", { exact: true })).toBeVisible();
    await expect(page.getByText("Item 3", { exact: true })).toBeVisible();
    const includeAccount = page.getByLabel("Import Generated browser account", { exact: true });
    await includeAccount.uncheck();
    await expect(includeAccount).not.toBeChecked();
    await includeAccount.check();
    expect((await page.locator("body").innerText()).includes(testData.entryPassword)).toBe(false);
    const quality = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(quality.violations.filter((item) => ["serious", "critical"].includes(item.impact || "")).map((item) => item.id)).toEqual([]);
    await testInfo.attach("browser-import-generated-preview", { body: await page.locator(".import-wizard").screenshot({ path: testInfo.outputPath("browser-import-en.png") }), contentType: "image/png" });
    await page.getByRole("button", { name: "Cancel import" }).click();
    await page.getByRole("button", { name: "Back to passwords" }).click();
    await expect(page.getByText("Generated browser account", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Import from browser", exact: true }).click();
    await upload();
    await expect(page.getByRole("button", { name: "Confirm import" })).toBeDisabled();
    await page.getByLabel("I reviewed additions, duplicates, and skip reasons").check();
    await page.getByRole("button", { name: "Confirm import" }).click();
    await expect(page.getByText("1 added, 0 updated, 2 skipped.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Undo this import" }).click();
    await expect(page.getByText("This import has been undone.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Done", exact: true }).click();
    await expect(page.getByText("Generated browser account", { exact: true })).toHaveCount(0);
    // Commit once more and verify the record survives locking and reopening.
    await page.getByRole("button", { name: "Import from browser", exact: true }).click();
    await upload();
    await page.getByLabel("I reviewed additions, duplicates, and skip reasons").check();
    await page.getByRole("button", { name: "Confirm import" }).click();
    await page.getByRole("button", { name: "Done", exact: true }).click();
    await expect(page.getByText("Generated browser account", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Lock now", exact: true }).click();
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    const refreshedBackups = page.waitForResponse((response) => response.url().endsWith("/api/backups") && response.ok());
    await page.getByRole("button", { name: "Unlock", exact: true }).click();
    await expect(page.getByText("Generated browser account", { exact: true })).toBeVisible();
    await refreshedBackups;
  } finally {
    await sidecar.stop();
  }
});

test("Chinese Edge guide, UTF-8 rejection and invalid row explanations", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "zh"));
    await page.goto("/");
    await page.getByLabel("主密码", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("再次输入主密码", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: "创建并解锁", exact: true }).click();
    await page.getByRole("button", { name: "从浏览器导入", exact: true }).click();
    await page.getByLabel("密码来源").selectOption("edge");
    await expect(page.getByText(/打开 Edge 菜单/)).toBeVisible();
    await page.getByLabel("选择浏览器 CSV 文件").setInputFiles({
      name: "generated-invalid-encoding.csv", mimeType: "text/csv", buffer: Buffer.from([0xff, 0xfe, 0x61]),
    });
    await expect(page.getByRole("alert")).toContainText("UTF-8");
    await page.getByLabel("选择浏览器 CSV 文件").setInputFiles({
      name: "generated-edge.csv", mimeType: "text/csv", buffer: Buffer.from(content()),
    });
    await expect(page.getByText("跳过原因：这条记录缺少有效的网站或 Android 应用地址。", { exact: true })).toBeVisible();
    expect((await page.locator("body").innerText()).includes(testData.entryPassword)).toBe(false);
    await page.setViewportSize({ width: 520, height: 900 });
    await testInfo.attach("browser-import-generated-zh", { body: await page.locator(".import-wizard").screenshot({ path: testInfo.outputPath("browser-import-zh.png") }), contentType: "image/png" });
    const quality = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(quality.violations.filter((item) => ["serious", "critical"].includes(item.impact || "")).map((item) => item.id)).toEqual([]);
    await page.getByRole("button", { name: "取消导入", exact: true }).click();
  } finally {
    await sidecar.stop();
  }
});
