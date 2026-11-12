import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { startGeneratedSidecar } from "./live-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off", video: "off" });

type Locale = "en" | "zh";
const titles = ["Generated race account A", "Generated race account B"];
const rendererCors = { "access-control-allow-origin": "http://127.0.0.1:1420" };
const text = (locale: Locale, en: string, zh: string) => locale === "zh" ? zh : en;
const button = (page: Page, locale: Locale, en: string, zh: string) => page.getByRole("button", { name: text(locale, en, zh), exact: true });

// The API has completed the real operation before ready resolves. Only delivery
// to the renderer is held, so the race cannot accidentally become a locked-API
// rejection instead of a late successful response.
async function holdResponse(page: Page, url: string, fail: boolean | 401 = false) {
  let release!: () => void;
  let ready!: () => void;
  let rejectReady!: (error: unknown) => void;
  const released = new Promise<void>(resolve => { release = resolve; });
  const fetched = new Promise<void>((resolve, reject) => { ready = resolve; rejectReady = reject; });
  await page.route(url, async route => {
    try {
      const response = await route.fetch();
      if (!response.ok()) throw new Error(`Generated API gate failed: ${response.status()} ${new URL(url).pathname}`);
      ready();
      await released;
      if (fail) await route.fulfill({ response, status: fail === 401 ? 401 : 500, contentType: "application/json", body: JSON.stringify({ detail: "Generated delayed organization failure" }) });
      else await route.fulfill({ response });
    } catch (error) { rejectReady(error); throw error; }
  }, { times: 1 });
  return { ready: fetched, release };
}

async function createAccounts(page: Page, locale: Locale) {
  await page.addInitScript(value => localStorage.setItem("vault_locale", value), locale);
  await page.goto("/");
  await page.getByLabel(text(locale, "Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
  await page.getByLabel(text(locale, "Confirm master password", "再次输入主密码"), { exact: true }).fill(testData.masterPassword);
  await button(page, locale, "Create and unlock", "创建并解锁").click();
  for (const title of titles) {
    await button(page, locale, "Add password", "添加密码").click();
    await page.getByLabel(text(locale, "Website or app name", "网站或应用名称"), { exact: true }).fill(title);
    await page.getByLabel(text(locale, "Username", "用户名"), { exact: true }).fill("generated-race-user");
    await page.getByLabel(text(locale, "Password", "密码"), { exact: true }).fill(testData.entryPassword);
    await page.getByLabel(text(locale, "Website address", "网站地址"), { exact: true }).fill("https://race.example.invalid/login");
    await button(page, locale, "Save", "保存").click();
    await expect(page.locator(".entry-row").filter({ hasText: title })).toBeVisible();
  }
  await page.getByText(text(locale, "Filters and bulk organization", "筛选与批量整理"), { exact: true }).click();
}

async function selectFirst(page: Page, locale: Locale) {
  await page.getByLabel(`${text(locale, "Select", "选择")} ${titles[0]}`, { exact: true }).check();
}

async function unlock(page: Page, locale: Locale) {
  await page.getByLabel(text(locale, "Master password", "主密码"), { exact: true }).fill(testData.masterPassword);
  await button(page, locale, "Unlock", "解锁").click();
  await expect(button(page, locale, "Lock now", "立即锁定")).toBeVisible();
}

// A retrying toHaveCount(0) would let a stale success toast disappear after its
// normal four-second lifetime and falsely pass. Remember every inserted toast.
async function watchForStaleFeedback(page: Page) {
  const state = await page.evaluateHandle(() => {
    const result = { appeared: 0, observer: null as MutationObserver | null };
    result.observer = new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) {
        if (node instanceof Element && (node.matches(".toast") || node.querySelector(".toast"))) result.appeared += 1;
      }
    });
    result.observer.observe(document.body, { subtree: true, childList: true });
    return result;
  });
  return async () => {
    const appeared = await state.evaluate(value => { value.observer?.disconnect(); return value.appeared; });
    await state.dispose();
    expect(appeared, "a completed old-session request must never publish a toast").toBe(0);
    expect(await page.locator(".toast").count()).toBe(0);
  };
}

