import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

for (const locale of ["en", "zh"] as const) test(`credential templates persist used codes, licenses and API details (${locale})`, async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const zh = locale === "zh";
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
    await page.goto("/");
    await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
    const save = () => page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click();
    const cancel = () => page.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click();
    const open = (title: string) => page.getByRole("button", { name: `${zh ? "打开" : "Open"} ${title}`, exact: true }).click();
    const add = async (type: string, title: string) => {
      await page.getByRole("button", { name: zh ? "添加密码" : "Add password", exact: true }).click();
      await page.getByLabel(zh ? "内容类型" : "Content type", { exact: true }).selectOption(type);
      await page.getByLabel(zh ? "名称" : "Name", { exact: true }).fill(title);
    };
    await add("recovery_code", "Generated codes");
    for (const [index, code] of [testData.entryPassword, testData.masterPassword].entries()) {
      await page.getByRole("button", { name: zh ? "添加恢复码" : "Add recovery code", exact: true }).click();
      await page.getByLabel(`${zh ? "恢复码" : "Recovery code"} ${index + 1}`, { exact: true }).fill(code);
    }
    await expect(page.getByRole("button", { name: zh ? "复制恢复码" : "Copy recovery code", exact: true }).first()).toBeDisabled();
    await save(); await open("Generated codes");
    const used = page.getByLabel(zh ? "已使用" : "Used", { exact: true }).first();
    await used.check(); await cancel();
    await page.getByRole("button", { name: zh ? "放弃更改" : "Discard changes", exact: true }).click();
    await open("Generated codes");
    await expect(used).not.toBeChecked();
    await used.check(); await save(); await open("Generated codes");
    await expect(used).toBeChecked();
    await expect(page.getByRole("button", { name: zh ? "复制恢复码" : "Copy recovery code", exact: true }).first()).toBeDisabled();
    await expect(page.getByRole("button", { name: zh ? "复制恢复码" : "Copy recovery code", exact: true }).nth(1)).toBeEnabled();
    await expect(page.getByLabel(`${zh ? "恢复码" : "Recovery code"} 1`, { exact: true })).toHaveAttribute("type", "password");
    const quality = await new AxeBuilder({ page }).analyze();
    expect(quality.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await page.getByRole("region", { name: zh ? "凭据详情" : "Credential details", exact: true }).screenshot({ path: testInfo.outputPath(`recovery-codes-${locale}.png`) });
    await cancel();
    await add("software_license", "Generated license");
    await page.getByLabel(zh ? "许可证密钥" : "License key", { exact: true }).fill(testData.entryPassword);
    await page.getByLabel(zh ? "登记人或邮箱" : "Registered name or email", { exact: true }).fill("Generated owner");
    await page.getByLabel(zh ? "到期日（可选）" : "Expiry date (optional)", { exact: true }).fill("2027-10-14");
    await save(); await open("Generated license");
    await expect(page.getByLabel(zh ? "许可证密钥" : "License key", { exact: true })).toHaveValue(testData.entryPassword);
    await expect(page.getByLabel(zh ? "登记人或邮箱" : "Registered name or email", { exact: true })).toHaveValue("Generated owner");
    await cancel();
    await add("api_credential", "Generated API");
    await page.getByLabel(zh ? "API 令牌或密钥" : "API token or key", { exact: true }).fill(testData.entryPassword);
    await page.getByLabel(zh ? "环境" : "Environment", { exact: true }).fill("development");
    await page.getByLabel(zh ? "权限范围" : "Scopes", { exact: true }).fill("generated:read");
    await save(); await open("Generated API");
    await expect(page.getByLabel(zh ? "权限范围" : "Scopes", { exact: true })).toHaveValue("generated:read");
    await expect(page.getByLabel(zh ? "环境" : "Environment", { exact: true })).toHaveValue("development");
  } finally { await sidecar.stop(); }
});
