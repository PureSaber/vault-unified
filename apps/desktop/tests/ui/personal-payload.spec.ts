import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"]) {
  test(`personal payload upgrade cancels and reopens with a retained backup (${locale})`, async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    const sidecar = await startGeneratedSidecar(page, { oldPayload: true });
    const zh = locale === "zh";
    try {
      await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
      await page.goto("/");
      await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
      await page.getByRole("button", { name: zh ? "解锁" : "Unlock", exact: true }).click();
      await page.getByRole("button", { name: zh ? "安全与恢复" : "Security & recovery", exact: true }).click();
      const review = page.getByRole("button", { name: zh ? "查看升级" : "Review upgrade", exact: true });
      await review.click();
      const dialog = page.getByRole("alertdialog");
      await expect(dialog).toContainText(zh ? "全部 0 个条目" : "all 0 entries");
      const accessibility = await new AxeBuilder({ page }).analyze();
      expect(accessibility.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
      await dialog.screenshot({ path: testInfo.outputPath(`personal-format-${locale}.png`) });
      await dialog.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click();
      await expect(review).toBeVisible();
      await review.click();
      await page.getByRole("button", { name: zh ? "备份并升级" : "Back up and upgrade", exact: true }).click();
      await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
      await page.getByRole("button", { name: zh ? "解锁" : "Unlock", exact: true }).click();
      await page.getByRole("button", { name: zh ? "安全与恢复" : "Security & recovery", exact: true }).click();
      await expect(page.getByText(zh ? "已启用个人版数据格式。" : "Personal vault data format is enabled.", { exact: true })).toBeVisible();
      await expect(review).toHaveCount(0);
      await page.getByRole("button", { name: zh ? "管理历史备份" : "Manage backup history", exact: true }).click();
      await expect(page.getByRole("button", { name: zh ? "取消固定" : "Unpin", exact: true })).toHaveCount(1);
    } finally { await sidecar.stop(); }
  });
}
