import { expect, test } from "./journey-test";
import { MockAuthenticatedSidecar } from "./mock-sidecar";
import { testData } from "./test-data";

test("shows conflicts only in context and preserves another unsubmitted field choice", async ({ page }) => {
  const sidecar = new MockAuthenticatedSidecar(900, 0, "empty", 2);
  await sidecar.install(page);
  await page.addInitScript(() => localStorage.setItem("vault_locale", "en"));

  await page.goto("/");
  await page.getByLabel("Master password", { exact: true }).fill(testData.masterPassword);
  await page.getByLabel("Confirm master password").fill(testData.masterPassword);
  await page.getByRole("button", { name: "Create and unlock" }).click();

  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await expect(navigation.getByRole("button", { name: "Conflicts", exact: true })).toHaveCount(0);
  await expect(page.getByText(/2 account\(s\) changed both/)).toBeVisible();
  await page.getByRole("button", { name: "Review changes", exact: true }).click();

  const first = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Generated conflict 1" }) });
  const second = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Generated conflict 2" }) });
  const usernameRow = second.locator(".conflict-pick-row").filter({ hasText: "Username" });
  const serviceChoice = usernameRow.getByRole("button", { name: "Connected service", exact: true });
  await serviceChoice.click();
  await expect(serviceChoice).toHaveAttribute("aria-pressed", "true");

  await first.getByRole("button", { name: "Keep this device version", exact: true }).click();
  await expect(first).toHaveCount(0);
  await expect(serviceChoice).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "Keep this device version", exact: true }).click();
  await expect(page.getByText("There are no changes from two locations to review.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Back to passwords", exact: true }).click();
  await expect(page.getByRole("button", { name: "Review changes", exact: true })).toHaveCount(0);
});
