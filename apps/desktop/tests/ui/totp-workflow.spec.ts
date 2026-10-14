import AxeBuilder from "@axe-core/playwright";
import { fileURLToPath } from "node:url";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
const fixture = fileURLToPath(new URL("./fixtures/totp-rfc-test.png", import.meta.url));

test("local QR setup persists, renders a timed code and hides it on blur", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const sidecar = await startGeneratedSidecar(page);
  try {
    await page.addInitScript(() => localStorage.setItem("vault_locale", "zh"));
    await page.goto("/");
    await page.getByLabel("主密码", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("再次输入主密码", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: "创建并解锁", exact: true }).click();
    await page.getByRole("button", { name: "添加密码", exact: true }).click();
    await page.getByLabel("网站或应用名称", { exact: true }).fill("Generated OTP account");
    await page.getByLabel("密码", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: "更多选项", exact: true }).click();
    const key = page.getByLabel("验证器密钥（TOTP 密钥）", { exact: true });
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "从二维码图片录入", exact: true }).press("Enter");
    await (await chooser).setFiles(fixture);
    await expect(key).toHaveValue(/^otpauth:\/\/totp\/RFC/);
    await expect(page.getByRole("button", { name: "复制验证码", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "显示验证码", exact: true }).click();
    await expect(page.getByLabel("当前验证码", { exact: true })).toHaveText(/^\d{6}$/);
    await expect(page.getByRole("timer")).toHaveText(/^\d+ 秒后更新$/);
    const initialCode = await page.getByLabel("当前验证码", { exact: true }).textContent();
    await expect.poll(async () => {
      const next = await page.getByLabel("当前验证码", { exact: true }).textContent();
      return Boolean(next && /^\d{6}$/.test(next) && next !== initialCode);
    }, { timeout: 5000 }).toBe(true);
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    await expect(page.getByLabel("当前验证码", { exact: true })).toHaveCount(0);
    await expect(key).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.getByRole("button", { name: "打开 Generated OTP account", exact: true }).click();
    await page.getByRole("button", { name: "更多选项", exact: true }).click();
    await expect(key).toHaveValue(/^otpauth:\/\/totp\/RFC/);
    await expect(page.getByRole("button", { name: "复制验证码", exact: true })).toBeEnabled();
    const quality = await new AxeBuilder({ page }).analyze();
    expect(quality.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await page.getByRole("region", { name: "动态验证码", exact: true }).screenshot({ path: testInfo.outputPath("totp-setup-generated.png") });
    // Invalid input is a draft validation result, without exposing its contents.
    await key.fill("invalid generated authenticator input");
    await page.getByRole("button", { name: "显示验证码", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("无法生成验证码");
    await page.getByRole("button", { name: "取消", exact: true }).click();
    await page.getByRole("button", { name: "放弃更改", exact: true }).click();
    await page.getByRole("button", { name: "打开 Generated OTP account", exact: true }).click();
    await page.getByRole("button", { name: "更多选项", exact: true }).click();
    await expect(key).toHaveValue(/^otpauth:\/\/totp\/RFC/);
  } finally { await sidecar.stop(); }
});
