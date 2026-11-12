import type { Locator } from "@playwright/test";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

async function expectListFits(pane: Locator) {
  const geometry = await pane.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return {
      width: element.clientWidth,
      contentWidth: element.scrollWidth,
      outside: [...element.querySelectorAll<HTMLElement>("input, select, button, summary")]
        .filter(control => control.getClientRects().length > 0)
        .filter(control => {
          const rect = control.getBoundingClientRect();
          return rect.left < bounds.left - 1 || rect.right > bounds.left + element.clientWidth + 1;
        })
        .map(control => ({ tag: control.tagName, label: control.getAttribute("aria-label") || control.textContent?.trim(), width: control.getBoundingClientRect().width })),
    };
  });
  expect(geometry, "list content and controls must fit without horizontal scrolling or clipping").toMatchObject({ outside: [] });
  expect(geometry.contentWidth, JSON.stringify(geometry)).toBeLessThanOrEqual(geometry.width + 1);
}

for (const locale of ["zh", "en"] as const) for (const width of [1000, 900, 640, 1440]) {
  test(`account list fits with usable search and filters (${locale}, ${width})`, async ({ page }) => {
    const zh = locale === "zh";
    const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 0, 2);
    await sidecar.install(page);
    await page.route("http://127.0.0.1:43129/personal/format", async route => {
      if (route.request().method() === "OPTIONS") return route.fallback();
      await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ version: 3, current_version: 3 }) });
    });
    // This layout fixture has active entries only; the shared sidecar does not
    // model archive filtering. Supply the empty archive through the API boundary.
    await page.route("http://127.0.0.1:43129/entries?*", async route => {
      if (route.request().method() !== "GET" || new URL(route.request().url()).searchParams.get("state") !== "archived") return route.fallback();
      await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: "[]" });
    });
    await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
    await page.setViewportSize({ width, height: 700 });
    await page.goto("/");
    await page.getByLabel(zh ? "主密码" : "Master password", { exact: true }).fill(testData.masterPassword);
    await page.getByLabel(zh ? "再次输入主密码" : "Confirm master password", { exact: true }).fill(testData.masterPassword);
    await page.getByRole("button", { name: zh ? "创建并解锁" : "Create and unlock", exact: true }).click();
    await expect(page.locator(".entry-row")).toHaveCount(2);
    const pane = page.locator(".list-pane");
    const location = pane.getByRole("combobox", { name: zh ? "条目位置" : "Entry location", exact: true });
    await expect(location).toBeVisible();
    await expectListFits(pane);

    const search = page.getByLabel(zh ? "搜索保险库" : "Search vault", { exact: true });
    await search.fill("0001");
    await expect(page.locator(".entry-row")).toHaveCount(1);
    await page.getByRole("button", { name: `${zh ? "打开" : "Open"} Generated account 0001`, exact: true }).click();
    await expect(page.getByRole("article", { name: zh ? "账号详情" : "Account details" })).toBeVisible();
    if (width <= 850) await page.getByRole("button", { name: zh ? "返回密码" : "Back to passwords", exact: true }).click();
    await expectListFits(pane);
    await search.fill("");
    await expect(page.locator(".entry-row")).toHaveCount(2);

    await pane.locator("details.card > summary").click();
    await expectListFits(pane);
    await pane.getByRole("button", { name: zh ? "选择当前列表" : "Select current list", exact: true }).click();
    await expect(pane.getByRole("button", { name: zh ? "比较并合并" : "Compare and merge", exact: true })).toBeEnabled();
    await expectListFits(pane);
    await location.selectOption("archived");
    await expect(page.locator(".entry-row")).toHaveCount(0);
    await expectListFits(pane);
    await location.selectOption("active");
    await expect(page.locator(".entry-row")).toHaveCount(2);
    expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
  });
}
