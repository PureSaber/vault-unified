import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSharing } from "./sharing-service";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });
for (const locale of ["en", "zh"] as const) test(`real encrypted share viewer (${locale})`, async ({ page }, testInfo) => {
  const service = await startGeneratedSharing(); const zh = locale === "zh";
  const text = (en: string, cn: string) => zh ? cn : en;
  const requests: Array<{ url: string; body: string }> = [];
  page.on("request", request => requests.push({ url: request.url(), body: request.postData() || "" }));
  try {
    await page.goto(service.seedUrl);
    await page.getByLabel("Language / 语言").selectOption(locale);
    expect(new URL(page.url()).hash.length).toBe(0);
    expect(requests.filter(request => request.url.endsWith("/read"))).toHaveLength(0);
    await page.getByRole("button", { name: text("Open shared item", "打开分享内容"), exact: true }).click();
    await expect(page.getByRole("heading", { name: "Generated shared account" })).toBeVisible();
    await expect(page.locator("#fields")).toContainText("<script>unsafeMarkup()</script>");
    expect(await page.locator("#fields script").count()).toBe(0);
    const findings = await new AxeBuilder({ page }).analyze();
    expect(findings.violations.filter(value => ["critical", "serious"].includes(value.impact || ""))).toEqual([]);
    if (zh) await page.screenshot({ path: testInfo.outputPath("encrypted-share-viewer-zh.png"), fullPage: true });
    await page.getByRole("button", { name: text("Show value", "显示内容"), exact: true }).click();
    expect(await page.locator("#fields").textContent()).toContain(testData.entryPassword);
    const fragment = new URLSearchParams(new URL(service.seedUrl).hash.slice(1));
    expect(requests.every(request => !request.url.includes(fragment.get("key")!) && !request.body.includes(fragment.get("key")!))).toBe(true);
    expect(requests.every(request => !request.body.includes(testData.entryPassword))).toBe(true);
    await page.getByRole("button", { name: text("Hide content", "隐藏内容"), exact: true }).click();
    await expect(page.locator("#content")).toBeHidden();
    expect((await page.locator("body").textContent())?.includes(testData.entryPassword)).toBe(false);
    testInfo.annotations.push({ type: "expected-request-failures", description: "1" });
    await Promise.all([page.waitForEvent("load"), page.goto(service.seedUrl)]);
    await page.getByLabel("Language / 语言").selectOption(locale);
    await page.getByRole("button", { name: text("Open shared item", "打开分享内容"), exact: true }).click();
    await expect(page.getByRole("status")).toContainText(text("expired, revoked, used up", "过期、撤销、用尽次数"));
    await expect(page.locator("#content")).toBeHidden();
  } finally { await service.stop(); }
});
