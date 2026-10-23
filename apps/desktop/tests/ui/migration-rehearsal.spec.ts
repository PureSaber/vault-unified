import { appendFile } from "node:fs/promises";
import { resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"] as const) test(`rehearse and move to an independent computer (${locale})`, async ({ page }, testInfo) => {
  test.setTimeout(90_000); page.setDefaultTimeout(15_000);
  const zh = locale === "zh";
  const source = await startGeneratedSidecar(page);
  const nextPage = await page.context().newPage(); nextPage.setDefaultTimeout(15_000);
  let destination: Awaited<ReturnType<typeof startGeneratedSidecar>> | undefined;
  try {
    await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
    await page.goto("/");
    await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
    await page.getByRole("button", { name: zh ? "添加密码" : "Add password", exact: true }).click();
    await page.getByLabel(zh ? "网站或应用名称" : "Website or app name", { exact: true }).fill("Generated portable account");
    await page.getByLabel(zh ? "密码" : "Password", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click();
    await expect(page.getByRole("button", { name: zh ? "打开 Generated portable account" : "Open Generated portable account", exact: true })).toBeVisible();
    await page.getByRole("button", { name: zh ? "安全与恢复" : "Security & recovery", exact: true }).click();
    await page.getByRole("button", { name: zh ? "创建恢复包" : "Create recovery kit", exact: true }).click();
    const codeField = page.getByLabel(zh ? "恢复码（请立即离线记录）" : "Recovery code (record offline now)", { exact: true });
    await expect(codeField).toBeVisible();
    const code = await codeField.inputValue();
    await appendFile(resolve(".playwright-runtime/secret-markers.txt"), code + "\n");
    await page.getByLabel(zh ? "重新输入恢复码以确认" : "Re-enter recovery code to confirm", { exact: true }).fill(code);
    const created = page.waitForResponse(value => value.url().endsWith("/auth/recovery-kit"));
    await page.getByRole("button", { name: zh ? "创建恢复包" : "Create recovery kit", exact: true }).click();
    const kit = (await (await created).json()).path as string;
    await expect(codeField).toHaveCount(0);
    const guide = page.getByRole("region", { name: zh ? "换电脑与恢复演练" : "Move computers and rehearse recovery", exact: true });
    await guide.getByRole("button", { name: zh ? "打开换机向导" : "Open migration guide", exact: true }).click();
    await expect(guide).toContainText(kit);
    await guide.getByLabel(zh ? "演练恢复码" : "Recovery code for rehearsal", { exact: true }).fill(code);
    await guide.getByRole("button", { name: zh ? "开始恢复演练" : "Rehearse recovery", exact: true }).click();
    await expect(guide.getByRole("status")).toContainText(zh ? "演练通过：完整数据一致，临时副本已删除。" : "Rehearsal passed: all data matched and the temporary copy was removed.");
    await expect(guide.getByLabel(zh ? "演练恢复码" : "Recovery code for rehearsal", { exact: true })).toBeEmpty();
    expect((await new AxeBuilder({ page }).analyze()).violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await expect(page.locator(".toast")).toHaveCount(0, { timeout: 10_000 });
    await guide.screenshot({ path: testInfo.outputPath(`migration-${locale}.png`) });

    destination = await startGeneratedSidecar(nextPage);
    await nextPage.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
    await nextPage.goto("/");
    await nextPage.getByRole("button", { name: zh ? "从另一台电脑迁入" : "Bring a vault from another computer", exact: true }).click();
    await nextPage.getByRole("button", { name: zh ? "手工输入路径（高级）" : "Enter path manually (advanced)", exact: true }).click();
    await nextPage.getByLabel(zh ? "恢复包文件路径" : "Recovery-kit file path", { exact: true }).fill(kit);
    async function preview() {
      await nextPage.getByLabel(zh ? "恢复码" : "Recovery code", { exact: true }).fill(code);
      await nextPage.getByLabel(zh ? "新的主密码" : "New master password", { exact: true }).fill(testData.entryPassword);
      await nextPage.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.entryPassword);
      await nextPage.getByRole("button", { name: zh ? "预览迁入" : "Preview migration", exact: true }).click();
    }
    await preview();
    const confirmation = nextPage.getByRole("alertdialog");
    await confirmation.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click();
    await expect(nextPage.getByLabel(zh ? "新的主密码" : "New master password", { exact: true })).toBeEmpty();
    await preview();
    await confirmation.getByRole("button", { name: zh ? "确认迁入" : "Confirm migration", exact: true }).click();
    await nextPage.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.entryPassword);
    await nextPage.getByRole("button", { name: zh ? "解锁" : "Unlock", exact: true }).click();
    await nextPage.getByRole("button", { name: zh ? "打开 Generated portable account" : "Open Generated portable account", exact: true }).click();
    await nextPage.getByRole("article").getByRole("button", { name: zh ? "编辑" : "Edit", exact: true }).click();
    await expect.poll(async () => await nextPage.getByLabel(zh ? "密码" : "Password", { exact: true }).inputValue() === testData.entryPassword).toBe(true);
    await page.getByRole("button", { name: zh ? "密码" : "Passwords", exact: true }).click();
    await expect(page.getByRole("button", { name: zh ? "打开 Generated portable account" : "Open Generated portable account", exact: true })).toBeVisible();
  } finally { await destination?.stop(); await nextPage.close(); await source.stop(); }
});
