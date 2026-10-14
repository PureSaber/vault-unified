import { appendFile, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { generatedWebDAV } from "./sync-storage";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"] as const) test(`two computers join, reconcile and reconnect (${locale})`, async ({ page }, testInfo) => {
  test.setTimeout(150_000); page.setDefaultTimeout(15_000);
  const zh = locale === "zh";
  const folder = await mkdtemp(join(tmpdir(), "vault-sync-generated-"));
  const server = zh ? await generatedWebDAV("generated-user", testData.entryPassword) : null;
  const source = await startGeneratedSidecar(page, { personalSync: true });
  const other = await page.context().newPage(); other.setDefaultTimeout(15_000);
  let destination: Awaited<ReturnType<typeof startGeneratedSidecar>> | undefined;
  const text = (en: string, chinese: string) => zh ? chinese : en;
  const title = "Generated synchronized account";
  const section = (target: Page) => target.getByRole("region", { name: text("Full vault sync between computers", "多电脑完整同步"), exact: true });
  async function create(target: Page) {
    await target.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
    await target.goto("/");
    await target.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    await target.getByLabel(text("Confirm master password", "再次输入主密码"), { exact: true }).fill(testData.masterPassword);
    await target.getByRole("button", { name: text("Create and unlock", "创建并解锁"), exact: true }).click();
    await expect(target.getByRole("button", { name: text("Connections", "连接"), exact: true })).toBeVisible();
  }
  async function connections(target: Page) { await target.getByRole("button", { name: text("Connections", "连接"), exact: true }).click(); }
  async function setup(target: Page, label: string, code = "") {
    await connections(target);
    const box = section(target);
    await box.getByRole("button", { name: text("Set up computer sync", "设置多电脑同步"), exact: true }).click();
    await box.getByLabel(text("Connection mode", "连接方式"), { exact: true }).selectOption(code ? "join" : "create");
    if (server) {
      await box.getByLabel("存储方式", { exact: true }).selectOption("webdav");
      await box.getByLabel("WebDAV 文件夹地址", { exact: true }).fill(server.address);
      await box.getByLabel("WebDAV 用户名", { exact: true }).fill("generated-user");
      await box.getByLabel("WebDAV 密码", { exact: true }).fill(testData.entryPassword);
    } else {
      await box.getByRole("button", { name: "Enter path manually (advanced)", exact: true }).click();
      await box.getByLabel("Synchronized folder location", { exact: true }).fill(folder);
    }
    await box.getByLabel(text("This computer's name", "这台电脑的名称"), { exact: true }).fill(label);
    if (code) await box.getByLabel(text("Connection code from another computer", "另一台电脑的连接码"), { exact: true }).fill(code);
    await box.getByRole("button", { name: text("Preview connection", "预览连接"), exact: true }).click();
    await expect(box.getByRole("region", { name: text("Sync connection preview", "同步连接预览"), exact: true })).toBeVisible();
  }
  async function apply(target: Page) {
    await section(target).getByRole("button", { name: text("Connect and apply", "连接并应用"), exact: true }).click();
    await target.getByRole("alertdialog").getByRole("button", { name: text("Confirm", "确认"), exact: true }).click();
    await expect(section(target).getByRole("button", { name: text("Sync now", "立即同步"), exact: true })).toBeVisible();
  }
  async function sync(target: Page) {
    const response = target.waitForResponse(value => value.url().endsWith("/personal-sync/run") && value.request().postDataJSON()?.automatic === false);
    await section(target).getByRole("button", { name: text("Sync now", "立即同步"), exact: true }).click();
    expect((await response).status()).toBe(200);
    await expect(section(target).getByRole("button", { name: text("Sync now", "立即同步"), exact: true })).toBeEnabled();
  }
  async function edit(target: Page, password: string) {
    await target.getByRole("button", { name: text("Passwords", "密码"), exact: true }).click();
    await target.getByRole("button", { name: text(`Open ${title}`, `打开 ${title}`), exact: true }).click();
    await target.getByLabel(text("Password", "密码"), { exact: true }).fill(password);
    await target.getByRole("button", { name: text("Save", "保存"), exact: true }).click();
    await expect(target.getByRole("button", { name: text(`Open ${title}`, `打开 ${title}`), exact: true })).toBeVisible();
  }
  try {
    await create(page);
    await page.getByRole("button", { name: text("Add password", "添加密码"), exact: true }).click();
    await page.getByLabel(text("Website or app name", "网站或应用名称"), { exact: true }).fill(title);
    await page.getByLabel(text("Password", "密码"), { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: text("Save", "保存"), exact: true }).click();
    await expect(page.getByRole("button", { name: text(`Open ${title}`, `打开 ${title}`), exact: true })).toBeVisible();
    const before = await readFile(join(source.directory, "generated.vault"));
    await setup(page, "Generated first computer");
    await section(page).getByRole("button", { name: text("Cancel connection", "取消连接"), exact: true }).click();
    expect((await readFile(join(source.directory, "generated.vault"))).equals(before)).toBe(true);
    if (server) await section(page).getByLabel("WebDAV 密码", { exact: true }).fill(testData.entryPassword);
    await section(page).getByRole("button", { name: text("Preview connection", "预览连接"), exact: true }).click();
    await apply(page); await sync(page);
    await section(page).getByText(text("Connect another computer and view devices", "连接另一台电脑与设备列表"), { exact: true }).click();
    await section(page).getByRole("button", { name: text("Reveal connection code", "显示连接码"), exact: true }).click();
    const shown = section(page).getByLabel(text("Sync connection code", "同步连接码"), { exact: true });
    await expect(shown).toBeVisible(); const code = await shown.inputValue();
    await appendFile(resolve(".playwright-runtime/secret-markers.txt"), code + "\n");
    await section(page).getByRole("button", { name: text("Hide connection code", "隐藏连接码"), exact: true }).click();

    destination = await startGeneratedSidecar(other, { personalSync: true });
    await other.clock.install();
    await create(other); await setup(other, "Generated second computer", code); await apply(other); await sync(other);
    await connections(page); await sync(page);
    await edit(page, testData.entryPassword + "-first");
    await edit(other, testData.entryPassword + "-second");
    await connections(page); await sync(page);
    await connections(other); await sync(other); await sync(page);
    await section(page).getByRole("button", { name: text("Review computer sync conflicts", "处理多电脑冲突"), exact: true }).click();
    const conflict = section(page).getByRole("region", { name: text("Review changes from other computers", "处理多电脑修改冲突"), exact: true });
    await expect(conflict.getByRole("radio", { name: new RegExp(text("Keep this computer", "保留这台电脑")) })).toHaveCount(1);
    await conflict.getByRole("radio", { name: new RegExp(text("Keep this computer", "保留这台电脑")) }).check();
    expect((await new AxeBuilder({ page }).analyze()).violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await expect(page.locator(".toast")).toHaveCount(0, { timeout: 10_000 });
    await section(page).screenshot({ path: testInfo.outputPath(`personal-sync-${locale}.png`) });
    await conflict.getByRole("button", { name: text("Confirm selected values", "确认所选内容"), exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: text("Cancel", "取消"), exact: true }).click();
    await expect(conflict.getByRole("radio", { name: new RegExp(text("Keep this computer", "保留这台电脑")) })).toBeChecked();
    await conflict.getByRole("button", { name: text("Confirm selected values", "确认所选内容"), exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: text("Confirm", "确认"), exact: true }).click();
    await expect(conflict).toContainText(text("No conflicts to resolve.", "没有待处理冲突。"));
    await sync(page); await sync(other);
    await other.getByRole("button", { name: text("Passwords", "密码"), exact: true }).click();
    await other.getByRole("button", { name: text(`Open ${title}`, `打开 ${title}`), exact: true }).click();
    await expect.poll(async () => await other.getByLabel(text("Password", "密码"), { exact: true }).inputValue() === testData.entryPassword + "-first").toBe(true);
    await connections(other);
    await section(other).getByLabel(text("Sync automatically while unlocked", "解锁期间自动同步"), { exact: true }).check();
    await section(other).getByRole("button", { name: text("Save sync settings", "保存同步设置"), exact: true }).click();
    await expect(section(other).getByRole("button", { name: text("Save sync settings", "保存同步设置"), exact: true })).toBeDisabled();
    await other.getByRole("button", { name: text("Passwords", "密码"), exact: true }).click();
    await expect(other.getByRole("button", { name: text(`Open ${title}`, `打开 ${title}`), exact: true })).toBeVisible();
    await edit(page, testData.entryPassword + "-automatic"); await connections(page); await sync(page);
    const automaticResult = other.waitForResponse(value => value.url().endsWith("/personal-sync/run") && value.request().postDataJSON()?.automatic === true);
    await other.clock.fastForward(61_000);
    expect((await automaticResult).status()).toBe(200);
    await other.getByRole("button", { name: text(`Open ${title}`, `打开 ${title}`), exact: true }).click();
    await expect.poll(async () => await other.getByLabel(text("Password", "密码"), { exact: true }).inputValue() === testData.entryPassword + "-automatic").toBe(true);
    await connections(other);
    if (server) {
      testInfo.annotations.push({ type: "expected-request-failures", description: "1" });
      server.state.offline = true;
      await section(page).getByRole("button", { name: "立即同步", exact: true }).click();
      await expect(section(page).getByRole("alert")).toBeVisible();
      server.state.offline = false; await sync(page);
    }
    await page.reload();
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: text("Unlock", "解锁"), exact: true }).click();
    await connections(page); await sync(page);
    for (const target of [page, other]) {
      await section(target).getByRole("button", { name: text("Disconnect this computer", "断开这台电脑"), exact: true }).click();
      await target.getByRole("alertdialog").getByRole("button", { name: text("Confirm", "确认"), exact: true }).click();
      await expect(section(target).getByRole("button", { name: text("Set up computer sync", "设置多电脑同步"), exact: true })).toBeVisible();
    }
  } finally {
    const stopped = await Promise.allSettled([destination?.stop(), source.stop()]);
    await other.close(); await server?.stop();
    const target = resolve(folder);
    if (dirname(target) !== resolve(tmpdir()) || !basename(target).startsWith("vault-sync-generated-")) throw new Error("Generated sync folder cleanup boundary failed");
    await rm(target, { recursive: true, force: true, maxRetries: 3 });
    for (const result of stopped) if (result.status === "rejected") throw result.reason;
  }
});
