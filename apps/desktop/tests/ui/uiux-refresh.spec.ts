import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { startGeneratedSidecar } from "./live-sidecar";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

for (const locale of ["zh", "en"] as const) for (const theme of ["light", "dark"] as const) {
  test(`read-only account details preserve stored data (${locale}, ${theme})`, async ({ page }, testInfo) => {
    const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 9);
    await sidecar.install(page);
    await page.addInitScript(({ locale, theme }) => { localStorage.setItem("vault_locale", locale); localStorage.setItem("vault_theme", theme); }, { locale, theme });
    await page.setViewportSize({ width: 1000, height: 700 });
    await page.goto("/");
    const zh = locale === "zh";
    await expect(page.locator("html")).toHaveAttribute("lang", zh ? "zh-CN" : "en");
    await expect(page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`onboarding-${locale}-${theme}.png`) });
    await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password").fill(testData.masterPassword);
    await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
    await expect(page.locator(".entry-row")).toHaveCount(9);
    const before = structuredClone(sidecar.persistedEntries);
    const writes = { ...sidecar.writes };
    await page.getByRole("button", { name: `${zh ? "打开" : "Open"} Generated account 0001`, exact: true }).click();
    const detail = page.getByRole("article", { name: zh ? "账号详情" : "Account details" });
    await expect(detail.getByRole("button", { name: zh ? "编辑" : "Edit", exact: true })).toBeEnabled();
    await expect(page.getByLabel(zh ? "网站或应用名称" : "Website or app name", { exact: true })).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(testData.entryPassword);
    await expect(page.locator(".badge-sync-dirty")).toHaveCount(0);
    expect(sidecar.persistedEntries).toEqual(before);
    expect(sidecar.writes).toEqual(writes);
    const axe = await new AxeBuilder({ page }).analyze();
    expect(axe.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => ({ id: item.id, nodes: item.nodes.map(node => node.target) }))).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`accounts-${locale}-${theme}.png`) });
    await detail.getByRole("button", { name: zh ? "编辑" : "Edit", exact: true }).click();
    await page.getByLabel(zh ? "网站或应用名称" : "Website or app name", { exact: true }).fill("Generated cancelled change");
    await page.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click();
    await page.getByRole("button", { name: zh ? "放弃更改" : "Discard changes", exact: true }).click();
    await expect(detail).toBeVisible();
    expect(sidecar.persistedEntries).toEqual(before);
    expect(sidecar.writes).toEqual(writes);
    await page.setViewportSize({ width: 640, height: 700 });
    await expect(detail).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    expect(overflow).toBe(false);
    await page.getByRole("button", { name: zh ? "立即锁定" : "Lock now", exact: true }).click();
    await expect(detail).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(testData.entryPassword);
  });
}

test("an internal copy and enabled-but-never-successful backup keep the reminder visible", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1);
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  await page.route("http://127.0.0.1:43129/backups", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({
      backups: [{ path: "generated/internal", kind: "local_atomic", verified: true }], count: 1,
      health: { auto_backup_enabled: true, backup_location: "generated/backup", last_success_at: "", last_error_summary: "", last_verification_status: "unverified" },
    }) });
  });
  await page.goto("/");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();
  await expect(page.getByText("Automatic backup is on; the first successful backup is still needed.")).toBeVisible();
});


