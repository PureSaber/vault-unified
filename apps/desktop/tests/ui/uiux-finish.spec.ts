import type { Page } from "@playwright/test";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

async function createVault(page: Page, locale: "en" | "zh" = "en") {
  await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
  await page.goto("/");
  await page.getByLabel(locale === "zh" ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel(locale === "zh" ? "再次输入主密码" : "Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: locale === "zh" ? "创建并解锁" : "Create and unlock", exact: true }).click();
  await expect(page.getByLabel(locale === "zh" ? "搜索保险库" : "Search vault")).toBeVisible();
}

const globalNavigation = (page: Page, name: string) => page.locator("nav.nav").getByRole("button", { name, exact: true });

async function openProtection(page: Page) {
  await globalNavigation(page, "Security & recovery").click();
  // Supports the old anchor long-page layout as a reproduction precondition.
  // The task-page contract itself is asserted separately below.
  await page.locator("nav.section-nav").getByText("Automatic protection", { exact: true }).click();
  await expect(page.locator("#lock-after")).toHaveValue("900");
}

test("clipboard feedback counts down, replaces an earlier copy and clears at lock (real API)", async ({ page }) => {
  const sidecar = await startGeneratedSidecar(page);
  try {
    await createVault(page);
    await page.getByRole("button", { name: "Add password", exact: true }).click();
    await page.getByLabel("Website or app name", { exact: true }).fill("Generated countdown account");
    await page.getByLabel("Username", { exact: true }).fill("generated-countdown-user");
    await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: "Open Generated countdown account", exact: true }).click();
    const detail = page.getByRole("article", { name: "Account details" });
    const feedback = page.locator(".toast").filter({ hasText: /clipboard clears in \d+ seconds?/ });
    const seconds = async () => Number((await feedback.innerText()).match(/clipboard clears in (\d+) seconds?/)?.[1]);
    await detail.getByRole("button", { name: "Copy user", exact: true }).click();
    await expect(feedback).toHaveCount(1);
    const initial = await seconds();
    expect(initial).toBeGreaterThan(1);
    expect(initial).toBeLessThanOrEqual(45);
    await expect.poll(seconds, { timeout: 3500 }).toBeLessThan(initial);
    await expect.poll(seconds, { timeout: 3500 }).toBeLessThan(initial - 1);
    const elapsed = await seconds();
    await detail.getByRole("button", { name: "Copy user", exact: true }).click();
    await expect(feedback).toHaveCount(1);
    await expect.poll(seconds).toBeGreaterThan(elapsed);
    await expect(page.locator("body")).not.toContainText(testData.entryPassword);
    await globalNavigation(page, "Lock now").click();
    await expect(page.getByLabel("Master password", { exact: true })).toBeVisible();
    await expect(feedback).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(testData.entryPassword);
  } finally { await sidecar.stop(); }
});

test("unsaved protection settings guard global navigation and save only on explicit submission", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);
  let writes = 0;
  page.on("request", request => { if (request.method() === "PUT" && new URL(request.url()).pathname === "/personal/settings") writes++; });
  await openProtection(page);
  await page.locator("#lock-after").selectOption("300");
  await expect(page.getByText("Changes not saved", { exact: true })).toBeVisible();
  await globalNavigation(page, "Settings").click();
  const discard = page.getByRole("alertdialog", { name: "Discard unsaved changes?", exact: true });
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(page.locator("#lock-after")).toHaveValue("300");
  expect(writes).toBe(0);
  await globalNavigation(page, "Settings").click();
  await discard.getByRole("button", { name: "Discard changes", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await openProtection(page);
  expect(writes).toBe(0);
  await page.locator("#lock-after").selectOption("300");
  await page.getByRole("button", { name: "Save auto-lock and automatic-backup settings", exact: true }).click();
  await expect(page.getByText("Changes not saved", { exact: true })).toHaveCount(0);
  expect(writes).toBe(1);
  await globalNavigation(page, "Settings").click();
  await expect(discard).toHaveCount(0);
  await globalNavigation(page, "Security & recovery").click();
  await page.locator("nav.section-nav").getByRole("button", { name: "Automatic protection", exact: true }).click();
  await expect(page.locator("#lock-after")).toHaveValue("300");
});

