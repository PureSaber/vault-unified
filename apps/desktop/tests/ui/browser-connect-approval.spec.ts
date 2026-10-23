import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

const request = (id: string, code: string, choices: string[]) => ({ id, device_name: "Generated Chrome on Windows", choices, remaining_seconds: 110, code });

for (const locale of ["en", "zh"] as const) test.describe(`browser connection approval (${locale})`, () => {
  const zh = locale === "zh";
  const text = (english: string, chinese: string) => zh ? chinese : english;
  const dialog = (page: Page) => page.getByRole("dialog", { name: text("Connect a browser to Vault Unified?", "要将浏览器连接到 Vault Unified 吗？") });
  const choose = (page: Page, code: string) => dialog(page).getByRole("button", { name: text(`Choose code ${code}`, `选择代码 ${code}`), exact: true });
  async function open(page: Page, sidecar: MockAuthenticatedSidecar) {
    await sidecar.install(page);
    await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
    await page.goto("/");
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(text("Confirm master password", "再次输入主密码"), { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: text("Create and unlock", "创建并解锁"), exact: true }).click();
    await expect(page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true })).toBeVisible();
  }

  test("the matching code allows the browser; the dialog never singles it out", async ({ page }, testInfo) => {
    const sidecar = new MockAuthenticatedSidecar();
    sidecar.connectRequests = [request("generated-request", "482913", ["105377", "482913", "730264"])];
    await open(page, sidecar);
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toContainText(text("Only continue if you just clicked Connect to Vault Unified in a browser.", "仅当你刚刚在浏览器中点击了“连接到 Vault Unified”时才继续。"));
    await expect(dialog(page)).toContainText(text("Browser name (reported by the browser)", "浏览器名称（由浏览器提供）"));
    await expect(dialog(page)).toContainText("Generated Chrome on Windows");
    // The safe action has focus; the three codes look the same.
    await expect(dialog(page).getByRole("button", { name: text("None of these — Deny", "都不是，拒绝"), exact: true })).toBeFocused();
    for (const code of ["105 377", "482 913", "730 264"]) await expect(choose(page, code)).toHaveClass(/secondary/);
    await expect(dialog(page).getByRole("button", { name: text("Deny all", "全部拒绝"), exact: true })).toHaveCount(0);
    expect((await new AxeBuilder({ page }).analyze()).violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await dialog(page).screenshot({ path: testInfo.outputPath(`browser-connect-${locale}.png`) });
    await choose(page, "482 913").click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(page.getByText(text("Allowed. The browser finishes connecting by itself.", "已允许。浏览器将自动完成连接。"), { exact: true })).toBeVisible();
    expect(sidecar.connectDecisions).toEqual(["approve:482913"]);
  });

  test("a wrong pick denies the request and warns", async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar();
    sidecar.connectRequests = [request("generated-request", "482913", ["105377", "482913", "730264"])];
    await open(page, sidecar);
    await choose(page, "730 264").click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(page.getByText(text("That code did not match. If you did not start this, someone else may be trying to connect.", "代码不匹配。如果不是你发起的，可能有其他程序在尝试连接。"), { exact: true })).toBeVisible();
    expect(sidecar.connectDecisions).toEqual(["approve:730264"]);
  });

  test("None of these and Escape deny; Deny all clears several requests", async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar();
    sidecar.connectRequests = [request("generated-one", "111111", ["111111", "222222", "333333"]), request("generated-two", "444444", ["555555", "444444", "666666"]),
      request("generated-three", "777777", ["888888", "999999", "777777"])];
    await open(page, sidecar);
    await expect(choose(page, "111 111")).toBeVisible();
    await dialog(page).getByRole("button", { name: text("None of these — Deny", "都不是，拒绝"), exact: true }).click();
    await expect(choose(page, "444 444")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(choose(page, "777 777")).toBeVisible();
    expect(sidecar.connectDecisions).toEqual(["deny:generated-one", "deny:generated-two"]);
    sidecar.connectRequests.push(request("generated-four", "121212", ["121212", "343434", "565656"]));
    await expect(dialog(page).getByRole("button", { name: text("Deny all", "全部拒绝"), exact: true })).toBeVisible();
    await dialog(page).getByRole("button", { name: text("Deny all", "全部拒绝"), exact: true }).click();
    await expect(dialog(page)).toHaveCount(0);
    expect(sidecar.connectDecisions).toEqual(["deny:generated-one", "deny:generated-two", "deny-all"]);
  });

  test("an expired request closes the dialog", async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar();
    sidecar.connectRequests = [request("generated-request", "482913", ["105377", "482913", "730264"])];
    await open(page, sidecar);
    await expect(dialog(page)).toBeVisible();
    sidecar.connectRequests = [];
    await expect(dialog(page)).toHaveCount(0);
    expect(sidecar.connectDecisions).toEqual([]);
  });

  test("the window comes forward once per request, and a tray lock clears pending requests", async ({ page }) => {
    // Minimal native stub: event subscription, window activation count, no Hello.
    await page.addInitScript(() => {
      let counter = 0, activations = 0;
      const callbacks = new Map<number, (value: unknown) => void>(), events = new Map<string, number>();
      Object.assign(window, { isTauri: true, nativeHarness: { activations: () => activations, emit: (event: string) => callbacks.get(events.get(event)!)?.({ event, payload: null }) },
        __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} }, __TAURI_INTERNALS__: {
          transformCallback: (callback: (value: unknown) => void) => { callbacks.set(++counter, callback); return counter; },
          invoke: async (command: string, args: { event?: string; handler?: number } = {}) => {
            if (command === "plugin:event|listen") { events.set(args.event!, args.handler!); return args.handler; }
            if (command === "plugin:event|unlisten") { events.delete(args.event!); return; }
            if (command === "show_desktop_approval") { activations++; return; }
            if (command === "desktop_ready") return false;
            if (command === "cancel_windows_hello") return;
            if (command === "windows_hello_status") return { supported: false, ready: false, busy: false };
            if (command === "get_desktop_status") return { preferences: { close_to_tray: true, shortcut: "Control+Shift+Space", locale: "en" }, tray_available: true, shortcut_registered: true };
            throw new Error("Outside the native fixture");
          },
        } });
    });
    const native = {
      activations: () => page.evaluate(() => (window as unknown as { nativeHarness: { activations: () => number } }).nativeHarness.activations()),
      emit: (event: string) => page.evaluate(value => (window as unknown as { nativeHarness: { emit: (event: string) => void } }).nativeHarness.emit(value), event),
    };
    const sidecar = new MockAuthenticatedSidecar();
    sidecar.connectRequests = [request("generated-one", "111111", ["111111", "222222", "333333"]), request("generated-two", "444444", ["555555", "444444", "666666"])];
    await open(page, sidecar);
    await expect(choose(page, "111 111")).toBeVisible();
    expect(await native.activations()).toBe(1);
    await dialog(page).getByRole("button", { name: text("None of these — Deny", "都不是，拒绝"), exact: true }).click();
    await expect(choose(page, "444 444")).toBeVisible();
    expect(await native.activations()).toBe(1);
    await native.emit("desktop-lock-requested");
    await expect(page.getByLabel(text("Master password", "主密码"), { exact: true })).toBeVisible();
    await expect(dialog(page)).toHaveCount(0);
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    const polled = page.waitForResponse(response => response.url().endsWith("/browser/connect/pending"));
    await page.getByRole("button", { name: text("Unlock", "解锁"), exact: true }).click();
    await polled;
    await expect(page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true })).toBeVisible();
    await expect(dialog(page)).toHaveCount(0);
    expect(sidecar.connectDecisions).toEqual(["deny:generated-one"]);
  });
});
