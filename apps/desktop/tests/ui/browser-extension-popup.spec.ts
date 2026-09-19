import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "./journey-test";
import { testData } from "./test-data";
import AxeBuilder from "@axe-core/playwright";

const extensionRoot = fileURLToPath(new URL("../../../browser-extension/", import.meta.url));
const popupHtml = readFileSync(`${extensionRoot}/popup.html`, "utf8")
  .replace(/<script[^>]*><\/script>/g, "")
  .replace(/<link[^>]*popup\.css[^>]*>/g, "");
const popupScript = readFileSync(`${extensionRoot}/popup.js`, "utf8");
const fillScript = readFileSync(`${extensionRoot}/fill.js`, "utf8");
const popupCss = readFileSync(`${extensionRoot}/popup.css`, "utf8");

type ExtensionMockState = {
  session: Record<string, unknown>;
  locked: boolean;
  tabUrl: string;
  calls: {
    sessionGet: number;
    sessionSet: number;
    sessionRemove: number;
    local: number;
    sync: number;
    requests: string[];
    methods: string[];
    saves: number;
    previews: number;
    injections: number;
    openedWindows: string[];
  };
};

async function loadPopup(
  page: Page,
  options: {
    initialState?: { sidecarUrl: string; browserToken: string; connectionKey?: string } | null;
    matches?: Array<{ id: string; title: string; username: string }>;
    matchesError?: string;
    injectedReason?: string;
    resumeLocked?: boolean;
    saveConflict?: boolean;
  } = {},
) {
  await page.setContent(popupHtml);
  await page.evaluate((config) => {
    const session: Record<string, unknown> = {};
    if (config.initialState) session.vaultUnifiedBrowserPairing = config.initialState;
    const calls = {
      sessionGet: 0,
      sessionSet: 0,
      sessionRemove: 0,
      local: 0,
      sync: 0,
      requests: [] as string[],
      methods: [] as string[],
      saves: 0,
      previews: 0,
      injections: 0,
      openedWindows: [] as string[],
    };
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
    const mockState = { session, calls, locked: false, tabUrl: "https://example.invalid/login" };
    Object.defineProperty(window, "chrome", {
      configurable: true,
      value: {
        storage: { session: area, local: forbiddenArea, sync: forbiddenSync },
        runtime: { getURL: (path: string) => `chrome-extension://generated/${path}` },
        windows: { create: async ({ url }: { url: string }) => { calls.openedWindows.push(url); } },
        tabs: { query: async () => [{ id: 7, url: mockState.tabUrl }] },
        scripting: {
          executeScript: async ({ args }: { args: Array<{ capture?: boolean }> }) => {
            calls.injections += 1;
            return [{ result: args[0]?.capture
              ? { reason: "captured", username: "generated-user", password: config.entryPassword }
              : { username: config.injectedReason === "filled", password: config.injectedReason === "filled",
                  reason: config.injectedReason || "filled" } }];
          },
        },
      },
    });
    Object.defineProperty(window, "fetch", {
      configurable: true,
      value: async (input: string | URL, init?: RequestInit) => {
        const url = String(input);
        calls.requests.push(url);
        calls.methods.push(init?.method || "GET");
        const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
          status, headers: { "content-type": "application/json" },
        });
        if (url.endsWith("/status")) return json(mockState.locked ? { detail: "Desktop vault is locked" } : { unlocked: true }, mockState.locked ? 401 : 200);
        if (url.endsWith("/resume")) {
          if (config.resumeLocked) return json({ detail: "Desktop vault is locked" }, 423);
          config.matchesError = undefined;
          return json({ browser_token: config.browserToken });
        }
        if (url.endsWith("/disconnect")) return json({ disconnected: true });
        if (url.endsWith("/generate")) return json({ password: config.entryPassword });
        if (url.endsWith("/save/preview")) {
          calls.previews += 1;
          const draft = JSON.parse(String(init?.body));
          return json({ preview_token: "generated-preview", action: draft.entry_id ? "update" : "create",
            title: draft.title, username: draft.username, site: draft.url });
        }
        if (url.endsWith("/save/apply")) {
          if (config.saveConflict) return json({ detail: "Vault changed" }, 409);
          calls.saves += 1;
          return json({ saved: true, entry_id: "generated-entry" });
        }
        if (url.endsWith("/save/cancel")) return json({ cancelled: true });
        if (url === "http://127.0.0.1:43129/api/browser/pair") {
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
    Object.assign(window, { __extensionMock: mockState });
    Object.defineProperty(window, "close", { configurable: true, value: () => {} });
  }, { ...options, browserToken: testData.bearerToken, entryPassword: testData.entryPassword });
  await page.addScriptTag({ content: fillScript });
  await page.addScriptTag({ content: popupScript });
  await expect(page.locator("#language")).toBeEnabled();
}

test("pairs only into session storage and reports no matching login", async ({ page }) => {
  await loadPopup(page);
  await page.locator("#sidecar-url").fill("http://127.0.0.1:43129/api/");
  await page.locator("#pairing-code").fill(testData.bootstrapSecret);
  await page.getByRole("button", { name: "Pair this browser" }).click();
  await expect(page.getByText("No saved login URL matches this page.")).toBeVisible();
  const state = await page.evaluate(() => (window as unknown as {
    __extensionMock: ExtensionMockState;
  }).__extensionMock);
  expect(state.session.vaultUnifiedBrowserPairing).toEqual({
    sidecarUrl: "http://127.0.0.1:43129",
    browserToken: testData.bearerToken,
  });
  expect(state.calls.sessionSet).toBe(1);
  expect(state.calls.local).toBe(0);
  expect(state.calls.sync).toBe(0);
  expect(state.calls.requests[0]).toBe("http://127.0.0.1:43129/api/browser/pair");
  expect(state.calls.requests[1]).toContain("/api/browser/matches?");
  expect(state.calls.methods[0]).toBe("POST");
  expect(state.calls.methods[1]).toBe("POST");
  expect(state.calls.requests.some((url) => url.includes("/api/api/"))).toBe(false);
});

test("rejects unexpected local paths before sending a pairing code", async ({ page }) => {
  await loadPopup(page);
  await page.locator("#sidecar-url").fill("http://127.0.0.1:43129/unexpected");
  await page.locator("#pairing-code").fill(testData.bootstrapSecret);
  await page.getByRole("button", { name: "Pair this browser" }).click();
  await expect(page.getByText("Use the local http://127.0.0.1 address shown by Vault Unified")).toBeVisible();
  const state = await page.evaluate(() => (window as unknown as {
    __extensionMock: ExtensionMockState;
  }).__extensionMock);
  expect(state.calls.requests).toEqual([]);
  expect(state.calls.sessionSet).toBe(0);
});

test("removes session pairing immediately when the desktop reports locked", async ({ page }) => {
  await loadPopup(page, {
    initialState: { sidecarUrl: "http://127.0.0.1:43129", browserToken: testData.bearerToken },
    matchesError: "Desktop vault is locked",
  });
  await expect(page.getByText("Pairing expired. Create a new pairing code in the desktop app.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Pair this browser" })).toBeVisible();
  const state = await page.evaluate(() => (window as unknown as {
    __extensionMock: ExtensionMockState;
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
  await page.locator("button.match").click();
  await expect(page.getByText("Multiple password fields or login forms were found. Nothing was filled.")).toBeVisible();
  await expect(page.locator("#status")).toHaveClass("error");
});

async function runFill(page: Page, html: string) {
  await page.setContent(`<style>input,form,iframe,div{display:block}</style>${html}`);
  await page.addScriptTag({ content: fillScript });
  return page.evaluate((password) => (window as unknown as {
    vaultUnifiedFillInputs: (values: { username: string; password: string; pageOrigin: string }) => Record<string, unknown>;
  }).vaultUnifiedFillInputs({ username: "generated-user", password, pageOrigin: location.origin }), testData.entryPassword);
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
    vaultUnifiedFillInputs: (values: { username: string; password: string; pageOrigin: string }) => Record<string, unknown>;
  }).vaultUnifiedFillInputs({ username: "generated-user", password, pageOrigin: location.origin }), testData.entryPassword);
  expect(shadow.reason).toBe("shadow-dom");
});