test("security task pages show one task and guard changing tasks with unsaved protection settings", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);
  await globalNavigation(page, "Security & recovery").click();
  const sections = page.locator("nav.section-nav");
  await expect(page.getByRole("heading", { name: "Current protection status", exact: true })).toBeVisible();
  await expect(page.locator("#lock-after")).toHaveCount(0);
  await expect(page.getByLabel("Manual backup and restore")).toHaveCount(0);
  await sections.getByRole("button", { name: "Automatic protection", exact: true }).click();
  await expect(page.locator("#lock-after")).toHaveValue("900");
  await page.locator("#lock-after").selectOption("300");
  await sections.getByRole("button", { name: "Backups", exact: true }).click();
  const discard = page.getByRole("alertdialog", { name: "Discard unsaved changes?", exact: true });
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(page.locator("#lock-after")).toHaveValue("300");
  await sections.getByRole("button", { name: "Backups", exact: true }).click();
  await discard.getByRole("button", { name: "Discard changes", exact: true }).click();
  await expect(page.getByLabel("Manual backup and restore")).toBeVisible();
  await expect(page.locator("#lock-after")).toHaveCount(0);
  await sections.getByRole("button", { name: "Automatic protection", exact: true }).click();
  await expect(page.locator("#lock-after")).toHaveValue("900");
  await sections.getByRole("button", { name: "Recovery", exact: true }).click();
  await expect(page.getByRole("button", { name: "Restore from recovery kit", exact: true })).toBeVisible();
  await expect(page.getByLabel("Manual backup and restore")).toHaveCount(0);
  await expect(page.getByText(/Plaintext export is a short-lived migration file/)).toHaveCount(0);
  await sections.getByRole("button", { name: "Import and export", exact: true }).click();
  await expect(page.getByText(/Plaintext export is a short-lived migration file/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Restore from recovery kit", exact: true })).toHaveCount(0);
});

test("more options put verification codes, tags and website matching in task order and cancel without writes", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.route("http://127.0.0.1:43129/personal/format", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ version: 3, current_version: 3 }) });
  });
  await createVault(page);
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByRole("button", { name: "More options", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Website matching rules", exact: true })).toBeVisible();
  const headings = page.locator("#entry-more-options h3");
  await expect(headings).toHaveText(["Verification codes", "Tags", "Website matching rules", "Custom fields", "Attachments"]);
  await page.getByLabel("Authenticator key (TOTP key)", { exact: true }).fill(testData.entryPassword);
  await page.getByLabel("Add a tag", { exact: true }).fill("generated-tag");
  await page.getByLabel("Add a tag", { exact: true }).press("Enter");
  await page.getByLabel("Matching mode", { exact: true }).selectOption("base_domain");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Discard changes", exact: true }).click();
  await expect(page.getByLabel("Search vault")).toBeVisible();
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
  expect(sidecar.persistedEntries).toEqual([]);
});

