import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { testData } from "./test-data";

const extensionRoot = fileURLToPath(new URL("../../../browser-extension/", import.meta.url));
const popupHtml = readFileSync(`${extensionRoot}/popup.html`, "utf8")
  .replace(/<script[^>]*><\/script>/g, "")
  .replace(/<link[^>]*popup\.css[^>]*>/g, "");
const popupScript = readFileSync(`${extensionRoot}/popup.js`, "utf8");
const fillScript = readFileSync(`${extensionRoot}/fill.js`, "utf8");

async function loadPopup(
  page: Page,
  options: {
    initialState?: { sidecarUrl: string; browserToken: string } | null;
    matches?: Array<{ id: string; title: string; username: string }>;
    matchesError?: string;
    injectedReason?: string;
  } = {},
) {
  await page.setContent(popupHtml);
  await page.evaluate((config) => {
    const session: Record<string, unknown> = {};
    if (config.initialState) session.vaultUnifiedBrowserPairing = config.initialState;
    const calls = { sessionGet: 0, sessionSet: 0, sessionRemove: 0, local: 0, sync: 0 };
    const area = {
      get: async (key: string) => {
        calls.sessionGet += 1;
        return { [key]: session[key] };
      },
      set: async (value: Record<string, unknown>) => {
        calls.sessionSet += 1;
        Object.assign(session, value);
      },
      remove: async (key: string) => {
        calls.sessionRemove += 1;
        delete session[key];
      },
    };
    const forbiddenArea = {
      get: async () => { calls.local += 1; return {}; },
      set: async () => { calls.local += 1; },
      remove: async () => { calls.local += 1; },
    };
    const forbiddenSync = {
      get: async () => { calls.sync += 1; return {}; },
      set: async () => { calls.sync += 1; },
      remove: async () => { calls.sync += 1; },
    };
    Object.defineProperty(window, "chrome", {
      configurable: true,
      value: {
        storage: { session: area, local: forbiddenArea, sync: forbiddenSync },
        tabs: { query: async () => [{ id: 7, url: "https://example.invalid/login" }] },
        scripting: {
          executeScript: async () => [{ result: {
            username: config.injectedReason === "filled",
            password: config.injectedReason === "filled",
            reason: config.injectedReason || "filled",
          } }],
        },
      },
    });
    Object.defineProperty(window, "fetch", {
      configurable: true,
      value: async (input: string | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/browser/pair")) {
          return new Response(JSON.stringify({ browser_token: config.browserToken }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        if (url.includes("/api/browser/matches")) {
          if (config.matchesError) {
            return new Response(JSON.stringify({ detail: config.matchesError }), {
              status: 401,
              headers: { "content-type": "application/json" },
            });
          }
          return new Response(JSON.stringify({ matches: config.matches || [] }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        if (url.endsWith("/api/browser/fill") && init?.method === "POST") {
          return new Response(JSON.stringify({ username: "generated-user", password: config.entryPassword }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        return new Response(JSON.stringify({ detail: "Unexpected generated request" }), {
          status: 500,
          headers: { "content-type": "application/json" },
        });
      },
    });
    Object.assign(window, { __extensionMock: { session, calls } });
  }, { ...options, browserToken: testData.bearerToken, entryPassword: testData.entryPassword });
  await page.addScriptTag({ content: fillScript });
  await page.addScriptTag({ content: popupScript });
}

test("pairs only into session storage and reports no matching login", async ({ page }) => {
  await loadPopup(page);
  await page.locator("#sidecar-url").fill("http://127.0.0.1:43129");
  await page.locator("#pairing-code").fill(testData.bootstrapSecret);
  await page.getByRole("button", { name: "Pair this browser" }).click();
  await expect(page.getByText("No saved login URL matches this page.")).toBeVisible();
  const state = await page.evaluate(() => (window as unknown as {
    __extensionMock: { session: Record<string, unknown>; calls: Record<string, number> };
  }).__extensionMock);
  expect(state.session.vaultUnifiedBrowserPairing).toEqual({
    sidecarUrl: "http://127.0.0.1:43129",
    browserToken: testData.bearerToken,
  });
  expect(state.calls.sessionSet).toBe(1);
  expect(state.calls.local).toBe(0);
  expect(state.calls.sync).toBe(0);
});

test("removes session pairing immediately when the desktop reports locked", async ({ page }) => {
  await loadPopup(page, {
    initialState: { sidecarUrl: "http://127.0.0.1:43129", browserToken: testData.bearerToken },
    matchesError: "Desktop vault is locked",
  });
  await expect(page.getByText("Desktop vault is locked")).toBeVisible();
  await expect(page.getByRole("button", { name: "Pair this browser" })).toBeVisible();
  const state = await page.evaluate(() => (window as unknown as {
    __extensionMock: { session: Record<string, unknown>; calls: Record<string, number> };
  }).__extensionMock);
  expect(state.session).toEqual({});
  expect(state.calls.sessionRemove).toBe(1);
});

test("shows an explicit warning instead of success for an ambiguous page", async ({ page }) => {
  await loadPopup(page, {
    initialState: { sidecarUrl: "http://127.0.0.1:43129", browserToken: testData.bearerToken },
    matches: [{ id: "generated-entry", title: "Generated account", username: "generated-user" }],
    injectedReason: "ambiguous-password-fields",
  });
  await page.getByRole("button", { name: /Generated account/ }).click();
  await expect(page.getByText("Multiple password fields or login forms were found. Nothing was filled.")).toBeVisible();
  await expect(page.locator("#status")).toHaveClass("error");
});

async function runFill(page: Page, html: string) {
  await page.setContent(`<style>input,form,iframe,div{display:block}</style>${html}`);
  await page.addScriptTag({ content: fillScript });
  return page.evaluate((password) => (window as unknown as {
    vaultUnifiedFillInputs: (values: { username: string; password: string }) => Record<string, unknown>;
  }).vaultUnifiedFillInputs({ username: "generated-user", password }), testData.entryPassword);
}

test("fills one unambiguous login form", async ({ page }) => {
  const outcome = await runFill(page, `
    <form><input id="user" type="email" autocomplete="username"><input id="password" type="password" autocomplete="current-password"></form>
  `);
  expect(outcome).toEqual({ username: true, password: true, reason: "filled" });
  await expect(page.locator("#user")).toHaveValue("generated-user");
  await expect(page.locator("#password")).toHaveValue(testData.entryPassword);
});

test("refuses multi-form and change-password pages without changing any field", async ({ page }) => {
  const multi = await runFill(page, `
    <form><input id="user-a"><input id="password-a" type="password"></form>
    <form><input id="user-b"><input id="password-b" type="password"></form>
  `);
  expect(multi.reason).toBe("ambiguous-password-fields");
  expect(await page.locator("input").evaluateAll((items) => items.map((item) => (item as HTMLInputElement).value))).toEqual(["", "", "", ""]);

  const changed = await runFill(page, `
    <form><input id="current" type="password" autocomplete="current-password"><input id="new" type="password" autocomplete="new-password"><input id="confirm" type="password" autocomplete="new-password"></form>
  `);
  expect(changed.reason).toBe("ambiguous-password-fields");
  expect(await page.locator("input").evaluateAll((items) => items.map((item) => (item as HTMLInputElement).value))).toEqual(["", "", ""]);
});

test("reports iframe and Shadow DOM forms as unsupported", async ({ page }) => {
  const iframe = await runFill(page, "<iframe></iframe>");
  expect(iframe.reason).toBe("iframe");

  await page.setContent("<div id='host'></div>");
  await page.evaluate(() => {
    document.querySelector("#host")?.attachShadow({ mode: "open" }).append(document.createElement("input"));
  });
  await page.addScriptTag({ content: fillScript });
  const shadow = await page.evaluate((password) => (window as unknown as {
    vaultUnifiedFillInputs: (values: { username: string; password: string }) => Record<string, unknown>;
  }).vaultUnifiedFillInputs({ username: "generated-user", password }), testData.entryPassword);
  expect(shadow.reason).toBe("shadow-dom");
});
