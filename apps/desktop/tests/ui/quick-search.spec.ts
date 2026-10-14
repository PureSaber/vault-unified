import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

for (const locale of ["en", "zh"] as const) test(`quick search copies with the keyboard and protects drafts (${locale})`, async ({ page }, testInfo) => {
  const zh = locale === "zh";
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
  await page.goto("/");
  await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
  for (const title of ["Generated first", "Generated second"]) {
    await page.getByRole("button", { name: zh ? "添加密码" : "Add password", exact: true }).click();
    await page.getByLabel(zh ? "网站或应用名称" : "Website or app name", { exact: true }).fill(title);
    await page.getByLabel(zh ? "用户名" : "Username", { exact: true }).fill("generated@example.invalid");
    await page.getByLabel(zh ? "密码" : "Password", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click();
  }
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: zh ? "快捷搜索" : "Quick search", exact: true });
  const query = dialog.getByRole("combobox");
  await expect(query).toBeFocused();
  await expect(dialog.getByRole("option")).toHaveCount(2);
  await query.press("ArrowDown");
  await expect(dialog.getByRole("option", { selected: true })).toContainText("Generated first");
  await query.press("Enter");
  await expect.poll(() => sidecar.copyWrites.password).toBe(1);
  await expect(dialog.getByRole("button", { name: zh ? "复制用户名" : "Copy username", exact: true })).toBeEnabled();
  await query.press("Shift+Enter");
  await expect.poll(() => sidecar.copyWrites.username).toBe(1);
  await query.fill("no matching generated account");
  await expect(dialog.getByRole("option")).toHaveCount(0);
  await query.press("Enter");
  expect(sidecar.copyWrites.password).toBe(1);
  await query.fill("Generated");
  await expect(dialog.getByRole("option")).toHaveCount(2);
  const quality = await new AxeBuilder({ page }).analyze();
  expect(quality.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
  await dialog.screenshot({ path: testInfo.outputPath(`quick-search-${locale}.png`) });
  await query.press("Escape");
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: zh ? "添加密码" : "Add password", exact: true }).click();
  const title = page.getByLabel(zh ? "网站或应用名称" : "Website or app name", { exact: true });
  await title.fill("Generated unsaved draft");
  await page.keyboard.press("Control+k");
  await expect(dialog.getByRole("option")).toHaveCount(2);
  await dialog.getByRole("button", { name: zh ? "打开条目" : "Open entry", exact: true }).click();
  await page.getByRole("button", { name: zh ? "继续编辑" : "Keep editing", exact: true }).click();
  await expect(title).toHaveValue("Generated unsaved draft");
  await page.keyboard.press("Control+k");
  await dialog.getByRole("button", { name: zh ? "打开条目" : "Open entry", exact: true }).click();
  await page.getByRole("button", { name: zh ? "放弃更改" : "Discard changes", exact: true }).click();
  await expect(title).toHaveValue("Generated second");
  expect(sidecar.writes).toEqual({ create: 2, update: 0, delete: 0 });
});

test("native event handoff queues search until unlock and guards explicit exit", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.addInitScript(() => {
    localStorage.setItem("vault_locale", "en");
    const callbacks = new Map<number, (value: unknown) => void>();
    const events = new Map<string, number>();
    let counter = 0;
    let status = { preferences: { close_to_tray: true, shortcut: "Control+Shift+Space", locale: "en" }, tray_available: true, shortcut_registered: true };
    const harness = { exits: 0, emit: (event: string) => callbacks.get(events.get(event)!)?.({ event, payload: null }), status: () => status };
    Object.assign(window, { isTauri: true, nativeHarness: harness, __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} }, __TAURI_INTERNALS__: {
      transformCallback: (callback: (value: unknown) => void) => { callbacks.set(++counter, callback); return counter; },
      invoke: async (command: string, args: { event?: string; handler?: number; preferences?: typeof status.preferences }) => {
        if (command === "plugin:event|listen") { events.set(args.event!, args.handler!); return args.handler; }
        if (command === "plugin:event|unlisten") { events.delete(args.event!); return; }
        if (command === "get_desktop_status") return status;
        if (command === "desktop_ready") return false;
        if (command === "exit_desktop") { harness.exits += 1; return; }
        if (command === "set_desktop_preferences") {
          if (args.preferences!.shortcut === "Control+Alt+KeyV") throw new Error("shortcut_unavailable");
          status = { ...status, preferences: args.preferences!, shortcut_registered: Boolean(args.preferences!.shortcut) }; return status;
        }
        throw new Error("This native command is outside the renderer test");
      },
    } });
  });
  const emit = (event: string) => page.evaluate(value => (window as unknown as { nativeHarness: { emit: (event: string) => void } }).nativeHarness.emit(value), event);
  await page.goto("/");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await emit("desktop-quick-search");
  await expect(page.getByRole("dialog", { name: "Quick search", exact: true })).toHaveCount(0);
  await page.getByLabel("Confirm master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Quick search", exact: true })).toBeVisible();
  await emit("desktop-hidden");
  await expect(page.getByRole("dialog", { name: "Quick search", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const shortcut = page.getByLabel("Global shortcut", { exact: true });
  await shortcut.selectOption("Control+Alt+KeyV");
  await expect(page.getByRole("alert").filter({ hasText: "This shortcut is in use" })).toBeVisible();
  await expect(shortcut).toHaveValue("Control+Shift+Space");
  await shortcut.selectOption("");
  await expect(shortcut).toHaveValue("");
  await page.getByRole("button", { name: "Passwords", exact: true }).click();
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  const title = page.getByLabel("Website or app name", { exact: true });
  await title.fill("Generated retained draft");
  await emit("desktop-hidden");
  await expect(title).toHaveValue("Generated retained draft");
  await emit("desktop-exit-requested");
  await page.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(title).toHaveValue("Generated retained draft");
  expect(await page.evaluate(() => (window as unknown as { nativeHarness: { exits: number } }).nativeHarness.exits)).toBe(0);
  await emit("desktop-exit-requested");
  await page.getByRole("button", { name: "Discard and close", exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { nativeHarness: { exits: number } }).nativeHarness.exits)).toBe(1);
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
  await title.fill("Generated system-lock draft");
  await emit("desktop-system-locked");
  await expect(page.getByLabel("Master password", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Keep editing", exact: true })).toHaveCount(0);
  await expect(page.getByText("Generated system-lock draft", { exact: true })).toHaveCount(0);
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
});
