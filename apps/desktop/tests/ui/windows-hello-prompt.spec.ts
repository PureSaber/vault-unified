import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

type Harness = { failNext: () => void; enables: () => number; helloUnlocks: () => number; emit: (event: string) => void };

/** Native Hello is replaced by a per-page stub: a new page is a new app run,
 * so its quick-unlock grant starts empty exactly like the real process memory. */
async function installNative(page: Page, locale: "en" | "zh", supported = true) {
  await page.addInitScript(({ locale, supported, bootstrap, password }) => {
    localStorage.setItem("vault_locale", locale);
    let ready = false, cancelled = false, enables = 0, helloUnlocks = 0, counter = 0;
    const callbacks = new Map<number, (value: unknown) => void>(), events = new Map<string, number>();
    const harness = { failNext: () => { cancelled = true; }, enables: () => enables, helloUnlocks: () => helloUnlocks,
      emit: (event: string) => callbacks.get(events.get(event)!)?.({ event, payload: null }) };
    Object.assign(window, { isTauri: true, helloHarness: harness, __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} }, __TAURI_INTERNALS__: {
      transformCallback: (callback: (value: unknown) => void) => { callbacks.set(++counter, callback); return counter; },
      invoke: async (command: string, args: { event?: string; handler?: number } = {}) => {
        if (command === "plugin:event|listen") { events.set(args.event!, args.handler!); return args.handler; }
        if (command === "plugin:event|unlisten") { events.delete(args.event!); return; }
        if (command === "cancel_windows_hello") return;
        if (command === "desktop_ready") return false;
        if (command === "get_desktop_status") return { preferences: { close_to_tray: true, shortcut: "Control+Shift+Space", locale }, tray_available: true, shortcut_registered: true };
        if (command === "windows_hello_status") return { supported, ready, busy: false };
        if (command === "disable_windows_hello") { ready = false; return; }
        if (["enable_windows_hello", "unlock_windows_hello"].includes(command)) {
          if (cancelled) { cancelled = false; throw "hello_cancelled"; }
          if (command === "enable_windows_hello") { enables++; ready = true; return { supported: true, ready, busy: false }; }
          helloUnlocks++;
          return (await fetch("http://127.0.0.1:43129/auth/unlock", { method: "POST", headers: { "Content-Type": "application/json", "X-Vault-Bootstrap": bootstrap }, body: JSON.stringify({ password }) })).json();
        }
        throw new Error("Outside the native Hello UI fixture");
      },
    } });
  }, { locale, supported, bootstrap: testData.bootstrapSecret, password: testData.masterPassword });
}

const harness = (page: Page) => ({
  failNext: () => page.evaluate(() => (window as unknown as { helloHarness: Harness }).helloHarness.failNext()),
  enables: () => page.evaluate(() => (window as unknown as { helloHarness: Harness }).helloHarness.enables()),
  helloUnlocks: () => page.evaluate(() => (window as unknown as { helloHarness: Harness }).helloHarness.helloUnlocks()),
  emit: (event: string) => page.evaluate(value => (window as unknown as { helloHarness: Harness }).helloHarness.emit(value), event),
});

