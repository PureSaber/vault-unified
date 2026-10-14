import { appendFile } from "node:fs/promises";
import { resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"] as const) test(`offline findings, optional exposure and password improvement (${locale})`, async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const zh = locale === "zh";
  const sidecar = await startGeneratedSidecar(page);
  const weak = testData.entryPassword.slice(-10);
  await appendFile(resolve(".playwright-runtime/secret-markers.txt"), weak + "\n");
  const requests: Array<{ entry_id: string; confirm_network: boolean }> = [];
  try {
    await page.addInitScript(value => {
      localStorage.setItem("vault_locale", value);
      Object.assign(window, { generatedOpenedSites: [] });
      window.open = ((url: string) => { (window as unknown as { generatedOpenedSites: string[] }).generatedOpenedSites.push(url); return null; }) as typeof window.open;
    }, locale);
    await page.goto("/");
    await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
    for (const [title, password] of [["Generated first", weak], ["Generated second", weak], ["Generated strong", testData.entryPassword]]) {
      await page.getByRole("button", { name: zh ? "添加密码" : "Add password", exact: true }).click();
      await page.getByLabel(zh ? "网站或应用名称" : "Website or app name", { exact: true }).fill(title);
      await page.getByLabel(zh ? "用户名" : "Username", { exact: true }).fill("generated@example.invalid");
      await page.getByLabel(zh ? "密码" : "Password", { exact: true }).fill(password);
      await page.getByLabel(zh ? "网站地址" : "Website address", { exact: true }).fill("https://account.example.invalid/private?generated=discard");
      await page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click();
      await expect(page.getByRole("button", { name: `${zh ? "打开" : "Open"} ${title}`, exact: true })).toBeVisible();
    }
    await page.getByRole("button", { name: zh ? "安全与恢复" : "Security & recovery", exact: true }).click();
    const section = page.getByRole("region", { name: zh ? "密码检查" : "Password check", exact: true });
    const reportResponse = page.waitForResponse(value => value.url().endsWith("/security/password-health"));
    await section.getByRole("button", { name: zh ? "检查本地密码" : "Check local passwords", exact: true }).click();
    const report = await (await reportResponse).json() as { entries: Array<{ id: string; weak: boolean }> };
    await expect(section.getByRole("status")).toHaveText(zh ? "已检查 3 个账号 · 弱密码 2 · 重复密码 2" : "3 logins checked · 2 weak · 2 reused");
    const consent = section.getByRole("checkbox", { name: zh ? "本次允许联网查询泄露记录" : "Allow exposure lookups for this visit", exact: true });
    const bulk = section.getByRole("button", { name: zh ? "查询这些账号的泄露记录" : "Check these logins for exposure", exact: true });
    await expect(consent).not.toBeChecked(); await expect(bulk).toBeDisabled();
    const reused = report.entries.filter(item => item.weak).map(item => item.id);
    await page.route("**/api/security/exposure", async route => {
      const body = route.request().postDataJSON(); requests.push(body);
      const ids = reused.includes(body.entry_id) ? reused : [body.entry_id];
      await route.fulfill({ headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:1420" }, json: { entry_id: body.entry_id, matching_entry_ids: ids, count: reused.includes(body.entry_id) ? 9 : 0 } });
    });
    expect(requests).toHaveLength(0);
    await consent.check(); await bulk.click();
    await expect(bulk).toBeEnabled();
    expect(requests).toHaveLength(2);
    expect(requests.every(item => item.confirm_network === true && Object.keys(item).sort().join(",") === "confirm_network,entry_id")).toBe(true);
    const first = section.getByRole("region", { name: "Generated first", exact: true });
    await expect(first).toContainText(zh ? "此密码出现在泄露记录中（9 次）" : "This password appears in exposure records (9 times)");
    await section.getByLabel(zh ? "筛选问题" : "Filter findings", { exact: true }).selectOption("exposed");
    expect((await new AxeBuilder({ page }).analyze()).violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await section.screenshot({ path: testInfo.outputPath(`password-health-${locale}.png`) });
    await first.getByRole("button", { name: zh ? "打开网站改密" : "Open website to change password", exact: true }).click();
    expect(await page.evaluate(() => (window as unknown as { generatedOpenedSites: string[] }).generatedOpenedSites)).toEqual(["https://account.example.invalid/.well-known/change-password"]);
    await first.getByRole("button", { name: zh ? "更新已存密码" : "Update saved password", exact: true }).click();
    const password = page.getByLabel(zh ? "密码" : "Password", { exact: true });
    await expect.poll(async () => await password.inputValue() === weak).toBe(true);
    await page.getByRole("button", { name: zh ? "生成密码" : "Generate password", exact: true }).click();
    await expect.poll(async () => (await password.inputValue()).length === 20 && await password.inputValue() !== weak).toBe(true);
    await page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click();
    await expect(page.getByRole("button", { name: zh ? "打开 Generated first" : "Open Generated first", exact: true })).toBeVisible();
    await page.getByRole("button", { name: zh ? "安全与恢复" : "Security & recovery", exact: true }).click();
    await section.getByRole("button", { name: zh ? "检查本地密码" : "Check local passwords", exact: true }).click();
    await expect(section.getByRole("status")).toHaveText(zh ? "已检查 3 个账号 · 弱密码 1 · 重复密码 0" : "3 logins checked · 1 weak · 0 reused");
    await expect(consent).not.toBeChecked();
    expect(requests).toHaveLength(2);
  } finally { await sidecar.stop(); }
});
