import { chromium, type BrowserContext } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"] as const) test(`actual extension Passkey registration and login (${locale})`, async ({ page }, testInfo) => {
  test.setTimeout(150_000); page.setDefaultTimeout(15_000);
  const root = resolve(process.cwd(), "../..");
  const directory = await mkdtemp(join(tmpdir(), "vault-passkey-generated-"));
  const sidecar = await startGeneratedSidecar(page);
  let context: BrowserContext | undefined; let rp: ChildProcess | undefined;
  const zh = locale === "zh";
  const text = (english: string, chinese: string) => zh ? chinese : english;
  const dialog = () => page.getByRole("dialog");
  try {
    await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
    await page.goto("/");
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(text("Confirm master password", "再次输入主密码"), { exact: true }).fill(testData.masterPassword);
    const created = page.waitForResponse(response => response.url().endsWith("/auth/create"));
    await page.getByRole("button", { name: text("Create and unlock", "创建并解锁"), exact: true }).click();
    const token = (await (await created).json()).token as string;
    const headers = { "X-Vault-Bootstrap": testData.bootstrapSecret, "X-Vault-Client": "vault-unified-desktop", Authorization: `Bearer ${token}` };
    const paired = await page.request.post(`${sidecar.apiUrl}/browser/pairing-code`, { headers });
    const pairingCode = (await paired.json()).pairing_code as string;
    rp = spawn(join(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"), [join(root, "tests/helpers/passkey_rp.py")], {
      cwd: directory, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    });
    rp.stderr!.on("data", () => {});
    const port = await new Promise<number>((accept, reject) => {
      let output = "";
      const timer = setTimeout(() => reject(new Error("Generated RP startup timeout")), 10000);
      rp!.once("error", () => { clearTimeout(timer); reject(new Error("Generated RP failed to start")); });
      rp!.stdout!.on("data", chunk => { output += chunk.toString(); if (output.includes("\n")) { clearTimeout(timer); accept(JSON.parse(output.split("\n")[0]).port); } });
    });
    const origin = `http://localhost:${port}`;
    context = await chromium.launchPersistentContext(join(directory, "browser"), { channel: "chromium", headless: true,
      args: [`--disable-extensions-except=${join(root, "apps/browser-extension")}`, `--load-extension=${join(root, "apps/browser-extension")}`] });
    const manager = await context.newPage(); await manager.goto("chrome://extensions");
    const extension = manager.locator("extensions-item").filter({ hasText: "Vault Unified" }); await extension.waitFor();
    const id = await extension.getAttribute("id");
    const website = await context.newPage(); await website.goto(origin);
    const popup = await context.newPage(); await popup.goto(`chrome-extension://${id}/popup.html?lang=en`);
    const tabs = await popup.evaluate(() => (globalThis as unknown as { chrome: { tabs: { query: (options: object) => Promise<Array<{ id: number; url?: string }>> } } }).chrome.tabs.query({}));
    const tab = tabs.find(value => value.url?.startsWith(origin))!;
    await popup.goto(`chrome-extension://${id}/popup.html?tab=${tab.id}&lang=en`);
    await popup.locator("#sidecar-url").fill(sidecar.apiUrl.replace(/\/api$/, ""));
    await popup.locator("#pairing-code").fill(pairingCode);
    await popup.locator("#remember").uncheck();
    await popup.locator("#pair-form button[type=submit]").click();
    await expect(popup.locator("#pair-form")).toBeHidden();
    await popup.locator("#inline-heading").click();
    await expect(popup.locator("#passkey-enabled")).not.toBeChecked();
    await popup.locator("#inline-enable-site").click();
    await expect(popup.locator("#inline-status")).toContainText("enabled");
    await popup.locator("#passkey-enabled").check();
    await website.reload(); await website.bringToFront();

    const before = await readFile(join(sidecar.directory, "generated.vault"));
    await website.locator("#create").click();
    await expect(dialog().getByRole("heading", { name: text("Create a Passkey", "创建通行密钥") })).toBeVisible();
    await expect(dialog()).toContainText(origin);
    await dialog().getByRole("button", { name: text("Cancel", "取消"), exact: true }).click();
    await expect(website.locator("#result")).toHaveText("NotAllowedError");
    expect((await readFile(join(sidecar.directory, "generated.vault"))).equals(before)).toBe(true);

    testInfo.annotations.push({ type: "expected-request-failures", description: "2" });
    await website.locator("#create").click(); await expect(dialog()).toBeVisible();
    await page.route("**/passkeys/reject", route => route.abort("failed"));
    await dialog().getByRole("button", { name: text("Cancel", "取消"), exact: true }).click();
    await expect(dialog()).toBeHidden();
    await expect(page.getByRole("alert")).toContainText(text("Cancellation could not be confirmed", "未能确认取消结果"));
    await page.unroute("**/passkeys/reject");
    await website.locator("#abort").click(); await expect(website.locator("#result")).toHaveText("AbortError");
    expect((await readFile(join(sidecar.directory, "generated.vault"))).equals(before)).toBe(true);

    await website.locator("#create").click(); await expect(dialog()).toBeVisible();
    const findings = await new AxeBuilder({ page }).analyze();
    expect(findings.violations.filter(value => ["critical", "serious"].includes(value.impact || ""))).toEqual([]);
    if (zh) await page.screenshot({ path: testInfo.outputPath("passkey-confirmation-zh.png") });
    await dialog().getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword + "-wrong");
    await dialog().getByRole("button", { name: text("Confirm", "确认"), exact: true }).click();
    await expect(dialog().getByRole("alert")).toContainText(text("incorrect", "不正确"));
    await expect(dialog().getByLabel(text("Master password", "主密码"), { exact: true })).toHaveValue("");
    expect((await readFile(join(sidecar.directory, "generated.vault"))).equals(before)).toBe(true);
    await dialog().getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    await dialog().getByRole("button", { name: text("Confirm", "确认"), exact: true }).click();
    await expect(website.locator("#result")).toHaveText("Registered");
    await expect(website.locator("body")).toHaveAttribute("data-credential-class", "true");
    await expect(website.locator("body")).toHaveAttribute("data-response-class", "true");
    await expect(website.locator("body")).toHaveAttribute("data-algorithm", "-7");
    await expect(page.getByRole("button", { name: text("Open Generated Passkey website", "打开 Generated Passkey website"), exact: true })).toBeVisible();
    for (const mode of ["get", "discoverable"]) {
      await website.locator(`#${mode}`).click();
      await expect(dialog().getByRole("heading", { name: text("Sign in with a Passkey", "使用通行密钥登录") })).toBeVisible();
      await dialog().getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
      await dialog().getByRole("button", { name: text("Confirm", "确认"), exact: true }).click();
      await expect(website.locator("#result")).toHaveText("Signed in");
    }
    await website.locator("#create").click(); await expect(dialog()).toBeVisible();
    await website.locator("#abort").click();
    await expect(website.locator("#result")).toHaveText("AbortError");
    await expect(dialog()).toBeHidden();
    await website.locator("#timeout").click(); await expect(website.locator("#result")).toHaveText("NotAllowedError");
    await website.locator("#wrong-rp").click(); await expect(website.locator("#result")).toHaveText("SecurityError");
    await website.locator("#get").click(); await expect(dialog()).toBeVisible();
    await website.goto(origin + "/?navigated"); await expect(dialog()).toBeHidden();
    await website.goto(origin);
    await page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true }).click();
    await page.getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    const unlocked = page.waitForResponse(response => response.url().endsWith("/auth/unlock"));
    await page.getByRole("button", { name: text("Unlock", "解锁"), exact: true }).click();
    // Temporary pairing is session-scoped; explicitly pair again after unlock.
    const newToken = (await (await unlocked).json()).token as string;
    const newCode = await page.request.post(`${sidecar.apiUrl}/browser/pairing-code`, { headers: { ...headers, Authorization: `Bearer ${newToken}` } });
    await popup.reload();
    await popup.locator("#sidecar-url").fill(sidecar.apiUrl.replace(/\/api$/, ""));
    await popup.locator("#pairing-code").fill((await newCode.json()).pairing_code);
    await popup.locator("#remember").uncheck();
    await popup.locator("#pair-form button[type=submit]").click();
    await expect(popup.locator("#pair-form")).toBeHidden();
    await website.bringToFront(); await website.locator("#get").click(); await expect(dialog()).toBeVisible();
    await dialog().getByLabel(text("Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
    await dialog().getByRole("button", { name: text("Confirm", "确认"), exact: true }).click();
    await expect(website.locator("#result")).toHaveText("Signed in");
    const cdp = await context.newCDPSession(website);
    await cdp.send("WebAuthn.enable");
    await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
    // The other provider is Chrome's virtual authenticator, not a mocked Vault response.
    await website.locator("#create").click(); await expect(dialog()).toBeVisible();
    await dialog().getByRole("button", { name: text("Use the browser or another password manager", "使用浏览器或其他密码管理器"), exact: true }).click();
    await expect(website.locator("#result")).toHaveText("Registered");
    await popup.locator("#inline-heading").click(); await popup.locator("#passkey-enabled").uncheck();
    await website.bringToFront(); await website.locator("#get").click();
    await expect(website.locator("#result")).toHaveText("Signed in");
    await expect(dialog()).toBeHidden();
    const stored = await page.request.get(`${sidecar.apiUrl}/entries`, { headers: { ...headers, Authorization: `Bearer ${newToken}` } });
    expect((await stored.json()).length).toBe(1);
    await page.getByRole("button", { name: text("Open Generated Passkey website", "打开 Generated Passkey website"), exact: true }).click();
    await page.getByRole("article").getByRole("button", { name: text("Edit", "编辑"), exact: true }).click();
    await expect(page.getByRole("region", { name: text("Passkeys", "通行密钥"), exact: true })).toContainText("localhost");
    await page.getByRole("button", { name: text("Lock now", "立即锁定"), exact: true }).click();
  } finally {
    await context?.close();
    if (rp && rp.exitCode === null && rp.signalCode === null) {
      const exited = new Promise<void>(accept => rp!.once("exit", () => accept())); rp.kill(); await exited;
    }
    await sidecar.stop();
    const target = resolve(directory);
    if (dirname(target) !== resolve(tmpdir()) || !basename(target).startsWith("vault-passkey-generated-")) throw new Error("Generated Passkey cleanup boundary failed");
    await rm(target, { recursive: true, force: true, maxRetries: 3 });
  }
});
