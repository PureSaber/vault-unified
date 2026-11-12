import { expect, test } from "@playwright/test";
import { uiEn, uiZh } from "../../src/i18n/ui-messages";
import { backupMessages } from "../../src/i18n/backup-messages";

function checkCatalog(en: Record<string, string>, zh: Record<string, string>) {
  expect(Object.keys(zh).sort()).toEqual(Object.keys(en).sort());
  const parameters = (message: string) => [...new Set(message.match(/\{\w+\}/g) || [])].sort();
  for (const key of Object.keys(en)) {
    expect(zh[key].trim(), key).not.toBe("");
    expect(parameters(zh[key]), key).toEqual(parameters(en[key]));
  }
}

test("task-page dictionaries have bilingual key and interpolation parity", () => {
  checkCatalog(uiEn, uiZh);
  checkCatalog(backupMessages.en, backupMessages.zh);
});