test("sharing separates connection, limited shares and family tasks and protects an edited connection", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.route("http://127.0.0.1:43129/sharing/status", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ service: "", identity: "", shares: [], families: [], outbox: [] }) });
  });
  let writes = 0;
  page.on("request", request => { if (["POST", "PUT", "DELETE"].includes(request.method()) && new URL(request.url()).pathname.startsWith("/sharing/")) writes++; });
  await createVault(page);
  await globalNavigation(page, "Sharing").click();
  const tasks = page.locator("nav.section-nav");
  await expect(page.getByRole("combobox", { name: "Personal account", exact: true })).toBeVisible();
  await expect(page.getByLabel("Sharing service address", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("New shared vault name", { exact: true })).toHaveCount(0);
  await tasks.getByRole("button", { name: "Connection", exact: true }).click();
  const address = page.getByLabel("Sharing service address", { exact: true });
  await address.fill("https://sharing.example.invalid");
  await tasks.getByRole("button", { name: "Family vaults", exact: true }).click();
  const discard = page.getByRole("alertdialog", { name: "Discard unsaved changes?", exact: true });
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(address).toHaveValue("https://sharing.example.invalid");
  await globalNavigation(page, "Settings").click();
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(address).toHaveValue("https://sharing.example.invalid");
  await tasks.getByRole("button", { name: "Family vaults", exact: true }).click();
  await discard.getByRole("button", { name: "Discard changes", exact: true }).click();
  await expect(page.getByLabel("New shared vault name", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Personal account", exact: true })).toHaveCount(0);
  await expect(address).toHaveCount(0);
  await tasks.getByRole("button", { name: "Connection", exact: true }).click();
  await expect(address).toHaveValue("");
  expect(writes).toBe(0);
});

test("clipboard deadline is shared across copy entry points and expires even while hovered", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1);
  await sidecar.install(page);
  let duration = 8;
  await page.route("http://127.0.0.1:43129/entries/*/copy?*", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ copied: "username", clears_in_seconds: duration }) });
  });
  await createVault(page);
  await page.clock.install();
  await page.getByRole("button", { name: "Open Generated account 0001", exact: true }).click();
  await page.getByRole("article", { name: "Account details" }).getByRole("button", { name: "Copy user", exact: true }).click();
  const feedback = page.locator(".toast").filter({ hasText: /clipboard clears in \d+ seconds?/ });
  await expect(feedback).toHaveCount(1);
  await expect(feedback).toContainText(/clipboard clears in [78] seconds/);
  // The second copy uses the list action, so each component cannot own its own timer.
  duration = 2;
  await page.locator(".list-pane").getByRole("button", { name: "Copy password", exact: true }).click();
  await expect(feedback).toHaveCount(1);
  await expect(feedback).toContainText("clipboard clears in 2 seconds");
  await globalNavigation(page, "Settings").click();
  await expect(feedback).toHaveCount(1);
  await feedback.hover();
  await page.clock.fastForward(1100);
  await expect(feedback).toContainText(/clipboard clears in 1 seconds?/);
  await page.clock.fastForward(1100);
  await expect(feedback).toHaveCount(0);
  await expect(page.locator(".toast-stack")).not.toContainText(/-\d+ seconds|clipboard cleared/i);
});

test("a copy reply from the locked session cannot reappear after unlocking again", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1);
  await sidecar.install(page);
  let release!: () => void;
  let entered = false;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("http://127.0.0.1:43129/entries/*/copy?*", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    entered = true;
    await held;
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ copied: "username", clears_in_seconds: 45 }) });
  });
  await createVault(page);
  await page.getByRole("button", { name: "Open Generated account 0001", exact: true }).click();
  await page.getByRole("article", { name: "Account details" }).getByRole("button", { name: "Copy user", exact: true }).click();
  await expect.poll(() => entered).toBe(true);
  await globalNavigation(page, "Lock now").click();
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByLabel("Search vault")).toBeVisible();
  const observed = await page.evaluateHandle(() => {
    const result = { count: 0, observer: null as MutationObserver | null };
    result.observer = new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) {
        if (node instanceof Element && (node.matches(".toast") || node.querySelector(".toast"))) result.count++;
      }
    });
    result.observer.observe(document.body, { subtree: true, childList: true });
    return result;
  });
  try {
    const response = page.waitForResponse(response => /\/entries\/[^/]+\/copy\?/.test(response.url()));
    release();
    await (await response).finished();
    // Flush network continuations and React rendering without waiting long enough
    // for an incorrect transient toast to disappear unnoticed.
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    expect(await observed.evaluate(result => result.count)).toBe(0);
    expect(await page.locator(".toast").count()).toBe(0);
  } finally {
    release();
    await observed.evaluate(result => result.observer?.disconnect());
    await observed.dispose();
  }
});

