import { useEffect, useRef, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { api } from "../api/client";
import { helloError } from "../desktop";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import { declineHelloThisRun, helloDeclinedThisRun, helloPromptEnabled, setHelloPromptEnabled } from "./hello-prompt";

/** Offers Windows Hello quick unlock once after a master-password unlock.
 * It only calls the existing enable command; the master password is still
 * required after every restart because Hello grants live in process memory. */
export default function HelloOffer({ active, onDone }: { active: boolean; onDone: () => void }) {
  const { locale } = useI18n(); const zh = locale === "zh"; const { showToast } = useToast();
  const [eligible, setEligible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDivElement>(null);
  const enableButton = useRef<HTMLButtonElement>(null);
  // Locking unmounts this offer and cancels a pending Hello verification.
  // Set in the effect body too: StrictMode runs mount cleanups once in development.
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  useEffect(() => {
    if (!isTauri() || !helloPromptEnabled() || helloDeclinedThisRun()) { onDone(); return; }
    let current = true;
    void api.helloStatus()
      .then(status => { if (!current) return; if (status.supported && !status.ready && !status.busy) setEligible(true); else onDone(); })
      .catch(() => { if (current) onDone(); });
    return () => { current = false; };
  }, [onDone]);

  const open = eligible && active;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    enableButton.current?.focus();
    return () => previous?.focus?.();
  }, [open]);
  // A cancelled or failed Windows prompt returns focus to Enable.
  useEffect(() => { if (open && !busy && error) enableButton.current?.focus(); }, [open, busy, error]);

  const keys = useRef<(event: KeyboardEvent) => void>(() => {});
  keys.current = event => {
    if (event.key === "Escape") { event.preventDefault(); notNow(); return; }
    if (event.key !== "Tab" || !dialog.current) return;
    const focusable = [...dialog.current.querySelectorAll<HTMLElement>("button:not([disabled])")];
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0], last = focusable[focusable.length - 1];
    const inside = dialog.current.contains(document.activeElement);
    if (!inside) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
    else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  // Window-level, like ConfirmDialog, so focus on the backdrop or body cannot escape the trap.
  useEffect(() => {
    if (!open) return;
    const listener = (event: KeyboardEvent) => keys.current(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [open]);

  function notNow() { if (busy) return; declineHelloThisRun(); onDone(); }
  function never() { if (busy) return; setHelloPromptEnabled(false); onDone(); }
  async function enable() {
    setBusy(true); setError("");
    try {
      await api.enableHello();
      if (!alive.current) return;
      showToast(zh ? "已为本次运行启用 Windows Hello 快速解锁。" : "Windows Hello quick unlock is on for this run.");
      onDone();
    } catch (reason) {
      if (!alive.current) return;
      setError(helloError(reason, zh));
      setBusy(false);
    }
  }
  if (!open) return null;
  // A stray backdrop click keeps focus in the dialog instead of declining.
  return <div className="confirm-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) event.preventDefault(); }}>
    <div ref={dialog} className="confirm-dialog card hello-offer" role="dialog" aria-modal="true" aria-labelledby="hello-offer-title" aria-describedby="hello-offer-message">
      <h2 id="hello-offer-title" className="confirm-title">{zh ? "使用 Windows Hello 快速解锁？" : "Unlock with Windows Hello?"}</h2>
      <p id="hello-offer-message" className="confirm-message">{zh
        ? "在退出 Vault Unified 之前，保险库再次锁定后，可以用这台电脑已设置的指纹、人脸或 Windows PIN 解锁，无需重新输入主密码。重新启动应用后，仍需先输入主密码。"
        : "Until you quit Vault Unified, you can unlock it after it locks with the fingerprint, face or Windows PIN set up on this computer instead of typing the master password. After you restart the app, the master password is required first."}</p>
      <p role="status" className={busy ? undefined : "sr-only"}>{busy ? (zh ? "请在 Windows Hello 窗口中完成验证…" : "Complete verification in the Windows Hello window…") : ""}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="button-row confirm-actions">
        <button ref={enableButton} type="button" className="primary" disabled={busy} onClick={() => void enable()}>{zh ? "启用" : "Enable"}</button>
        <button type="button" className="secondary" disabled={busy} onClick={notNow}>{zh ? "暂不" : "Not now"}</button>
        <button type="button" className="ghost" disabled={busy} onClick={never}>{zh ? "不再询问" : "Don't ask again"}</button>
      </div>
    </div>
  </div>;
}
