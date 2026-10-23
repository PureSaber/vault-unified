/** Preferences for offering Windows Hello after a master-password unlock.
 * Neither value is secret. "Don't ask again" persists; "Not now" lasts for
 * this application run (sessionStorage is cleared when the app restarts). */
const PERSISTENT_KEY = "vault_hello_prompt";
const RUN_KEY = "vault_hello_prompt_declined";
export const HELLO_PROMPT_EVENT = "vault-hello-prompt-changed";

export function helloPromptEnabled(): boolean {
  try { return localStorage.getItem(PERSISTENT_KEY) !== "off"; } catch { return true; }
}

export function setHelloPromptEnabled(enabled: boolean): void {
  try {
    if (enabled) { localStorage.removeItem(PERSISTENT_KEY); sessionStorage.removeItem(RUN_KEY); }
    else localStorage.setItem(PERSISTENT_KEY, "off");
  } catch { /* Storage can be unavailable; the prompt then simply reappears. */ }
  window.dispatchEvent(new Event(HELLO_PROMPT_EVENT));
}

export function helloDeclinedThisRun(): boolean {
  try { return sessionStorage.getItem(RUN_KEY) === "1"; } catch { return false; }
}

export function declineHelloThisRun(): void {
  try { sessionStorage.setItem(RUN_KEY, "1"); } catch { /* Best effort. */ }
}
