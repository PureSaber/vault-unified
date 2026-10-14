import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { testData } from "./test-data";

const root = fileURLToPath(new URL("../../../browser-extension/", import.meta.url));
const source = (name: string) => readFileSync(`${root}/${name}`, "utf8");
const html = (name: string) => source(name).replace(/<script[^>]*><\/script>/g, "").replace(/<link[^>]*popup\.css[^>]*>/g, "");

for (const locale of ["zh", "en"]) test(`inline site controls request optional permission and revoke it (${locale})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 380, height: 720 });
  await page.setContent(html("popup.html"));
  await page.addStyleTag({ content: source("popup.css") });
  await page.evaluate(locale => {
    document.documentElement.lang = locale;
    (document.getElementById("language") as HTMLSelectElement).value = locale;
    document.getElementById("status")!.textContent = "";
    const state = { enabled: false, denied: false, requests: [] as string[][], actions: [] as string[] };
    Object.assign(window, { inlineFixture: state, selectedTab: async () => ({ id: 7, url: "https://example.invalid/login" }) });
    Object.defineProperty(window, "chrome", { configurable: true, value: {
      permissions: { request: async ({ origins }: { origins: string[] }) => { state.requests.push(origins); return !state.denied; } },
      runtime: { sendMessage: async (message: { type: string; action: string }) => {
        if (message.type === "vault-inline-settings") { state.actions.push(message.action); state.enabled = message.action.startsWith("enable"); }
        return { enabled: state.enabled, all: message.action === "enable-all" };
      } },
    } });
  }, locale);
  await page.addScriptTag({ content: source("inline-settings.js") });
  await page.locator("#inline-heading").click();
  await expect(page.locator("#inline-site")).toHaveValue("https://example.invalid");
  await page.locator("#inline-enable-site").click();
  await expect(page.locator("#inline-status")).toHaveText(locale === "zh" ? "此网站已开启输入框建议。" : "Suggestions are enabled for this website.");
  expect(await page.evaluate(() => (window as any).inlineFixture.requests)).toEqual([["https://example.invalid/*"]]);
  await page.evaluate(() => { (window as any).inlineFixture.denied = true; });
  await page.locator("#inline-enable-all").click();
  await expect(page.locator("#inline-status")).toHaveText(locale === "zh" ? "未授予网站权限。" : "Website permission was not granted.");
  expect(await page.evaluate(() => (window as any).inlineFixture.actions)).toEqual(["enable-site"]);
  await page.locator("#inline-disable-all").click();
  await expect(page.locator("#inline-status")).toHaveText(locale === "zh" ? "此网站的输入框建议已关闭。" : "Suggestions are off for this website.");
  const audit = await new AxeBuilder({ page }).analyze();
  expect(audit.violations.filter(value => ["serious", "critical"].includes(value.impact || ""))).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath(`inline-settings-${locale}.png`) });
});

for (const locale of ["zh", "en"]) test(`embedded website confirmation shows both origins and handles changed pages (${locale})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 480, height: 510 });
  await page.setContent(html("frame-confirm.html"));
  await page.addStyleTag({ content: source("popup.css") });
  await page.evaluate(locale => {
    Object.defineProperty(window, "chrome", { configurable: true, value: { runtime: { sendMessage: async (message: { type: string }) => {
      if (message.type === "vault-frame-info") return { origin: "https://login.example.invalid", topOrigin: "https://example.invalid", title: "Generated account", username: "generated-user", language: locale, expires: Date.now() + 60_000 };
      return { error: "pageChanged" };
    } } } });
  }, locale);
  await page.addScriptTag({ content: source("frame-confirm.js") });
  await expect(page.locator("#approve")).toBeEnabled();
  await expect(page.locator("#parent")).toHaveText("https://example.invalid");
  await expect(page.locator("#frame")).toHaveText("https://login.example.invalid");
  const audit = await new AxeBuilder({ page }).analyze();
  expect(audit.violations.filter(value => ["serious", "critical"].includes(value.impact || ""))).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath(`frame-confirm-${locale}.png`) });
  await page.locator("#approve").click();
  await expect(page.locator("#status")).toHaveText(locale === "zh" ? "确认已过期或页面已改变，请返回输入框重新选择。" : "Confirmation expired or the page changed. Choose again in the field.");
  await expect(page.locator("#approve")).toBeDisabled();
});

test("inline keyboard choice fills the selected form without submitting or exposing the closed picker to the page", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.setContent('<!doctype html><html lang="en"><head><title>Generated login</title></head><body><main><h1>Generated login</h1><form><label>Username<input autocomplete="username"></label><label>Password<input type="password" autocomplete="current-password"></label></form></main></body></html>');
  await page.evaluate(password => {
    let listener: any;
    const state = { mode: "", submitted: false };
    Object.assign(window, { inlineFixture: state, inlineCommand: () => listener({ type: "vault-inline-open" }, { id: "generated" }, () => {}) });
    document.querySelector("form")!.addEventListener("submit", event => { event.preventDefault(); state.submitted = true; });
    Object.defineProperty(window, "chrome", { configurable: true, value: { runtime: {
      id: "generated", onMessage: { addListener: (value: any) => { listener = value; } },
      sendMessage: async (message: any) => {
        if (message.type === "vault-inline-check") return { enabled: true, language: "en" };
        if (message.type === "vault-inline-matches") return { language: "en", matches: [{ id: "one", title: "Generated account", username: "generated-user" }] };
        state.mode = message.mode;
        return new Promise(resolve => listener({ type: "vault-inline-deliver", nonce: message.nonce, origin: location.origin, values: { username: "generated-user", password } }, { id: "generated" }, resolve));
      },
    } } });
  }, testData.entryPassword);
  await page.addScriptTag({ content: source("inline.js") });
  await page.getByLabel("Password", { exact: true }).click();
  await expect(page.locator('[data-picker="false"]')).toBeVisible();
  await page.evaluate(() => (window as any).inlineCommand());
  await expect(page.locator('[data-picker="true"]')).toBeVisible();
  expect(await page.locator('[data-picker="true"]').evaluate(element => element.shadowRoot)).toBeNull();
  const cdp = await page.context().newCDPSession(page);
  await expect.poll(async () => (await cdp.send("Accessibility.getFullAXTree")).nodes.some(node => node.role?.value === "button" && node.name?.value?.includes("Generated account"))).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("inline-picker-generated.png") });
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue(testData.entryPassword);
  await expect(page.getByLabel("Username", { exact: true })).toHaveValue("generated-user");
  expect(await page.evaluate(() => (window as any).inlineFixture)).toEqual({ mode: "login", submitted: false });
  await cdp.detach();
});
