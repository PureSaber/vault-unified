import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { api, type PasskeyRequest } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";

function Approval({ item, onDone }: { item: PasskeyRequest; onDone: (id: string) => void }) {
  const { locale } = useI18n(); const zh = locale === "zh";
  const { showToast } = useToast();
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const [password, setPassword] = useState("");
  const [selected, setSelected] = useState(item.choices[0]?.credential_id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal(); cancel.current?.focus();
    if (isTauri()) void invoke("show_desktop_approval").catch(() => {});
    return () => previous?.focus();
  }, []);
  async function reject(fallback = false) {
    setPassword(""); onDone(item.id);
    try { await api.rejectPasskey(item.id, fallback); }
    catch { showToast(zh ? "未能确认取消结果，请查看网站和账号状态。" : "Cancellation could not be confirmed. Check the website and account status.", "error"); }
  }
  async function approve(event: React.FormEvent) {
    event.preventDefault(); if (busy || !password) return;
    const value = password; setPassword(""); setBusy(true); setError("");
    const choice = item.choices.find(candidate => candidate.credential_id === selected);
    try {
      const result = await api.approvePasskey(item.id, value, choice?.entry_id, choice?.credential_id);
      if (result.changed) window.dispatchEvent(new Event("vault-entries-changed"));
      onDone(item.id);
    } catch (reason) {
      const detail = String(reason);
      setError(detail.includes("master password")
        ? (zh ? "主密码不正确，请重新输入。" : "The master password is incorrect. Try again.")
        : (zh ? "请求已改变或未能完成，请回到网站重试。" : "The request changed or could not complete. Retry from the website."));
    } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="passkey-dialog" aria-labelledby="passkey-heading" onCancel={event => { event.preventDefault(); void reject(); }}>
    <form onSubmit={event => void approve(event)} autoComplete="off">
      <h2 id="passkey-heading">{item.operation === "create" ? (zh ? "创建通行密钥" : "Create a Passkey") : (zh ? "使用通行密钥登录" : "Sign in with a Passkey")}</h2>
      <dl><dt>{zh ? "请求网站" : "Requesting website"}</dt><dd>{item.origin}</dd>
        <dt>{zh ? "通行密钥所属域名" : "Passkey domain"}</dt><dd>{item.rp_id}</dd></dl>
      {item.operation === "create" ? <p>{zh ? "账号：" : "Account: "}<strong>{item.user_name}</strong>{item.user_display_name && item.user_display_name !== item.user_name ? ` (${item.user_display_name})` : ""}</p>
        : <label>{zh ? "选择账号" : "Choose account"}<select value={selected} onChange={event => setSelected(event.target.value)} disabled={busy}>
          {item.choices.map(choice => <option key={`${choice.entry_id}:${choice.credential_id}`} value={choice.credential_id}>{choice.title} — {choice.user_name}</option>)}
        </select></label>}
      <p>{zh ? "核对网站后，输入主密码确认本次操作。" : "Check the website, then enter your master password to confirm this request."}</p>
      <label>{zh ? "主密码" : "Master password"}<input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="off" maxLength={4096} disabled={busy} required /></label>
      <p className="muted">{zh ? `请求剩余 ${item.remaining_seconds} 秒` : `Request expires in ${item.remaining_seconds} seconds`}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="button-row"><button type="submit" disabled={busy || !password || (item.operation === "get" && !selected)}>{busy ? (zh ? "正在确认…" : "Confirming…") : (zh ? "确认" : "Confirm")}</button>
        <button type="button" className="secondary" ref={cancel} onClick={() => void reject()}>{zh ? "取消" : "Cancel"}</button></div>
      <button type="button" className="ghost" onClick={() => void reject(true)}>{zh ? "使用浏览器或其他密码管理器" : "Use the browser or another password manager"}</button>
    </form>
  </dialog>;
}

export default function PasskeyRequests({ onPendingChange }: { onPendingChange: (value: boolean) => void }) {
  const [item, setItem] = useState<PasskeyRequest | null>(null);
  const completed = useRef(new Set<string>());
  useEffect(() => { onPendingChange(Boolean(item)); }, [item, onPendingChange]);
  useEffect(() => {
    let disposed = false; let timer: number | undefined;
    const controller = new AbortController();
    async function poll() {
      try {
        const result = await api.pendingPasskeys(controller.signal);
        if (!disposed) setItem(result.items.find(value => !completed.current.has(value.id)) || null);
      } catch { if (!disposed) setItem(null); }
      finally { if (!disposed) timer = window.setTimeout(() => void poll(), 1500); }
    }
    void poll();
    return () => { disposed = true; controller.abort(); window.clearTimeout(timer); };
  }, []);
  function done(id: string) {
    completed.current.add(id);
    if (completed.current.size > 100) completed.current.delete(completed.current.values().next().value!);
    setItem(current => current?.id === id ? null : current);
  }
  return item ? <Approval key={item.id} item={item} onDone={done} /> : null;
}