test.describe("secret lifetime and feedback", () => {

  test("a delayed reveal cannot reappear after blur or selection changes", async ({ page }) => {
    const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 2);
    await sidecar.install(page);
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.goto("/");
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("Confirm master password").fill(testData.masterPassword);
    await page.getByRole("button", { name: "Create and unlock" }).click();
    await page.getByRole("button", { name: "Open Generated account 0001", exact: true }).click();
    const detail = page.getByRole("article", { name: "Account details" });
    let release: () => void = () => {};
    let received = false;
    const held = new Promise<void>(resolve => { release = resolve; });
    await page.route("**/entries/*?reveal=true", async route => {
      if (route.request().method() !== "GET") return route.fallback();
      received = true; await held; await route.fallback();
    });
    await detail.getByRole("button", { name: "Show password", exact: true }).click();
    await expect.poll(() => received).toBe(true);
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    const completed = page.waitForResponse(response => response.url().endsWith("?reveal=true") && response.ok());
    release(); await completed;
    await expect(detail.locator(".secret-value")).toHaveText("••••••••••••");
    await detail.getByRole("button", { name: "Show password", exact: true }).click();
    await expect.poll(async () => await detail.locator(".secret-value").textContent() === testData.entryPassword).toBe(true);
    await page.getByRole("button", { name: "Open Generated account 0002", exact: true }).click();
    await expect(detail.getByRole("heading", { name: "Generated account 0002" })).toBeVisible();
    expect((await page.locator("body").textContent())?.includes(testData.entryPassword)).toBe(false);
    expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
  });

  test("copy failures remain until dismissed and the system theme follows changes", async ({ page }) => {
    test.info().annotations.push({ type: "expected-request-failures", description: "1" });
    const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 1);
    await sidecar.install(page);
    await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.emulateMedia({ colorScheme: "light" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel("Confirm master password").fill(testData.masterPassword);
    await page.getByRole("button", { name: "Create and unlock" }).click();
    await page.getByRole("button", { name: "Open Generated account 0001", exact: true }).click();
    await page.route("**/entries/*/copy?field=password", async route => {
      if (route.request().method() === "OPTIONS") return route.fallback();
      await route.fulfill({ status: 500, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ detail: "Generated clipboard failure" }) });
    });
    await page.getByRole("article").getByRole("button", { name: "Copy password", exact: true }).click();
    const error = page.getByRole("alert").filter({ hasText: "Could not copy. Try again." });
    await expect(error).toBeVisible();
    await page.clock.install(); await page.clock.fastForward(20_000);
    await expect(error).toBeVisible();
    await page.getByRole("button", { name: "Dismiss notification" }).click();
    await expect(error).toHaveCount(0);
  });

  test("view, reveal and cancelled edits leave the encrypted file byte-for-byte unchanged", async ({ page }) => {
    const sidecar = await startGeneratedSidecar(page);
    try {
      await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
      await page.goto("/");
      await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
      await page.getByLabel("Confirm master password").fill(testData.masterPassword);
      await page.getByRole("button", { name: "Create and unlock" }).click();
      await page.getByRole("button", { name: "Add password", exact: true }).click();
      await page.getByLabel("Website or app name", { exact: true }).fill("Generated byte integrity");
      await page.getByLabel("Password", { exact: true }).fill(testData.entryPassword);
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByRole("button", { name: "Open Generated byte integrity", exact: true })).toBeVisible();
      await sidecar.drain();
      const digest = async () => createHash("sha256").update(await readFile(join(sidecar.directory, "generated.vault"))).digest("hex");
      const before = await digest();
      await page.getByRole("button", { name: "Open Generated byte integrity", exact: true }).click();
      const detail = page.getByRole("article");
      await detail.getByRole("button", { name: "Show password", exact: true }).click();
      await expect.poll(async () => await detail.locator(".secret-value").textContent() === testData.entryPassword).toBe(true);
      await page.evaluate(() => window.dispatchEvent(new Event("blur")));
      await expect(detail.locator(".secret-value")).toHaveText("••••••••••••");
      await detail.getByRole("button", { name: "Edit", exact: true }).click();
      await page.getByLabel("Password", { exact: true }).fill(testData.masterPassword);
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      await page.getByRole("button", { name: "Discard changes", exact: true }).click();
      await expect(detail).toBeVisible(); await sidecar.drain();
      expect(await digest() === before).toBe(true);
    } finally { await sidecar.stop(); }
  });
});
