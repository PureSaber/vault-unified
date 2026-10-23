import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { api, type BrowserConnectRequest } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";

const ACTIVATION_INTERVAL_MS = 10_000;
let lastActivation = 0;

/** Number matching: the browser shows one code, this dialog shows it among two
 * decoys fixed by the API. Picking a wrong code denies the request. */
function Approval({ item, many, onDone }: { item: BrowserConnectRequest; many: boolean; onDone: (id: string) => void }) {
  const { locale } = useI18n(); const zh = locale === "zh";
  const { showToast } = useToast();
  const dialog = useRef<HTMLDialogElement>(null);
  const deny = useRef<HTMLButtonElement>(null);
  const [busy, setBusy] = useState(false);
  // A ref, not state: a fast double click must not send a second decision.
  const deciding = useRef(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal(); deny.current?.focus();
    // Bring the window forward once per request, and not more than every 10 seconds.
    if (isTauri() && Date.now() - lastActivation >= ACTIVATION_INTERVAL_MS) {
      lastActivation = Date.now();
      void invoke("show_desktop_approval").catch(() => {});
    }
    return () => previous?.focus();
  }, []);
  async function decide(work: () => Promise<void>) {
    if (deciding.current) return;
    deciding.current = true;
    setBusy(true);
    try { await work(); }
    catch { showToast(zh ? "请求已过期或已处理，请回到浏览器重试。" : "The request expired or was already handled. Retry from the browser.", "error"); }
    finally { onDone(item.id); }
  }
  const pick = (code: string) => decide(async () => {
    const result = await api.approveBrowserConnection(item.id, code);
    if (result.approved) showToast(zh ? "已允许。浏览器将自动完成连接。" : "Allowed. The browser finishes connecting by itself.");
    else showToast(zh ? "代码不匹配。如果不是你发起的，可能有其他程序在尝试连接。" : "That code did not match. If you did not start this, someone else may be trying to connect.", "error");
  });
  const refuse = () => decide(() => api.denyBrowserConnection(item.id).then(() => undefined));
  const refuseAll = () => decide(() => api.denyAllBrowserConnections().then(() => undefined));
  const spaced = (code: string) => `${code.slice(0, 3)} ${code.slice(3)}`;
  return <dialog ref={dialog} className="passkey-dialog browser-connect-dialog" aria-labelledby="browser-connect-heading" aria-describedby="browser-connect-hint"
    onCancel={event => { event.preventDefault(); void refuse(); }}>
    <h2 id="browser-connect-heading">{zh ? "要将浏览器连接到 Vault Unified 吗？" : "Connect a browser to Vault Unified?"}</h2>
    <p id="browser-connect-hint">{zh
      ? "仅当你刚刚在浏览器中点击了“连接到 Vault Unified”时才继续。请选择该浏览器显示的代码。"
      : "Only continue if you just clicked Connect to Vault Unified in a browser. Choose the code that browser shows."}</p>
    <dl><dt>{zh ? "浏览器名称（由浏览器提供）" : "Browser name (reported by the browser)"}</dt><dd>{item.device_name}</dd></dl>
    <div className="browser-connect-codes" role="group" aria-label={zh ? "浏览器显示的代码" : "Code shown in the browser"}>
      {item.choices.map(code => <button key={code} type="button" className="secondary browser-connect-code" disabled={busy}
        aria-label={zh ? `选择代码 ${spaced(code)}` : `Choose code ${spaced(code)}`} onClick={() => void pick(code)}>{spaced(code)}</button>)}
    </div>
    <p className="field-hint">{zh
      ? "允许后，只要此保险库处于解锁状态，该浏览器即可填充其中的账号，直到你在“连接”中撤销。"
      : "After you allow it, this browser can fill accounts from this vault whenever the vault is unlocked, until you revoke it in Connections."}</p>
    <p className="muted">{zh ? `请求剩余 ${item.remaining_seconds} 秒` : `Request expires in ${item.remaining_seconds} seconds`}</p>
    <div className="button-row">
      <button ref={deny} type="button" className="secondary" disabled={busy} onClick={() => void refuse()}>{zh ? "都不是，拒绝" : "None of these — Deny"}</button>
      {many && <button type="button" className="danger" disabled={busy} onClick={() => void refuseAll()}>{zh ? "全部拒绝" : "Deny all"}</button>}
    </div>
  </dialog>;
}

/** One dialog at a time; it waits while a passkey approval is open. */
export default function BrowserConnectRequests({ paused, onPendingChange }: { paused: boolean; onPendingChange: (value: boolean) => void }) {
  const [items, setItems] = useState<BrowserConnectRequest[]>([]);
  const completed = useRef(new Set<string>());
  const item = items.find(value => !completed.current.has(value.id)) || null;
  useEffect(() => { onPendingChange(Boolean(item)); }, [item, onPendingChange]);
  useEffect(() => {
    let disposed = false; let timer: number | undefined;
    const controller = new AbortController();
    async function poll() {
      try {
        const result = await api.pendingBrowserConnections(controller.signal);
        if (!disposed) setItems(result.items);
      } catch { if (!disposed) setItems([]); }
      finally { if (!disposed) timer = window.setTimeout(() => void poll(), 2000); }
    }
    void poll();
    return () => { disposed = true; controller.abort(); window.clearTimeout(timer); };
  }, []);
  function done(id: string) {
    completed.current.add(id);
    if (completed.current.size > 100) completed.current.delete(completed.current.values().next().value!);
    setItems(current => current.filter(value => value.id !== id));
  }
  const open = items.filter(value => !completed.current.has(value.id));
  return item && !paused ? <Approval key={item.id} item={item} many={open.length > 1} onDone={done} /> : null;
}
