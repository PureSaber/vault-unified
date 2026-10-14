import { readFileSync } from "node:fs";
import { expect, test } from "./journey-test";

const script = readFileSync(new URL("../../../browser-extension/fill.js", import.meta.url), "utf8");

test("verification-code filling checks the target, page and expiry without submitting", async ({ page }) => {
  await page.setContent('<form><input id="otp" autocomplete="one-time-code"><input id="password" type="password"></form>');
  await page.addScriptTag({ content: script });
  await page.evaluate(() => { document.querySelector("form")!.onsubmit = () => { throw new Error("A fill must never submit"); }; });
  const fill = (overrides: Record<string, unknown> = {}) => page.evaluate(values => (window as unknown as { vaultUnifiedFillInputs: (value: unknown) => { reason: string } }).vaultUnifiedFillInputs({ otp: "123456", pageOrigin: location.origin, expiresAt: Date.now() + 20_000, ...values }), overrides);
  expect((await fill()).reason).toBe("otp-filled");
  await expect(page.locator("#otp")).toHaveValue("123456");
  await expect(page.locator("#password")).toHaveValue("");
  await page.locator("#otp").fill("");
  expect((await fill({ expiresAt: 0 })).reason).toBe("otp-expired");
  expect((await fill({ pageOrigin: "https://other.invalid" })).reason).toBe("page-changed");
  await page.evaluate(() => { const input = document.createElement("input"); input.autocomplete = "one-time-code"; document.body.append(input); });
  expect((await fill()).reason).toBe("otp-target-ambiguous");
  await expect(page.locator("#otp")).toHaveValue("");
});