const pairedState = () => ({ sidecarUrl: "http://127.0.0.1:43129", browserToken: testData.bearerToken });
const mock = (page: Page) => page.evaluate(() => (window as unknown as {
  __extensionMock: ExtensionMockState;
}).__extensionMock);

test("resumes after unlock without asking for another pairing code", async ({ page }) => {
  await loadPopup(page, {
    initialState: { ...pairedState(), connectionKey: testData.bootstrapSecret },
    matchesError: "Desktop vault is locked",
  });
  await expect(page.locator("#accounts")).toBeVisible();
  await expect(page.locator("#pair-form")).toBeHidden();
  expect((await mock(page)).calls.requests.some((url) => url.endsWith("/resume"))).toBe(true);
});

test("keeps remembered connection while locked and offers reconnect", async ({ page }) => {
  const state = { ...pairedState(), connectionKey: testData.bootstrapSecret };
  await loadPopup(page, { initialState: state, matchesError: "Desktop vault is locked", resumeLocked: true });
  await expect(page.locator("#retry")).toBeVisible();
  await expect(page.locator("#pair-form")).toBeHidden();
  expect((await mock(page)).session.vaultUnifiedBrowserPairing).toEqual(state);
});

test("opens a separate window bound to the selected tab without credentials in its URL", async ({ page }) => {
  await loadPopup(page, { initialState: pairedState() });
  await page.getByRole("button", { name: "Open a window for registration / password changes" }).click();
  expect((await mock(page)).calls.openedWindows).toEqual(["chrome-extension://generated/popup.html?tab=7&lang=en"]);
});

