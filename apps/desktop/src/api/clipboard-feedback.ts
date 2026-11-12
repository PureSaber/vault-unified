export const CLIPBOARD_FEEDBACK = "vault-clipboard-feedback";
export interface ClipboardFeedback { deadline?: number }

let epoch = 0;
let sequence = 0;
if (typeof window !== "undefined") window.addEventListener("vault-ui-locked", () => { epoch++; });

/** Only the latest requested copy can update feedback. Never queue a new
 * session's copy behind an old session's network request. The renderer never
 * reads or clears clipboard data; only timing metadata is sent.
 */
export async function copyWithFeedback<T>(copy: () => Promise<T>): Promise<T> {
  const session = epoch;
  const request = ++sequence;
  window.dispatchEvent(new CustomEvent<ClipboardFeedback>(CLIPBOARD_FEEDBACK, { detail: {} }));
  const started = performance.now();
  const value = await copy();
  const duration = (value as { clears_in_seconds?: number; clear_after?: number } | null)?.clears_in_seconds
    ?? (value as { clear_after?: number } | null)?.clear_after;
  // Subtract the whole round trip conservatively. A late response never
  // restarts a full duration, and a lock invalidates every in-flight result.
  if (session === epoch && request === sequence && typeof duration === "number" && Number.isFinite(duration) && duration > 0) {
    window.dispatchEvent(new CustomEvent<ClipboardFeedback>(CLIPBOARD_FEEDBACK, {
      detail: { deadline: started + duration * 1000 },
    }));
  }
  return value;
}