for (const locale of ["en", "zh"] as const) test.describe(`Windows Hello setup offer (${locale})`, () => {
  const zh = locale === "zh";
  const text = (english: string, chinese: string) => zh ? chinese : english;
  const offer = (page: Page) => page.getByRole("dialog", { name: text("Unlock with Windows Hello?", "使用 Windows Hello 快速解锁？") });
  const helloUnlock = (page: Page) => page.getByRole("button", { name: text("Unlock with Windows Hello", "使用 Windows Hello 解锁"), exact: true });
  const lock = (page: Page) => page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true }).click();
  const unlockWithMaster = async (page: Page) => {
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: text("Unlock", "解锁"), exact: true }).click();
    await expect(page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true })).toBeVisible();
  };
  const create = async (page: Page) => {
    await page.goto("/");
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(text("Confirm master password", "再次输入主密码"), { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: text("Create and unlock", "创建并解锁"), exact: true }).click();
  };

  test("accepting enables quick unlock for this run; Hello and later master unlocks do not ask again", async ({ page }, testInfo) => {
    const sidecar = new MockAuthenticatedSidecar(); await sidecar.install(page); await installNative(page, locale);
    await create(page);
    const dialog = offer(page);
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(text("fingerprint, face or Windows PIN", "指纹、人脸或 Windows PIN"));
    await expect(dialog).toContainText(text("After you restart the app, the master password is required first.", "重新启动应用后，仍需先输入主密码。"));
    await expect(dialog.getByRole("button", { name: text("Enable", "启用"), exact: true })).toBeFocused();
    expect((await new AxeBuilder({ page }).analyze()).violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
    await dialog.screenshot({ path: testInfo.outputPath(`hello-offer-${locale}.png`) });
    await dialog.getByRole("button", { name: text("Enable", "启用"), exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByText(text("Windows Hello quick unlock is on for this run.", "已为本次运行启用 Windows Hello 快速解锁。"), { exact: true })).toBeVisible();
    expect(await harness(page).enables()).toBe(1);
    await lock(page);
    await expect(helloUnlock(page)).toHaveClass(/primary/);
    await expect(page.getByLabel(text("Master password", "主密码"), { exact: true })).toBeEnabled();
    await helloUnlock(page).click();
    await expect(page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true })).toBeVisible();
    await expect(offer(page)).toHaveCount(0);
    await lock(page);
    await unlockWithMaster(page);
    await expect(offer(page)).toHaveCount(0);
    expect(await harness(page).enables()).toBe(1);
  });

  test("Not now lasts for the run, a restart asks again, and Don't ask again persists until Settings re-enables it", async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar(); await sidecar.install(page); await installNative(page, locale);
    await create(page);
    await offer(page).getByRole("button", { name: text("Not now", "暂不"), exact: true }).click();
    await expect(offer(page)).toHaveCount(0);
    await lock(page);
    await expect(helloUnlock(page)).toHaveCount(0);
    await unlockWithMaster(page);
    await expect(offer(page)).toHaveCount(0);

    // A new page is a new application run: storage persists, the run decline and grant do not.
    const second = await page.context().newPage(); await sidecar.install(second); await installNative(second, locale);
    await second.goto("/");
    await expect(helloUnlock(second)).toHaveCount(0);
    await unlockWithMaster(second);
    await expect(offer(second)).toBeVisible();
    await offer(second).getByRole("button", { name: text("Don't ask again", "不再询问"), exact: true }).click();
    await expect(offer(second)).toHaveCount(0);

    const third = await page.context().newPage(); await sidecar.install(third); await installNative(third, locale);
    await third.goto("/");
    await unlockWithMaster(third);
    await expect(offer(third)).toHaveCount(0);
    await third.getByRole("button", { name: text("Settings", "设置"), exact: true }).click();
    const setting = third.getByLabel(text("After I unlock with the master password, offer to turn on Windows Hello for that run", "使用主密码解锁后，询问是否为本次运行启用 Windows Hello"), { exact: true });
    await expect(setting).not.toBeChecked();
    await setting.check();
    await lock(third);
    await unlockWithMaster(third);
    await expect(offer(third)).toBeVisible();
    await third.keyboard.press("Escape");
    await expect(offer(third)).toHaveCount(0);
    expect(await harness(third).enables()).toBe(0);
  });

  test("a cancelled Windows Hello prompt explains the result and keeps password fallback", async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar(); await sidecar.install(page); await installNative(page, locale);
    await create(page);
    await harness(page).failNext();
    const dialog = offer(page);
    await dialog.getByRole("button", { name: text("Enable", "启用"), exact: true }).click();
    await expect(dialog.getByRole("alert")).toHaveText(text("Windows Hello verification was cancelled.", "已取消 Windows Hello 验证。"));
    await expect(dialog.getByRole("button", { name: text("Enable", "启用"), exact: true })).toBeEnabled();
    await dialog.getByRole("button", { name: text("Not now", "暂不"), exact: true }).click();
    await lock(page);
    await expect(helloUnlock(page)).toHaveCount(0);
    await unlockWithMaster(page);
    await expect(offer(page)).toHaveCount(0);
  });

  test("no offer when Hello is unsupported or after a saved-password unlock", async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar(); await sidecar.install(page); await installNative(page, locale, false);
    await create(page);
    await expect(page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true })).toBeVisible();
    await expect(offer(page)).toHaveCount(0);

    const saved = await page.context().newPage(); await sidecar.install(saved); await installNative(saved, locale);
    const cors = { "access-control-allow-origin": "http://127.0.0.1:1420" };
    await saved.route("http://127.0.0.1:43129/auth/check-keyring", async route => {
      if (route.request().method() === "OPTIONS") return route.fallback();
      await route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ has_saved_password: true }) });
    });
    await saved.route("http://127.0.0.1:43129/auth/unlock-keyring", async route => {
      if (route.request().method() === "OPTIONS") return route.fallback();
      // The saved credential is the master password, but no password was typed in this unlock.
      const token = await saved.evaluate(async ({ bootstrap, password }) => (await (await fetch("http://127.0.0.1:43129/auth/unlock", { method: "POST", headers: { "Content-Type": "application/json", "X-Vault-Bootstrap": bootstrap }, body: JSON.stringify({ password }) })).json()).token, { bootstrap: testData.bootstrapSecret, password: testData.masterPassword });
      await route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ token }) });
    });
    await saved.goto("/");
    await saved.getByRole("button", { name: text("Use saved password", "使用已保存密码"), exact: true }).click();
    await expect(saved.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true })).toBeVisible();
    await expect(offer(saved)).toHaveCount(0);

    // Enter on an empty field unlocks with the saved credential; that session is not master-verified.
    const empty = await page.context().newPage(); await sidecar.install(empty); await installNative(empty, locale);
    await empty.route("http://127.0.0.1:43129/auth/unlock", async route => {
      if (route.request().method() !== "POST" || route.request().postDataJSON().password !== "") return route.fallback();
      const token = await empty.evaluate(async ({ bootstrap, password }) => (await (await fetch("http://127.0.0.1:43129/auth/unlock", { method: "POST", headers: { "Content-Type": "application/json", "X-Vault-Bootstrap": bootstrap }, body: JSON.stringify({ password }) })).json()).token, { bootstrap: testData.bootstrapSecret, password: testData.masterPassword });
      await route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ token }) });
    });
    await empty.goto("/");
    await empty.getByLabel(text("Master password", "主密码"), { exact: true }).press("Enter");
    await expect(empty.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true })).toBeVisible();
    await expect(offer(empty)).toHaveCount(0);
  });

  test("locking closes the offer, focus stays trapped, Settings re-enable clears Not now, and Enter submits the master password", async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar(); await sidecar.install(page); await installNative(page, locale);
    await create(page);
    const dialog = offer(page);
    const enable = dialog.getByRole("button", { name: text("Enable", "启用"), exact: true });
    await expect(enable).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(dialog.getByRole("button", { name: text("Don't ask again", "不再询问"), exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(enable).toBeFocused();
    // A stray backdrop click neither declines nor moves focus out of the dialog.
    await page.mouse.click(5, 5);
    await expect(dialog).toBeVisible();
    await expect(enable).toBeFocused();
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press("Tab");
    await expect(enable).toBeFocused();

    // The offer covers "Lock now"; a tray or shortcut lock still reaches it.
    await harness(page).emit("desktop-lock-requested");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByLabel(text("Master password", "主密码"), { exact: true })).toBeVisible();
    await unlockWithMaster(page);
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: text("Not now", "暂不"), exact: true }).click();
    await page.getByRole("button", { name: text("Settings", "设置"), exact: true }).click();
    const setting = page.getByLabel(text("After I unlock with the master password, offer to turn on Windows Hello for that run", "使用主密码解锁后，询问是否为本次运行启用 Windows Hello"), { exact: true });
    await expect(setting).toBeChecked();
    await setting.uncheck(); await setting.check();
    await lock(page);
    await unlockWithMaster(page);
    await expect(dialog).toBeVisible();
    await enable.click();
    await expect(dialog).toHaveCount(0);

    await lock(page);
    await expect(helloUnlock(page)).toHaveClass(/primary/);
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    const typed = page.waitForRequest(request => request.url().endsWith("/auth/unlock") && request.postDataJSON().password === testData.masterPassword);
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).press("Enter");
    await typed;
    await expect(page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true })).toBeVisible();
    expect(await harness(page).helloUnlocks()).toBe(0);
    expect(await harness(page).enables()).toBe(1);
  });
});
