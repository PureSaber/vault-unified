import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";
import { browserPairingOrigin } from "../../src/api/client";

test("canonicalizes the packaged runtime API base for browser pairing", () => {
  expect(browserPairingOrigin("http://127.0.0.1:54907/api")).toBe("http://127.0.0.1:54907");
});

test("guides installation and makes desktop pairing copyable, expiring, renewable, and cancellable", async ({ page, context }) => {
  const sidecar = new MockAuthenticatedSidecar();
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));
  await page.goto("/");
  await context.grantPermissions(
    ["clipboard-read", "clipboard-write"],
    { origin: new URL(page.url()).origin },
  );
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();
  await page.getByRole("button", { name: "Connections", exact: true }).click();

  const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Browser extension" }) });
  await expect(card).toContainText("Download the extension ZIP");
  await expect(card).not.toContainText("apps/browser-extension");
  await expect(card.getByRole("button", { name: "Open extension install guide" })).toBeVisible();
  await card.getByRole("button", { name: "Create one-time pairing code" }).click();
  await expect(card).toContainText("Expires in: 5:00");
  expect(sidecar.pairingWrites.create).toBe(1);

  await card.getByRole("button", { name: "Copy local address" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("http://127.0.0.1:43129");
  await card.getByRole("button", { name: "Copy one-time pairing code" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(testData.bootstrapSecret);

  await card.getByRole("button", { name: "Generate again" }).click();
  expect(sidecar.pairingWrites.create).toBe(2);
  await expect(card).toContainText("Expires in: 5:00");
  await card.getByRole("button", { name: "Cancel pairing" }).click();
  expect(sidecar.pairingWrites.cancel).toBe(1);
  await expect(card.getByText("Expires in:")).toHaveCount(0);

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter((item) => ["critical", "serious"].includes(item.impact || ""))).toEqual([]);
});
