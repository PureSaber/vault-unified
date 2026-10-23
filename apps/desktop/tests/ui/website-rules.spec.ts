import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"] as const) test(`website rules test exact, extra, base and excluded origins and discard safely (${locale})`, async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const zh = locale === "zh";
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
    await page.goto("/");
    await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
    await page.getByRole("button", { name: zh ? "添加密码" : "Add password", exact: true }).click();
    await page.getByLabel(zh ? "网站或应用名称" : "Website or app name", { exact: true }).fill("Generated site rules");
    await page.getByLabel(zh ? "密码" : "Password", { exact: true }).fill(testData.entryPassword);
    await page.getByLabel(zh ? "网站地址" : "Website address", { exact: true }).fill("https://example.com");
    await page.getByRole("button", { name: zh ? "更多选项" : "More options", exact: true }).click();
    const mode = page.getByLabel(zh ? "匹配方式" : "Matching mode", { exact: true });
    const check = async (url: string, matches: boolean) => {
      await page.getByLabel(zh ? "测试网址" : "Test website", { exact: true }).fill(url);
      await page.getByRole("button", { name: zh ? "测试匹配" : "Test match", exact: true }).click();
      await expect(page.getByText(matches ? (zh ? "该网址会匹配此账号。" : "This website matches the account.") : (zh ? "该网址不会匹配此账号。" : "This website does not match the account."), { exact: true })).toBeVisible();
    };
    await expect(mode).toHaveValue("exact");
    await check("https://login.example.com", false);
    await page.getByRole("button", { name: zh ? "添加其他网址" : "Add another website", exact: true }).press("Enter");
    await page.getByLabel(zh ? "其他网址 1" : "Other website 1", { exact: true }).fill("https://login.example.net");
    await check("https://login.example.net", true);
    await mode.selectOption("base_domain");
    await check("https://accounts.example.com", true);
    await page.getByRole("button", { name: zh ? "添加排除网址" : "Add excluded website", exact: true }).click();
    await page.getByLabel(zh ? "排除网址 1" : "Excluded website 1", { exact: true }).fill("https://blocked.example.com");
    await check("https://blocked.example.com", false);
    const quality = await new AxeBuilder({ page }).analyze();
    expect(quality.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await page.getByRole("region", { name: zh ? "网站匹配规则" : "Website matching rules", exact: true }).screenshot({ path: testInfo.outputPath(`website-rules-${locale}.png`) });
    await page.getByLabel(zh ? "测试网址" : "Test website", { exact: true }).fill("invalid test does not block saving unrelated fields");
    await page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click();
    const open = async () => { await page.getByRole("button", { name: zh ? "打开 Generated site rules" : "Open Generated site rules", exact: true }).click(); await page.getByRole("article").getByRole("button", { name: zh ? "编辑" : "Edit", exact: true }).click(); };
    await open();
    await page.getByRole("button", { name: zh ? "更多选项" : "More options", exact: true }).click();
    await expect(mode).toHaveValue("base_domain");
    await mode.selectOption("exact");
    await page.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click();
    await page.getByRole("button", { name: zh ? "放弃更改" : "Discard changes", exact: true }).click();
    await open();
    await page.getByRole("button", { name: zh ? "更多选项" : "More options", exact: true }).click();
    await expect(mode).toHaveValue("base_domain");
    await check("https://login.example.net", true);
    await check("https://blocked.example.com", false);
  } finally { await sidecar.stop(); }
});