for (const locale of ["en", "zh"] as const) {
  test(`${locale}: bulk selection stays frozen through preview and apply, then recovers`, async ({ page }) => {
    test.setTimeout(90_000);
    const sidecar = await startGeneratedSidecar(page);
    const gates: Awaited<ReturnType<typeof holdResponse>>[] = [];
    try {
      await createAccounts(page, locale);
      await sidecar.drain();
      await selectFirst(page, locale);
      const previews: { action: string; entry_ids: string[] }[] = [];
      const applies: { action: string; entry_ids: string[] }[] = [];
      page.on("request", request => {
        const path = new URL(request.url()).pathname;
        if (request.method() !== "POST") return;
        if (path === "/api/organization/preview") previews.push(request.postDataJSON());
        if (path === "/api/organization/apply") applies.push(request.postDataJSON());
      });
      const preview = await holdResponse(page, `${sidecar.apiUrl}/organization/preview`); gates.push(preview);
      await button(page, locale, "Archive", "归档").first().click();
      await preview.ready;
      await expect(button(page, locale, "Clear selection", "取消选择")).toBeDisabled();
      for (const title of titles) await expect(page.getByLabel(`${text(locale, "Select", "选择")} ${title}`, { exact: true })).toBeDisabled();
      preview.release();
      const dialog = page.getByRole("alertdialog");
      await expect(dialog).toContainText(titles[0]);
      await expect(dialog).not.toContainText(titles[1]);
      const apply = await holdResponse(page, `${sidecar.apiUrl}/organization/apply`); gates.push(apply);
      await dialog.getByRole("button", { name: text(locale, "Archive", "归档"), exact: true }).click();
      await apply.ready;
      await expect(dialog).toHaveCount(0);
      await expect(button(page, locale, "Clear selection", "取消选择")).toBeDisabled();
      for (const title of titles) await expect(page.getByLabel(`${text(locale, "Select", "选择")} ${title}`, { exact: true })).toBeDisabled();
      apply.release();
      await expect(page.locator(".entry-row")).toHaveCount(1);
      await expect(page.locator(".entry-row")).toContainText(titles[1]);
      await expect(button(page, locale, "Select current list", "选择当前列表")).toBeEnabled();
      await expect(page.getByLabel(`${text(locale, "Select", "选择")} ${titles[1]}`, { exact: true })).toBeEnabled();
      expect(previews.length).toBe(1);
      expect(applies.length).toBe(1);
      // Deliberately compare only non-secret plan fields, never preview tokens.
      expect(applies[0].entry_ids).toEqual(previews[0].entry_ids);
      expect(applies[0].action).toBe("archive");
      await button(page, locale, "Select current list", "选择当前列表").click();
      await button(page, locale, "Clear selection", "取消选择").click();
      await expect(page.getByLabel(`${text(locale, "Select", "选择")} ${titles[1]}`, { exact: true })).not.toBeChecked();
    } finally { gates.forEach(gate => gate.release()); await sidecar.stop(); }
  });

  test(`${locale}: lock hides entries before its response and blocks entries-changed refreshes`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    const sidecar = await startGeneratedSidecar(page);
    let gate: Awaited<ReturnType<typeof holdResponse>> | undefined;
    try {
      await createAccounts(page, locale);
      await sidecar.drain();
      gate = await holdResponse(page, `${sidecar.apiUrl}/auth/lock`);
      let entryRequests = 0;
      page.on("request", request => { if (new URL(request.url()).pathname === "/api/entries") entryRequests += 1; });
      // Exercise the same-turn interval before React can unmount the list.
      await button(page, locale, "Lock now", "立即锁定").evaluate(element => {
        element.click();
        window.dispatchEvent(new Event("vault-entries-changed"));
      });
      await gate.ready;
      await expect(page.locator(".entry-row")).toHaveCount(0);
      await expect(button(page, locale, "Unlock", "解锁")).toHaveCount(0);
      await page.evaluate(async () => {
        window.dispatchEvent(new Event("vault-entries-changed"));
        await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      });
      expect(entryRequests).toBe(0);
      const accessibility = await new AxeBuilder({ page }).analyze();
      expect(accessibility.violations.filter(item => ["serious", "critical"].includes(item.impact || "")).map(item => item.id)).toEqual([]);
      await page.locator(".app").screenshot({ path: testInfo.outputPath(`locking-${locale}.png`) });
      gate.release();
      await sidecar.drain();
      await unlock(page, locale);
      await expect(page.locator(".entry-row")).toHaveCount(2);
    } finally { gate?.release(); await sidecar.stop(); }
  });

  test(`${locale}: rejected bulk apply restores selection controls and preserves the previewed selection for retry`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    testInfo.annotations.push({ type: "expected-request-failures", description: "1" });
    const sidecar = await startGeneratedSidecar(page);
    let release!: () => void;
    const released = new Promise<void>(resolve => { release = resolve; });
    let entered!: () => void;
    const requested = new Promise<void>(resolve => { entered = resolve; });
    try {
      await createAccounts(page, locale);
      await sidecar.drain();
      await selectFirst(page, locale);
      // Reject before forwarding: the API must not have committed the archive.
      await page.route(`${sidecar.apiUrl}/organization/apply`, async route => {
        entered(); await released;
        await route.fulfill({ status: 500, headers: rendererCors, contentType: "application/json", body: JSON.stringify({ detail: "Generated apply rejection before write" }) });
      }, { times: 1 });
      await button(page, locale, "Archive", "归档").first().click();
      await page.getByRole("alertdialog").getByRole("button", { name: text(locale, "Archive", "归档"), exact: true }).click();
      await requested;
      await expect(button(page, locale, "Clear selection", "取消选择")).toBeDisabled();
      release();
      await sidecar.drain();
      await expect(page.locator(".toast-error")).toContainText("Generated apply rejection before write");
      await expect(button(page, locale, "Clear selection", "取消选择")).toBeEnabled();
      const selected = page.getByLabel(`${text(locale, "Select", "选择")} ${titles[0]}`, { exact: true });
      await expect(selected).toBeEnabled();
      await expect(selected).toBeChecked();
      await expect(page.getByLabel(`${text(locale, "Select", "选择")} ${titles[1]}`, { exact: true })).not.toBeChecked();
      await expect(page.locator(".entry-row")).toHaveCount(2);
      // Refresh through the real API to verify failure did not write either row.
      await page.evaluate(() => window.dispatchEvent(new Event("vault-entries-changed")));
      await sidecar.drain();
      await expect(page.locator(".entry-row")).toHaveCount(2);
      await expect(selected).toBeChecked();
      await page.locator(".toast-error").getByRole("button", { name: text(locale, "Dismiss notification", "关闭提示"), exact: true }).click();
      await button(page, locale, "Archive", "归档").first().click();
      await expect(page.getByRole("alertdialog")).toContainText(titles[0]);
      await expect(page.getByRole("alertdialog")).not.toContainText(titles[1]);
      await page.getByRole("alertdialog").getByRole("button", { name: text(locale, "Archive", "归档"), exact: true }).click();
      await expect(page.locator(".entry-row")).toHaveCount(1);
      await expect(page.locator(".entry-row")).toContainText(titles[1]);
      await expect(button(page, locale, "Select current list", "选择当前列表")).toBeEnabled();
    } finally { release(); await sidecar.stop(); }
  });

  test(`${locale}: favorite preview delivered after lock never starts an apply`, async ({ page }) => {
    test.setTimeout(90_000);
    const sidecar = await startGeneratedSidecar(page);
    let gate: Awaited<ReturnType<typeof holdResponse>> | undefined;
    try {
      await createAccounts(page, locale);
      await sidecar.drain();
      let applies = 0;
      page.on("request", request => {
        if (request.method() === "POST" && new URL(request.url()).pathname === "/api/organization/apply") applies += 1;
      });
      gate = await holdResponse(page, `${sidecar.apiUrl}/organization/preview`);
      const row = page.locator(".entry-row").filter({ hasText: titles[0] });
      await row.locator("summary").click();
      await row.getByRole("button", { name: text(locale, "Favorite", "收藏"), exact: true }).click();
      await gate.ready;
      await expect(button(page, locale, "Select current list", "选择当前列表")).toBeDisabled();
      await button(page, locale, "Lock now", "立即锁定").click();
      await expect(page.getByLabel(text(locale, "Master password", "主密码"), { exact: true })).toBeVisible();
      const noFeedback = await watchForStaleFeedback(page);
      gate.release();
      await sidecar.drain();
      expect(applies, "locking cancels the preview-to-apply continuation").toBe(0);
      await noFeedback();
      await unlock(page, locale);
      await expect(row).toBeVisible();
      await expect(row.getByLabel(text(locale, "Favorite", "已收藏"), { exact: true })).toHaveCount(0);
      await row.locator("summary").click();
      await row.getByRole("button", { name: text(locale, "Favorite", "收藏"), exact: true }).click();
      await expect(row.getByLabel(text(locale, "Favorite", "已收藏"), { exact: true })).toBeVisible();
      expect(applies).toBe(1);
    } finally { gate?.release(); await sidecar.stop(); }
  });

  test(`${locale}: an old-session 401 cannot lock a newly unlocked session`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    testInfo.annotations.push({ type: "expected-request-failures", description: "1" });
    const sidecar = await startGeneratedSidecar(page);
    let gate: Awaited<ReturnType<typeof holdResponse>> | undefined;
    try {
      await createAccounts(page, locale);
      await sidecar.drain();
      await selectFirst(page, locale);
      // Status injection models an old authenticated request's late rejection.
      // The real archive has committed; only its delivered status is replaced.
      gate = await holdResponse(page, `${sidecar.apiUrl}/organization/apply`, 401);
      await button(page, locale, "Archive", "归档").first().click();
      await page.getByRole("alertdialog").getByRole("button", { name: text(locale, "Archive", "归档"), exact: true }).click();
      await gate.ready;
      await button(page, locale, "Lock now", "立即锁定").click();
      await expect(page.getByLabel(text(locale, "Master password", "主密码"), { exact: true })).toBeVisible();
      await unlock(page, locale);
      await expect(page.locator(".entry-row")).toHaveCount(1);
      const noFeedback = await watchForStaleFeedback(page);
      gate.release();
      await sidecar.drain();
      expect(await button(page, locale, "Lock now", "立即锁定").count(), "a stale unauthorized response must not revoke the new renderer session").toBe(1);
      await noFeedback();
      await expect(page.locator(".entry-row")).toContainText(titles[1]);
      // Prove the new token still authenticates a real request, not just that
      // its already rendered rows survived the rejected old request.
      await page.evaluate(() => window.dispatchEvent(new Event("vault-entries-changed")));
      await sidecar.drain();
      await expect(page.locator(".entry-row")).toHaveCount(1);
      await expect(button(page, locale, "Lock now", "立即锁定")).toBeVisible();
    } finally { gate?.release(); await sidecar.stop(); }
  });

  test(`${locale}: a current-session 401 still clears the vault`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    testInfo.annotations.push({ type: "expected-request-failures", description: "1" });
    const sidecar = await startGeneratedSidecar(page);
    try {
      await createAccounts(page, locale);
      await sidecar.drain();
      await selectFirst(page, locale);
      // Status injection at the API boundary represents current auth expiry;
      // guarding stale responses must not suppress this security transition.
      await page.route(`${sidecar.apiUrl}/organization/preview`, route => route.fulfill({ status: 401, headers: rendererCors, contentType: "application/json", body: JSON.stringify({ detail: "Generated current session expired" }) }), { times: 1 });
      const noFeedback = await watchForStaleFeedback(page);
      await button(page, locale, "Archive", "归档").first().click();
      await expect(page.getByLabel(text(locale, "Master password", "主密码"), { exact: true })).toBeVisible();
      await sidecar.drain();
      expect(await page.locator(".entry-row").count()).toBe(0);
      await noFeedback();
      await unlock(page, locale);
      await expect(page.locator(".entry-row")).toHaveCount(2);
    } finally { await sidecar.stop(); }
  });

  for (const phase of ["preview-error", "apply-success", "apply-success-after-unlock", "apply-error", "favorite-error"] as const) {
    test(`${locale}: ${phase} arriving after lock cannot restore organization feedback`, async ({ page }, testInfo) => {
      test.setTimeout(90_000);
      const failure = phase === "preview-error" || phase === "apply-error" || phase === "favorite-error";
      if (failure) testInfo.annotations.push({ type: "expected-request-failures", description: "1" });
      const sidecar = await startGeneratedSidecar(page);
      let gate: Awaited<ReturnType<typeof holdResponse>> | undefined;
      try {
        await createAccounts(page, locale);
        await sidecar.drain();
        const endpoint = phase === "preview-error" ? "preview" : "apply";
        gate = await holdResponse(page, `${sidecar.apiUrl}/organization/${endpoint}`, failure);
        if (phase === "favorite-error") {
          const row = page.locator(".entry-row").filter({ hasText: titles[0] });
          await row.locator("summary").click();
          await row.getByRole("button", { name: text(locale, "Favorite", "收藏"), exact: true }).click();
        } else {
          await selectFirst(page, locale);
          await button(page, locale, "Archive", "归档").first().click();
          if (phase !== "preview-error") await page.getByRole("alertdialog").getByRole("button", { name: text(locale, "Archive", "归档"), exact: true }).click();
        }
        await gate.ready;
        await button(page, locale, "Lock now", "立即锁定").click();
        await expect(page.getByLabel(text(locale, "Master password", "主密码"), { exact: true })).toBeVisible();
        if (phase === "apply-success-after-unlock") {
          await unlock(page, locale);
          await expect(page.locator(".entry-row")).toHaveCount(1);
          await page.getByText(text(locale, "Filters and bulk organization", "筛选与批量整理"), { exact: true }).click();
          await page.getByLabel(`${text(locale, "Select", "选择")} ${titles[1]}`, { exact: true }).check();
        }
        const noFeedback = await watchForStaleFeedback(page);
        gate.release();
        await sidecar.drain();
        await noFeedback();
        await expect(page.getByRole("alertdialog")).toHaveCount(0);
        if (phase === "apply-success-after-unlock") {
          await expect(page.getByLabel(`${text(locale, "Select", "选择")} ${titles[1]}`, { exact: true })).toBeChecked();
        } else {
          await expect(page.locator(".entry-row")).toHaveCount(0);
          await unlock(page, locale);
          await page.getByText(text(locale, "Filters and bulk organization", "筛选与批量整理"), { exact: true }).click();
          await page.getByLabel(`${text(locale, "Select", "选择")} ${titles[1]}`, { exact: true }).check();
        }
        await button(page, locale, "Archive", "归档").first().click();
        await page.getByRole("alertdialog").getByRole("button", { name: text(locale, "Archive", "归档"), exact: true }).click();
        await expect(page.locator(".toast")).toContainText(text(locale, "Organization completed", "整理完成"));
        await expect(page.locator(".entry-row").filter({ hasText: titles[1] })).toHaveCount(0);
      } finally { gate?.release(); await sidecar.stop(); }
    });
  }
}

