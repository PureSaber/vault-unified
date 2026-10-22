import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test.use({ trace: "off", screenshot: "off" });

test("a delayed sharing status cannot erase an address already being entered", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(); await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  let release: () => void = () => {};
  let received = false;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("http://127.0.0.1:43129/sharing/status", async route => {
    if (route.request().method() === "OPTIONS") return route.fallback();
    received = true; await held;
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "http://127.0.0.1:1420" }, body: JSON.stringify({ service: "", identity: "", shares: [], families: [], outbox: [] }) });
  });
  await page.goto("/");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();
  await page.getByRole("button", { name: "Sharing", exact: true }).click();
  await expect.poll(() => received).toBe(true);
  const field = page.getByLabel("Sharing service address", { exact: true });
  await field.fill("https://sharing.example.invalid");
  const loaded = page.waitForResponse(response => response.url().endsWith("/sharing/status"));
  release(); await loaded;
  await expect(field).toHaveValue("https://sharing.example.invalid");
  expect(sidecar.writes).toEqual({ create: 0, update: 0, delete: 0 });
});