test("reads an account only on request and saves after preview and explicit confirmation", async ({ page }) => {
  await loadPopup(page, { initialState: pairedState() });
  expect((await mock(page)).calls.injections).toBe(0);
  await page.getByRole("button", { name: "Read login from this page" }).click();
  await expect(page.locator("#save-password")).toHaveValue(testData.entryPassword);
  await page.getByRole("button", { name: "Review saving" }).click();
  await expect(page.locator("#save-preview")).toBeVisible();
  expect((await mock(page)).calls.saves).toBe(0);
  await page.getByRole("button", { name: "Confirm save", exact: true }).click();
  await expect(page.locator("#status")).toHaveText("Confirm that the website accepts this password before saving.");
  expect((await mock(page)).calls.saves).toBe(0);
  await page.locator("#confirmed").check();
  await page.getByRole("button", { name: "Confirm save", exact: true }).click();
  await expect(page.locator("#status")).toHaveText("Account saved to the local vault.");
  await expect(page.locator("#save-password")).toHaveValue("");
  const state = await mock(page);
  expect(state.calls.saves).toBe(1);
  expect(JSON.stringify(state.session).includes(testData.entryPassword)).toBe(false);
  expect(state.calls.local + state.calls.sync).toBe(0);
});

test("cancel clears the draft without sending a save", async ({ page }) => {
  await loadPopup(page, { initialState: pairedState() });
  await page.getByRole("button", { name: "Add manually" }).click();
  await page.locator("#save-password").fill(testData.entryPassword);
  await page.getByRole("button", { name: "Review saving" }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.locator("#save-password")).toHaveValue("");
  await expect(page.locator("#save-form")).toBeHidden();
  expect((await mock(page)).calls.saves).toBe(0);
});