test("failed lock still clears the renderer and permits a fresh unlock", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  testInfo.annotations.push({ type: "expected-request-failures", description: "1" });
  const sidecar = await startGeneratedSidecar(page);
  let release!: () => void;
  const released = new Promise<void>(resolve => { release = resolve; });
  let entered!: () => void;
  const requested = new Promise<void>(resolve => { entered = resolve; });
  try {
    await createAccounts(page, "en");
    await sidecar.drain();
    await page.route(`${sidecar.apiUrl}/auth/lock`, async route => {
      entered(); await released;
      await route.fulfill({ status: 500, headers: rendererCors, contentType: "application/json", body: JSON.stringify({ detail: "Generated lock transport failure" }) });
    }, { times: 1 });
    await button(page, "en", "Lock now", "立即锁定").click();
    await requested;
    await expect(page.locator(".entry-row")).toHaveCount(0);
    release();
    await sidecar.drain();
    expect(await page.locator(".toast").count()).toBe(0);
    await unlock(page, "en");
    await expect(page.locator(".entry-row")).toHaveCount(2);
  } finally { release(); await sidecar.stop(); }
});

test("merge success delivered after idle lock cannot publish its old completion toast", async ({ page }) => {
  test.setTimeout(90_000);
  const sidecar = await startGeneratedSidecar(page);
  let gate: Awaited<ReturnType<typeof holdResponse>> | undefined;
  try {
    await createAccounts(page, "en");
    await sidecar.drain();
    await button(page, "en", "Select current list", "选择当前列表").click();
    await button(page, "en", "Compare and merge", "比较并合并").click();
    const dialog = page.getByRole("dialog", { name: "Compare and merge accounts" });
    await dialog.getByRole("button", { name: "Preview merge", exact: true }).click();
    gate = await holdResponse(page, `${sidecar.apiUrl}/organization/merge/apply`);
    await dialog.getByRole("button", { name: "Confirm merge", exact: true }).click();
    await gate.ready;
    // A modal blocks pointer access to Lock now. Exercise the existing idle-lock
    // path, driven by its normal settings-change event, while the modal is busy.
    await page.evaluate(() => window.dispatchEvent(new CustomEvent("vault-personal-settings-changed", { detail: { lock_after_seconds: 1 } })));
    await expect(page.getByLabel("Master password", { exact: true })).toBeVisible();
    const noFeedback = await watchForStaleFeedback(page);
    gate.release();
    await sidecar.drain();
    await noFeedback();
    await expect(dialog).toHaveCount(0);
    await unlock(page, "en");
    await expect(page.locator(".entry-row")).toHaveCount(1);
    await expect(page.locator(".entry-row")).toContainText(titles[0]);
  } finally { gate?.release(); await sidecar.stop(); }
});