for (const locale of ["en", "zh"] as const) {
  test(`${locale}: settings identify immediate and submitted changes and render translated task pages`, async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar();
    await sidecar.install(page);
    await page.route("http://127.0.0.1:43129/sharing/status", async route => {
      if (route.request().method() === "OPTIONS") return route.fallback();
      await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ service: "", identity: "", shares: [], families: [], outbox: [] }) });
    });
    const zh = locale === "zh";
    const label = (en: string, cn: string) => zh ? cn : en;
    const untranslated = /(?:Settings|Sharing|SecurityRecovery|PersonalCenter|BackupCenter|settingsSave|clipboard|sharingTask)\.[A-Za-z][A-Za-z0-9]+/;
    await createVault(page, locale);
    await globalNavigation(page, label("Settings", "设置")).click();
    const languageCard = page.getByRole("region", { name: label("Interface language", "界面语言"), exact: true });
    const appearanceCard = page.getByRole("region", { name: label("Appearance", "外观"), exact: true });
    await expect(languageCard.getByText(label("Applies immediately", "即时生效"), { exact: true })).toBeVisible();
    await expect(appearanceCard.getByText(label("Applies immediately", "即时生效"), { exact: true })).toBeVisible();
    await page.locator("#settings-theme").selectOption("dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await expect(page.locator("main")).not.toContainText(untranslated);
    // Changing language updates the central card labels in-place without a save.
    await page.locator("#settings-locale").selectOption(zh ? "en" : "zh");
    await expect(page.getByRole("region", { name: zh ? "Appearance" : "外观", exact: true })).toContainText(zh ? "Applies immediately" : "即时生效");
    await page.locator("#settings-locale").selectOption(locale);
    await globalNavigation(page, label("Security & recovery", "安全与恢复")).click();
    const tasks = page.locator("nav.section-nav");
    for (const task of [label("Overview", "概览"), label("Automatic protection", "自动保护"), label("Backups", "备份"), label("Recovery", "恢复"), label("Import and export", "导入与导出")]) {
      await tasks.getByRole("button", { name: task, exact: true }).click();
      await expect(page.locator("main")).not.toContainText(untranslated);
      if (task === label("Automatic protection", "自动保护")) {
        const protection = page.getByRole("region", { name: label("Auto-lock and scheduled backups", "自动锁定与定时备份"), exact: true });
        await expect(protection.getByText(label("Save to apply", "保存后生效"), { exact: true })).toBeVisible();
        await expect(protection.locator("#lock-after")).toHaveValue("900");
      }
    }
    await globalNavigation(page, label("Sharing", "分享")).click();
    for (const task of [label("Limited shares", "限时分享"), label("Family vaults", "家庭共享库"), label("Connection", "服务连接"), label("Pending changes", "待发送操作")]) {
      await page.locator("nav.section-nav").getByRole("button", { name: task, exact: true }).click();
      await expect(page.locator("main")).not.toContainText(untranslated);
    }
    await globalNavigation(page, label("Settings", "设置")).click();
    await expect(page.locator("#settings-theme")).toHaveValue("dark");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
  });
}

test("failed protection save preserves the draft and can be retried without falsely reporting saved", async ({ page }) => {
  test.info().annotations.push({ type: "expected-request-failures", description: "1" });
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  let attempts = 0;
  await page.route("http://127.0.0.1:43129/personal/settings", async route => {
    if (route.request().method() !== "PUT") return route.fallback();
    attempts++;
    if (attempts > 1) return route.fallback();
    await route.fulfill({ status: 500, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ detail: "Generated settings write failure" }) });
  });
  await createVault(page);
  await openProtection(page);
  const field = page.locator("#lock-after");
  const save = page.getByRole("button", { name: "Save auto-lock and automatic-backup settings", exact: true });
  await field.selectOption("300");
  await save.click();
  await expect(page.getByRole("alert").filter({ hasText: "Generated settings write failure" })).toBeVisible();
  await expect(field).toHaveValue("300");
  await expect(field).toBeEnabled();
  await expect(page.getByText("Changes not saved", { exact: true })).toBeVisible();
  await expect(page.getByText("Settings are saved; automatic backups are currently off.", { exact: true })).toHaveCount(0);
  await globalNavigation(page, "Settings").click();
  const discard = page.getByRole("alertdialog", { name: "Discard unsaved changes?", exact: true });
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(field).toHaveValue("300");
  await save.click();
  await expect(page.getByText("Settings are saved; automatic backups are currently off.", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Generated settings write failure" })).toHaveCount(0);
  expect(attempts).toBe(2);
  await globalNavigation(page, "Settings").click();
  await expect(discard).toHaveCount(0);
  await globalNavigation(page, "Security & recovery").click();
  await page.locator("nav.section-nav").getByRole("button", { name: "Automatic protection", exact: true }).click();
  await expect(field).toHaveValue("300");
});

