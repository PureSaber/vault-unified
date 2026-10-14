import { useEffect, useRef, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { api, type Entry, type TypeTarget } from "../api/client";
import { useI18n } from "../i18n";

export default function AutoTypeButton({ entry, disabled = false }: { entry?: Entry; disabled?: boolean }) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const [open, setOpen] = useState(false);
  return isTauri() ? <>
    <button type="button" className="secondary" disabled={disabled || !entry || entry.entry_type !== "login" || (entry.state && entry.state !== "active")} onClick={() => setOpen(true)}>{zh ? "输入到应用" : "Type into application"}</button>
    {open && entry && <AutoTypeDialog entry={entry} onClose={() => setOpen(false)} />}
  </> : null;
}

function AutoTypeDialog({ entry, onClose }: { entry: Entry; onClose: () => void }) {
  const { locale } = useI18n(); const zh = locale === "zh";
  const dialog = useRef<HTMLDialogElement>(null);
  const alive = useRef(true);
  const [target, setTarget] = useState<TypeTarget | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [sequence, setSequence] = useState("login");
  const [delay, setDelay] = useState(20);
  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => { alive.current = false; void api.cancelAutoType().catch(() => {}); previous?.focus(); };
  }, []);
  useEffect(() => {
    if (!target) return;
    const timer = window.setTimeout(() => { setTarget(null); setMessage(zh ? "目标选择已过期，请重新选择。" : "Target selection expired. Choose it again."); }, 60_000);
    return () => clearTimeout(timer);
  }, [target, zh]);
  function failure(reason: unknown) {
    const code = String(reason);
    if (code.includes("type_focus")) return zh ? "窗口焦点已改变，输入已停止。请检查目标中已输入的部分，再重新操作。" : "Window focus changed; typing stopped. Check the partial input before trying again.";
    if (code.includes("type_cancelled")) return zh ? "输入已取消。请检查目标中已输入的部分。" : "Typing cancelled. Check any partial input in the destination.";
    if (code.includes("type_values")) return zh ? "请保存有效的登录信息并保持密码库解锁。自动输入不接受换行或控制字符，每个字段最多 256 个字符。" : "Save valid login details and keep the vault unlocked. Automatic typing accepts no control characters and at most 256 characters per field.";
    if (code.includes("type_target")) return zh ? "目标窗口已关闭、改变或选择已过期，请重新选择。" : "The target closed, changed or expired. Choose it again.";
    return zh ? "无法输入到此应用。请关闭管理员模式，或使用复制功能。" : "Could not type into this application. Use a non-administrator window or copy the fields.";
  }
  async function capture() {
    setBusy(true); setError(""); setTarget(null);
    setMessage(zh ? "请在 3 秒内切换到目标应用，并点击第一个输入框。" : "Switch to the target application and click its first field within 3 seconds.");
    try { const value = await api.captureTypeTarget(); if (alive.current) { setTarget(value); setMessage(""); } }
    catch (reason) { if (alive.current) { setMessage(""); setError(failure(reason)); } }
    finally { if (alive.current) setBusy(false); }
  }
  async function start() {
    if (!target || busy) return;
    setBusy(true); setError(""); setMessage(zh ? "正在输入，按 Esc 可停止。" : "Typing; press Esc to stop.");
    try { await api.startAutoType(target.id, entry.id, sequence, delay); if (alive.current) setMessage(zh ? "输入完成。请在目标应用中检查后自行登录。" : "Typing finished. Check the target application before signing in."); }
    catch (reason) { if (alive.current) { setMessage(""); setError(failure(reason)); } }
    finally { if (alive.current) { setTarget(null); setBusy(false); } }
  }
  return <dialog ref={dialog} className="card history-review" aria-labelledby="auto-type-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <h2 id="auto-type-title">{zh ? "输入到应用" : "Type into application"}</h2>
    <p>{entry.title}</p>
    <p className="field-hint">{zh ? "先选择目标窗口，再确认输入。切换窗口或按 Esc 会停止输入；完成后由你提交登录。" : "Choose a destination, then confirm typing. Changing windows or pressing Esc stops typing; submit the login yourself afterwards."}</p>
    <label className="field-label" htmlFor="auto-type-sequence">{zh ? "输入顺序" : "Typing sequence"}</label>
    <select id="auto-type-sequence" value={sequence} onChange={event => setSequence(event.target.value)} disabled={busy}>
      <option value="login">{zh ? "用户名 → Tab → 密码" : "Username → Tab → Password"}</option>
      <option value="username">{zh ? "仅用户名" : "Username only"}</option>
      <option value="password">{zh ? "仅密码" : "Password only"}</option>
    </select>
    <label className="field-label" htmlFor="auto-type-delay">{zh ? "输入速度" : "Typing speed"}</label>
    <select id="auto-type-delay" value={delay} onChange={event => setDelay(Number(event.target.value))} disabled={busy}>
      <option value={20}>{zh ? "正常" : "Normal"}</option><option value={70}>{zh ? "较慢（兼容旧应用）" : "Slower (older applications)"}</option>
    </select>
    {target && <section aria-label={zh ? "目标窗口" : "Destination window"}><p><strong>{target.title}</strong></p><p>{target.application}</p></section>}
    {message && <p role="status">{message}</p>}{error && <p role="alert" className="error">{error}</p>}
    <div className="button-row">
      <button type="button" className="secondary" disabled={busy} onClick={() => void capture()}>{zh ? "选择窗口（3 秒）" : "Choose window (3 seconds)"}</button>
      <button type="button" className="primary" disabled={busy || !target} onClick={() => void start()}>{zh ? "确认并开始输入" : "Confirm and start typing"}</button>
      <button type="button" className="secondary" onClick={onClose}>{zh ? "关闭" : "Close"}</button>
    </div>
  </dialog>;
}
