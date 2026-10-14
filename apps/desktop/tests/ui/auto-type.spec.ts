import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"] as const) test(`application typing needs a destination and handles focus loss (${locale})`, async ({ page }, testInfo) => {
  const zh = locale === "zh";
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.addInitScript(locale => {
    localStorage.setItem("vault_locale", locale);
    const harness = { starts: 0, cancels: 0, sequence: "" };
    Object.assign(window, { isTauri: true, autoTypeHarness: harness, __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} }, __TAURI_INTERNALS__: {
      transformCallback: () => 1,
      invoke: async (command: string, args: { sequence?: string }) => {
        if (command === "plugin:event|listen") return 1;
        if (command === "plugin:event|unlisten") return;
        if (command === "desktop_ready") return false;
        if (command === "get_desktop_status") return { preferences: { close_to_tray: true, shortcut: "Control+Shift+Space", locale }, tray_available: true, shortcut_registered: true };
        if (command === "windows_hello_status") return { supported: false, ready: false, busy: false };
        if (command === "capture_type_target") return { id: "generated-target", title: "Generated sign-in window", application: "generated.exe" };
        if (command === "cancel_auto_type") { harness.cancels++; return; }
        if (command === "start_auto_type") { harness.starts++; harness.sequence = args.sequence!; throw "type_focus"; }
        throw new Error("Outside native auto-type UI fixture");
      },
    } });
  }, locale);
  await page.goto("/");
  await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
  await page.getByRole("button", { name: zh ? "添加密码" : "Add password", exact: true }).click();
  await page.getByLabel(zh ? "网站或应用名称" : "Website or app name", { exact: true }).fill("Generated typing login");
  await page.getByLabel(zh ? "用户名" : "Username", { exact: true }).fill("generated@example.invalid");
  await page.getByLabel(zh ? "密码" : "Password", { exact: true }).fill(testData.entryPassword);
  await page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click();
  await page.keyboard.press("Control+k");
  const quick = page.getByRole("dialog", { name: zh ? "快捷搜索" : "Quick search", exact: true });
  await quick.getByRole("button", { name: zh ? "输入到应用" : "Type into application", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: zh ? "输入到应用" : "Type into application", exact: true });
  const start = dialog.getByRole("button", { name: zh ? "确认并开始输入" : "Confirm and start typing", exact: true });
  await expect(start).toBeDisabled();
  const sequence = dialog.getByLabel(zh ? "输入顺序" : "Typing sequence", { exact: true });
  await expect(sequence).toHaveValue("login");
  await sequence.selectOption("password");
  await dialog.getByRole("button", { name: zh ? "选择窗口（3 秒）" : "Choose window (3 seconds)", exact: true }).click();
  await expect(dialog.getByText("Generated sign-in window", { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
  await dialog.screenshot({ path: testInfo.outputPath(`auto-type-${locale}.png`) });
  await start.click();
  await expect(dialog.getByRole("alert")).toContainText(zh ? "窗口焦点已改变" : "Window focus changed");
  await expect(start).toBeDisabled();
  expect(await page.evaluate(() => (window as unknown as { autoTypeHarness: { starts: number; sequence: string } }).autoTypeHarness)).toMatchObject({ starts: 1, sequence: "password" });
  await dialog.getByRole("button", { name: zh ? "关闭" : "Close", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (window as unknown as { autoTypeHarness: { cancels: number } }).autoTypeHarness.cancels)).toBeGreaterThan(0);
  expect(sidecar.writes).toEqual({ create: 1, update: 0, delete: 0 });
});