test("a pending protection save freezes editable values and blocks leaving until the response settles", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  let release!: () => void;
  let submitted: { lock_after_seconds?: number } | undefined;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("http://127.0.0.1:43129/personal/settings", async route => {
    if (route.request().method() !== "PUT") return route.fallback();
    submitted = route.request().postDataJSON();
    await held;
    await route.fallback();
  });
  try {
    await createVault(page);
    await openProtection(page);
    const field = page.locator("#lock-after");
    await field.selectOption("300");
    await page.getByRole("button", { name: "Save auto-lock and automatic-backup settings", exact: true }).click();
    await expect.poll(() => submitted?.lock_after_seconds).toBe(300);
    await expect(field).toBeDisabled();
    await expect(page.getByLabel("Create encrypted backups while the app is unlocked", { exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Saving…", exact: true })).toBeDisabled();
    await expect(page.locator("nav.section-nav").getByRole("button", { name: "Backups", exact: true })).toBeDisabled();
    await globalNavigation(page, "Settings").click();
    await expect(page.getByRole("heading", { name: "Security & recovery", exact: true })).toBeVisible();
    await expect(page.getByText("Save in progress; please wait", { exact: true })).toBeVisible();
    await expect(field).toHaveValue("300");
    const response = page.waitForResponse(response => response.request().method() === "PUT" && response.url().endsWith("/personal/settings"));
    release();
    await response;
    await expect(field).toBeEnabled();
    await expect(page.getByText("Settings are saved; automatic backups are currently off.", { exact: true })).toBeVisible();
    await globalNavigation(page, "Settings").click();
    await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
  } finally { release(); }
});

test("a held old-session copy does not block a fresh copy or overwrite its countdown after unlock", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1);
  await sidecar.install(page);
  let release!: () => void;
  let oldEntered = false;
  let freshEntered = false;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("http://127.0.0.1:43129/entries/*/copy?*", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    const old = new URL(route.request().url()).searchParams.get("field") === "username";
    if (old) { oldEntered = true; await held; }
    else freshEntered = true;
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ copied: old ? "username" : "password", clears_in_seconds: old ? 45 : 20 }) });
  });
  try {
    await createVault(page);
    await page.getByRole("button", { name: "Open Generated account 0001", exact: true }).click();
    await page.getByRole("article", { name: "Account details" }).getByRole("button", { name: "Copy user", exact: true }).click();
    await expect.poll(() => oldEntered).toBe(true);
    await globalNavigation(page, "Lock now").click();
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: "Unlock", exact: true }).click();
    await expect(page.getByLabel("Search vault")).toBeVisible();
    await page.locator(".list-pane").getByRole("button", { name: "Copy password", exact: true }).click();
    // Keep the old response held: a global promise queue would deadlock this copy.
    await expect.poll(() => freshEntered).toBe(true);
    const feedback = page.locator(".toast").filter({ hasText: /clipboard clears in \d+ seconds?/ });
    await expect(feedback).toHaveCount(1);
    const before = Number((await feedback.innerText()).match(/clipboard clears in (\d+) seconds?/)?.[1]);
    expect(before).toBeGreaterThan(0);
    expect(before).toBeLessThanOrEqual(20);
    const observed = await page.evaluateHandle(() => {
      const result = { replacements: 0, observer: null as MutationObserver | null };
      result.observer = new MutationObserver(records => {
        for (const record of records) for (const node of record.addedNodes) {
          if (node instanceof Element && (node.matches(".toast") || node.querySelector(".toast"))) result.replacements++;
        }
      });
      result.observer.observe(document.body, { subtree: true, childList: true });
      return result;
    });
    try {
      const oldResponse = page.waitForResponse(response => response.url().includes("/copy?field=username"));
      release();
      await (await oldResponse).finished();
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(await observed.evaluate(result => result.replacements)).toBe(0);
      expect(await feedback.count()).toBe(1);
      const after = Number((await feedback.innerText()).match(/clipboard clears in (\d+) seconds?/)?.[1]);
      expect(after).toBeGreaterThan(0);
      expect(after).toBeLessThanOrEqual(before);
      expect(await page.locator(".toast-error").count()).toBe(0);
    } finally {
      await observed.evaluate(result => result.observer?.disconnect());
      await observed.dispose();
    }
  } finally { release(); }
});

