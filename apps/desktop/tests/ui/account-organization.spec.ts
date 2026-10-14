import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

test("Chinese trash preview explains retention and can be cancelled", async ({ page }) => {
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "zh"));
    await page.goto("/");
    await page.getByLabel("主密码", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("再次输入主密码", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: "创建并解锁", exact: true }).click();
    await page.getByRole("button", { name: "添加密码", exact: true }).click();
    await page.getByLabel("网站或应用名称", { exact: true }).fill("生成的中文账号");
    await page.getByLabel("密码", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.getByText("筛选与批量整理", { exact: true }).click();
    await page.getByLabel("选择 生成的中文账号", { exact: true }).check();
    await page.getByRole("button", { name: "移到回收站", exact: true }).first().click();
    await expect(page.getByRole("alertdialog")).toContainText("回收站保留 30 天");
    await page.getByRole("button", { name: "取消", exact: true }).click();
    await expect(page.getByText("生成的中文账号", { exact: true })).toBeVisible();
  } finally { await sidecar.stop(); }
});

test("real account organization retains trash, restores, filters favorites and previews bulk archive", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("Confirm master password").fill(testData.masterPassword);
    await page.getByRole("button", { name: "Create and unlock", exact: true }).click();
    for (const name of ["Generated account A", "Generated account B"]) {
      await page.getByRole("button", { name: "Add password", exact: true }).click();
      await page.getByLabel("Website or app name", { exact: true }).fill(name);
      await page.getByLabel("Username", { exact: true }).fill("generated-user");
      await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText(name, { exact: true })).toBeVisible();
    }
    const first = page.locator(".entry-row").filter({ hasText: "Generated account A" });
    await first.locator("summary").click();
    await first.getByRole("button", { name: "Favorite", exact: true }).click();
    await expect(first.getByLabel("Favorite", { exact: true })).toBeVisible();
    await page.getByText("Filters and bulk organization", { exact: true }).click();
    await page.getByLabel("Favorites only", { exact: true }).check();
    await expect(page.locator(".entry-row")).toHaveCount(1);
    await page.getByLabel("Favorites only", { exact: true }).uncheck();
    await page.getByRole("button", { name: "Select current list", exact: true }).click();
    await page.getByRole("button", { name: "Archive", exact: true }).first().click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Generated account A");
    await expect(dialog).toContainText("Generated account B");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.locator(".entry-row")).toHaveCount(2);
    await page.getByRole("button", { name: "Archive", exact: true }).first().click();
    await dialog.getByRole("button", { name: "Archive", exact: true }).click();
    await expect(page.locator(".entry-row")).toHaveCount(0);
    await page.getByLabel("Entry location").selectOption("archived");
    await expect(page.locator(".entry-row")).toHaveCount(2);
    await page.getByLabel("Select Generated account A", { exact: true }).check();
    await page.getByRole("button", { name: "Move to trash", exact: true }).first().click();
    await expect(dialog).toContainText("30 days");
    await dialog.getByRole("button", { name: "Move to trash", exact: true }).click();
    await page.getByLabel("Entry location").selectOption("trash");
    await expect(page.locator(".entry-row")).toHaveCount(1);
    await page.getByLabel("Select Generated account A", { exact: true }).check();
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await expect(page.locator(".toast")).toHaveCount(0);
    await page.locator("main").screenshot({ path: testInfo.outputPath("account-organization.png") });
    await page.getByRole("button", { name: "Restore to vault", exact: true }).first().click();
    await dialog.getByRole("button", { name: "Restore to vault", exact: true }).click();
    await page.getByLabel("Entry location").selectOption("active");
    await expect(page.getByText("Generated account A", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Lock now", exact: true }).click();
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    const refreshedBackups = page.waitForResponse(response => response.url().endsWith("/api/backups") && response.ok());
    await page.getByRole("button", { name: "Unlock", exact: true }).click();
    await refreshedBackups;
    await expect(page.getByText("Generated account A", { exact: true })).toBeVisible();
    await page.getByLabel("Entry location").selectOption("archived");
    await expect(page.getByText("Generated account B", { exact: true })).toBeVisible();
  } finally { await sidecar.stop(); }
});
