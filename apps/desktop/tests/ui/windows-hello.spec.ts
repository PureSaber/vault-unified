import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

for (const locale of ["en", "zh"] as const) test(`Hello enrollment, cancellation, fallback and disable (${locale})`, async ({ page }, testInfo) => {
  const zh = locale === "zh";
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.addInitScript(({ locale, bootstrap, password }) => {
    localStorage.setItem("vault_locale", locale);
    let ready = false, cancelled = false, unlocks = 0;
    const native = { failNext: () => { cancelled = true; }, unlocks: () => unlocks };
    Object.assign(window, { isTauri: true, helloHarness: native, __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} }, __TAURI_INTERNALS__: {
      transformCallback: () => 1,
      invoke: async (command: string) => {
        if (command === "plugin:event|listen") return 1;
        if (["plugin:event|unlisten", "cancel_windows_hello"].includes(command)) return;
        if (command === "desktop_ready") return false;
        if (command === "get_desktop_status") return { preferences: { close_to_tray: true, shortcut: "Control+Shift+Space", locale }, tray_available: true, shortcut_registered: true };
        if (command === "windows_hello_status") return { supported: true, ready, busy: false };
        if (command === "disable_windows_hello") { ready = false; return; }
        if (["enable_windows_hello", "unlock_windows_hello"].includes(command)) {
          if (cancelled) { cancelled = false; throw "hello_cancelled"; }
          if (command === "enable_windows_hello") { ready = true; return { supported: true, ready, busy: false }; }
          unlocks++;
          return (await fetch("http://127.0.0.1:43129/auth/unlock", { method: "POST", headers: { "Content-Type": "application/json", "X-Vault-Bootstrap": bootstrap }, body: JSON.stringify({ password }) })).json();
        }
        throw new Error("Outside the native Hello UI fixture");
      },
    } });
  }, { locale, bootstrap: testData.bootstrapSecret, password: testData.masterPassword });
  const failNext = () => page.evaluate(() => (window as unknown as { helloHarness: { failNext: () => void } }).helloHarness.failNext());
  await page.goto("/");
  await expect(page.getByRole("button", { name: zh ? "使用 Windows Hello 解锁" : "Unlock with Windows Hello", exact: true })).toHaveCount(0);
  await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
  await page.getByRole("button", { name: zh ? "设置" : "Settings", exact: true }).click();
  const section = page.locator("section", { has: page.getByRole("heading", { name: "Windows Hello", exact: true }) });
  const enable = section.getByRole("button", { name: zh ? "为本次运行启用 Windows Hello" : "Enable Windows Hello for this run", exact: true });
  await failNext(); await enable.click();
  await expect(section.getByRole("alert")).toHaveText(zh ? "已取消 Windows Hello 验证。" : "Windows Hello verification was cancelled.");
  await enable.click();
  await expect(section.getByRole("status")).toHaveText(zh ? "本次运行已启用快速解锁。" : "Quick unlock is enabled for this run.");
  expect((await new AxeBuilder({ page }).analyze()).violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
  await section.screenshot({ path: testInfo.outputPath(`windows-hello-${locale}.png`) });
  await page.getByRole("button", { name: zh ? "立即锁定" : "Lock now", exact: true }).click();
  const hello = page.getByRole("button", { name: zh ? "使用 Windows Hello 解锁" : "Unlock with Windows Hello", exact: true });
  await failNext(); await hello.click();
  await expect(page.getByText(zh ? "已取消 Windows Hello 验证。" : "Windows Hello verification was cancelled.", { exact: true })).toBeVisible();
  await expect(page.getByLabel(zh ? "主密码" : "Master password", { exact: true })).toBeEnabled();
  await hello.click();
  await page.getByRole("button", { name: zh ? "设置" : "Settings", exact: true }).click();
  await section.getByRole("button", { name: zh ? "关闭本次快速解锁" : "Disable quick unlock", exact: true }).click();
  await expect(enable).toBeEnabled();
  expect(await page.evaluate(() => (window as unknown as { helloHarness: { unlocks: () => number } }).helloHarness.unlocks())).toBe(1);
  await page.getByRole("button", { name: zh ? "立即锁定" : "Lock now", exact: true }).click();
  await expect(hello).toHaveCount(0);
  await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: zh ? "解锁" : "Unlock", exact: true }).click();
  await expect(page.getByRole("button", { name: zh ? "添加密码" : "Add password", exact: true })).toBeVisible();
});