test("failed protection settings load offers retry without editable defaults or a false saved status", async ({ page }) => {
  test.info().annotations.push({ type: "expected-request-failures", description: "1" });
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);
  await globalNavigation(page, "Security & recovery").click();
  await expect(page.getByRole("region", { name: "Current protection status", exact: true })).toContainText("15 minutes");
  // Fail only the task's settings load, after the overview has finished its read.
  let reads = 0;
  await page.route("http://127.0.0.1:43129/personal/settings", async route => {
    if (route.request().method() !== "GET") return route.fallback();
    reads++;
    if (reads > 1) return route.fallback();
    await route.fulfill({ status: 500, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ detail: "Generated settings load failure" }) });
  });
  await page.locator("nav.section-nav").getByRole("button", { name: "Automatic protection", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Settings could not be loaded. Retry before making changes.");
  await expect(page.locator("#lock-after")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save auto-lock and automatic-backup settings", exact: true })).toHaveCount(0);
  await expect(page.getByText("Settings are saved; automatic backups are currently off.", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.locator("#lock-after")).toHaveValue("900");
  await expect(page.getByText("Settings are saved; automatic backups are currently off.", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(reads).toBe(2);
});

test("clicking the current security navigation keeps the draft and its leave guard", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await createVault(page);
  await openProtection(page);
  await page.locator("#lock-after").selectOption("300");
  await globalNavigation(page, "Security & recovery").click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.locator("#lock-after")).toHaveValue("300");
  await globalNavigation(page, "Settings").click();
  const discard = page.getByRole("alertdialog", { name: "Discard unsaved changes?", exact: true });
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(page.locator("#lock-after")).toHaveValue("300");
});

test("a failed token-only sharing connection update reports not saved even when the old service remains configured", async ({ page }) => {
  test.info().annotations.push({ type: "expected-request-failures", description: "1" });
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  const service = "https://sharing.example.invalid";
  const stored = { service, identity: "generated-existing-sharing-identity", shares: [], families: [], outbox: [] };
  // Status never exposes the existing stored administration credential.
  await page.route("http://127.0.0.1:43129/sharing/status", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify(stored) });
  });
  let submittedReplacementOnly = false;
  await page.route("http://127.0.0.1:43129/sharing/connection", async route => {
    if (route.request().method() !== "PUT") return route.fallback();
    const submitted = route.request().postDataJSON();
    submittedReplacementOnly = submitted.server === service && submitted.admin_token === testData.entryPassword;
    await route.fulfill({ status: 500, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ detail: "Generated token storage failure" }) });
  });
  await createVault(page);
  await globalNavigation(page, "Sharing").click();
  await page.locator("nav.section-nav").getByRole("button", { name: "Connection", exact: true }).click();
  const card = page.getByRole("region", { name: "Sharing service connection", exact: true });
  await expect(card.getByText("Saved", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Sharing service address", { exact: true })).toHaveValue(service);
  const credential = page.getByLabel("Service administration token", { exact: true });
  await credential.fill(testData.entryPassword);
  await expect(card.getByText("Changes not saved", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Save service connection", exact: true }).click();
  await expect(card.getByText("Not saved. Try again.", { exact: true })).toBeVisible();
  await expect(card.getByText("Saved", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveText("Check the service administration token and Windows Credential Manager.");
  await expect(page.getByLabel("Sharing service address", { exact: true })).toHaveValue(service);
  await expect(credential).toHaveValue("");
  expect(submittedReplacementOnly).toBe(true);
  await expect(page.locator("body")).not.toContainText(testData.entryPassword);
});
