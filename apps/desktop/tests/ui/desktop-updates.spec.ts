import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"] as const) test(`optional signed update confirmation and rejection (${locale})`, async ({ page }, testInfo) => {
  const sidecar = new MockAuthenticatedSidecar(); await sidecar.install(page);
  await page.addInitScript(locale => {
    localStorage.setItem("vault_locale", locale);
    const callbacks = new Map<number, (event: unknown) => void>(); let next = 0;
    let status = { preferences: { close_to_tray: true, shortcut: "Control+Shift+Space", locale, check_updates: false }, tray_available: true, shortcut_registered: true };
    const harness = { checks: 0, installs: 0, status: () => status };
    Object.assign(window, { isTauri: true, updatesHarness: harness, __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} }, __TAURI_INTERNALS__: {
      transformCallback: (fn: (event: unknown) => void) => { callbacks.set(++next, fn); return next; },
      invoke: async (command: string, args: { handler?: number; preferences?: typeof status.preferences; confirm?: boolean; version?: string }) => {
        if (command === "plugin:event|listen") return args.handler;
        if (command === "plugin:event|unlisten" || command === "cancel_windows_hello" || command === "cancel_auto_type") return;
        if (command === "get_desktop_status") return status;
        if (command === "desktop_ready") return false;
        if (command === "set_desktop_preferences") { status = { ...status, preferences: args.preferences! }; return status; }
        if (command === "windows_hello_status") return { supported: false, ready: false, busy: false };
        if (command === "update_status") return null;
        if (command === "check_desktop_update") { harness.checks++; return { version: "99.0.0", notes: "Generated update notes" }; }
        if (command === "install_desktop_update") { if (!args.confirm || args.version !== "99.0.0") throw new Error("Invalid generated consent"); harness.installs++; throw new Error("update_verification_failed"); }
        throw new Error("Native command outside this renderer fixture");
      },
    } });
  }, locale);
  const zh = locale === "zh", text = (en: string, cn: string) => zh ? cn : en;
  const counters = () => page.evaluate(() => { const h = (window as unknown as { updatesHarness: { checks: number; installs: number } }).updatesHarness; return { checks: h.checks, installs: h.installs }; });
  await page.goto("/");
  await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
  await page.getByLabel(text("Confirm master password", "再次输入主密码"), { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: text("Create and unlock", "创建并解锁"), exact: true }).click();
  await page.getByRole("button", { name: text("Settings", "设置"), exact: true }).click();
  const region = page.getByRole("region", { name: text("Application updates", "应用更新"), exact: true });
  await expect(region.getByRole("checkbox")).not.toBeChecked(); expect(await counters()).toEqual({ checks: 0, installs: 0 });
  await region.getByRole("button", { name: text("Check for updates", "检查更新"), exact: true }).click();
  await region.getByRole("button", { name: text("Review update", "查看更新确认"), exact: true }).click();
  const dialog = page.getByRole("alertdialog", { name: text("Install update", "安装更新"), exact: true });
  await dialog.getByRole("button", { name: text("Cancel", "取消"), exact: true }).click();
  expect(await counters()).toEqual({ checks: 1, installs: 0 });
  const findings = await new AxeBuilder({ page }).analyze();
  expect(findings.violations.filter(value => ["critical", "serious"].includes(value.impact || ""))).toEqual([]);
  if (zh) await page.screenshot({ path: testInfo.outputPath("desktop-updates-zh.png"), fullPage: true });
  await region.getByRole("button", { name: text("Review update", "查看更新确认"), exact: true }).click();
  await dialog.getByRole("button", { name: text("Confirm", "确认"), exact: true }).click();
  await expect(region.getByRole("status")).toContainText(text("could not be verified", "签名验证未通过"));
  expect(await counters()).toEqual({ checks: 1, installs: 1 });
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
  await region.getByRole("checkbox").check(); await expect(region.getByRole("checkbox")).toBeChecked();
  expect(await counters()).toEqual({ checks: 1, installs: 1 });
});
