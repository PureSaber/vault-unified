import { expect, test as base } from "@playwright/test";
import { testData } from "./test-data";

const generatedSecrets = [
  testData.masterPassword,
  testData.entryPassword,
  testData.bearerToken,
  testData.bootstrapSecret,
];

function redactGeneratedSecrets(value: string): string {
  return generatedSecrets.reduce(
    (safe, marker) => safe.split(marker).join("[generated-secret]"),
    value,
  );
}

export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(redactGeneratedSecrets(message.text()));
      }
    });
    page.on("pageerror", (error) => {
      consoleErrors.push(redactGeneratedSecrets(`Uncaught page error: ${error.message}`));
    });

    await use(page);

    if (!page.isClosed()) {
      const quality = await page.evaluate(() => {
        const ids = [...document.querySelectorAll<HTMLElement>("[id]")].map((element) => element.id);
        const duplicateIds = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
        const dangerousControlsWithoutText = [...document.querySelectorAll<HTMLElement>("button.danger")]
          .filter((element) => {
            const style = window.getComputedStyle(element);
            if (style.display === "none" || style.visibility === "hidden") return false;
            const accessibleText = [
              element.textContent,
              element.getAttribute("aria-label"),
              element.getAttribute("title"),
            ].filter(Boolean).join(" ").trim();
            return accessibleText.length === 0;
          })
          .map((element) => element.outerHTML.slice(0, 160));
        return {
          duplicateIds,
          dangerousControlsWithoutText,
          horizontalOverflow: Math.max(
            0,
            document.documentElement.scrollWidth - document.documentElement.clientWidth,
          ),
        };
      });
      expect(quality.duplicateIds, "DOM ids must be unique").toEqual([]);
      expect(
        quality.dangerousControlsWithoutText,
        "dangerous actions need text in addition to color",
      ).toEqual([]);
      expect(quality.horizontalOverflow, "ordinary content must remain horizontally reachable").toBeLessThanOrEqual(1);
    }
    const expectedFailureAnnotation = testInfo.annotations.find(
      (annotation) => annotation.type === "expected-request-failures",
    );
    const expectedRequestFailures = Number(expectedFailureAnnotation?.description || "0");
    const isRequestFailure = (message: string) =>
      message.startsWith("Failed to load resource: the server responded with a status of ")
      || message.startsWith("Failed to load resource: net::");
    const requestFailures = consoleErrors.filter(isRequestFailure);
    expect(
      requestFailures,
      "fault-injection journeys must emit exactly the declared resource errors",
    ).toHaveLength(expectedRequestFailures);
    const unexpectedConsoleErrors = consoleErrors.filter((message) => !isRequestFailure(message));
    expect(unexpectedConsoleErrors, "ordinary journeys must not emit console errors").toEqual([]);
  },
});

export { expect };