test("lock clears a visible password and preview instead of preserving a draft", async ({ page }) => {
  await loadPopup(page, { initialState: { ...pairedState(), connectionKey: testData.bootstrapSecret } });
  await page.getByRole("button", { name: "Add manually" }).click();
  await page.locator("#save-password").fill(testData.entryPassword);
  await page.getByRole("button", { name: "Show password" }).click();
  await page.evaluate(() => { (window as unknown as { __extensionMock: ExtensionMockState }).__extensionMock.locked = true; });
  await expect(page.locator("#retry")).toBeVisible();
  await expect(page.locator("#save-password")).toHaveValue("");
  await expect(page.locator("#save-password")).toHaveAttribute("type", "password");
  expect((await mock(page)).calls.saves).toBe(0);
});

test("stale update returns to editing without claiming success", async ({ page }) => {
  await loadPopup(page, { initialState: pairedState(), saveConflict: true,
    matches: [{ id: "generated-entry", title: "Account", username: "generated-user" }] });
  await page.getByRole("button", { name: "Update Account generated-user" }).click();
  await page.locator("#save-password").fill(testData.entryPassword);
  await page.getByRole("button", { name: "Review saving" }).click();
  await page.locator("#confirmed").check();
  await page.getByRole("button", { name: "Confirm save", exact: true }).click();
  await expect(page.locator("#draft-fields")).toBeVisible();
  await expect(page.locator("#status")).toHaveText("The account or vault changed. Review saving again.");
  expect((await mock(page)).calls.saves).toBe(0);
});

test("page navigation prevents filling or saving the previous site's account", async ({ page }) => {
  await loadPopup(page, { initialState: pairedState(),
    matches: [{ id: "generated-entry", title: "Account", username: "generated-user" }] });
  await page.evaluate(() => { (window as unknown as { __extensionMock: ExtensionMockState }).__extensionMock.tabUrl = "https://other.invalid"; });
  await page.locator("button.match").click();
  await expect(page.locator("#status")).toHaveText("The page changed. Reopen the extension before continuing.");
  expect((await mock(page)).calls.injections).toBe(0);
});

test("Chinese save flow is accessible and keyboard reachable", async ({ page }, testInfo) => {
  await loadPopup(page, { initialState: pairedState() });
  await page.addStyleTag({ content: popupCss });
  await page.locator("#language").selectOption("zh");
  await page.getByRole("button", { name: "手动添加", exact: true }).click();
  await expect(page.locator("#save-heading")).toHaveText("保存账号");
  await page.locator("#save-password").fill(testData.entryPassword);
  await page.locator("#review").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#save-preview")).toBeVisible();
  await expect(page.locator("#confirmed")).toBeFocused();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("browser-save-zh.png"),
    mask: [page.locator("#save-password")] });
});

test("reads only matching new-password fields and preserves the current password when filling", async ({ page }) => {
  await page.setContent('<form><input id="user" autocomplete="username"><input id="old" type="password" autocomplete="current-password"><input id="new" type="password" autocomplete="new-password"><input id="confirm" type="password" autocomplete="new-password"></form>');
  await page.addScriptTag({ content: fillScript });
  await page.locator("#old").fill(testData.masterPassword);
  await page.locator("#new").fill(testData.entryPassword);
  await page.locator("#confirm").fill(testData.entryPassword);
  const result = await page.evaluate(() => (window as unknown as {
    vaultUnifiedFillInputs: (values: Record<string, unknown>) => Record<string, unknown>;
  }).vaultUnifiedFillInputs({ capture: true, pageOrigin: location.origin }));
  expect(result.reason).toBe("captured");
  expect(result.password === testData.entryPassword).toBe(true);
  await page.evaluate((password) => (window as unknown as {
    vaultUnifiedFillInputs: (values: Record<string, unknown>) => Record<string, unknown>;
  }).vaultUnifiedFillInputs({ newPassword: true, password, pageOrigin: location.origin }), testData.entryPassword);
  await expect(page.locator("#old")).toHaveValue(testData.masterPassword);
  const changed = await page.evaluate(() => (window as unknown as {
    vaultUnifiedFillInputs: (values: Record<string, unknown>) => Record<string, unknown>;
  }).vaultUnifiedFillInputs({ capture: true, pageOrigin: "https://other.invalid" }));
  expect(changed).toEqual({ username: false, password: false, reason: "page-changed" });
});
