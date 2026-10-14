import { useEffect, useRef, useState } from "react";
import { api, type GeneratedPassword } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";

export default function GenerationHistory({ onClose, onUse }: { onClose: () => void; onUse?: (value: string) => void }) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const { showToast } = useToast();
  const dialog = useRef<HTMLDialogElement>(null);
  const [items, setItems] = useState<GeneratedPassword[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);
  const [revealed, setRevealed] = useState<{ id: string; value: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    let cancelled = false;
    void api.generationHistory().then(result => { if (!cancelled) { setItems(result.items); setLoaded(true); } }).catch(() => { if (!cancelled) setError(true); });
    const hide = () => { ++sequence.current; setRevealed(null); setBusy(false); };
    window.addEventListener("blur", hide); document.addEventListener("visibilitychange", hide);
    return () => { cancelled = true; ++sequence.current; window.removeEventListener("blur", hide); document.removeEventListener("visibilitychange", hide); before?.focus(); };
  }, []);
  useEffect(() => {
    if (!revealed) return;
    const timer = setTimeout(() => setRevealed(null), 30_000);
    return () => clearTimeout(timer);
  }, [revealed]);
  async function act(item: GeneratedPassword, action: "show" | "use" | "copy") {
    const stamp = ++sequence.current;
    setBusy(true); setError(false);
    try {
      if (action === "copy") {
        await api.copyGeneration(item.id);
        if (stamp === sequence.current) showToast(zh ? "已复制，45 秒后清除剪贴板" : "Copied; clipboard clears in 45 seconds");
      } else {
        const result = await api.generationValue(item.id);
        if (stamp !== sequence.current) return;
        if (action === "use") { onUse?.(result.password); onClose(); }
        else setRevealed({ id: item.id, value: result.password });
      }
    } catch { if (stamp === sequence.current) setError(true); }
    finally { if (stamp === sequence.current) setBusy(false); }
  }
  return <dialog ref={dialog} className="card history-review" aria-labelledby="generation-history-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <h2 id="generation-history-title">{zh ? "生成密码历史" : "Generated password history"}</h2>
    <p>{zh ? "桌面和浏览器生成的密码加密保留最近 100 条，最长 30 天。" : "Passwords generated on desktop and in the browser are kept encrypted: the latest 100 for up to 30 days."}</p>
    {error && <p className="error" role="alert">{zh ? "无法读取或复制，记录可能已过期。请关闭后重试。" : "Could not read or copy; the record may have expired. Close and try again."}</p>}
    {!loaded && !error && <p role="status">{zh ? "正在读取…" : "Loading…"}</p>}
    {loaded && !items.length && <p>{zh ? "还没有生成记录。" : "No generated passwords yet."}</p>}
    <div className="history-field-list">
      {items.map((item, index) => <section className="history-field" key={item.id} aria-label={`${zh ? "生成记录" : "Generated record"} ${index + 1}`}>
        <strong>{item.origin || (zh ? "未关联网站" : "No website")}</strong>
        <p>{new Date(item.created_at * 1000).toLocaleString(locale === "zh" ? "zh-CN" : "en-US")} · {item.kind === "passphrase" ? (zh ? "口令短语" : "Passphrase") : (zh ? "随机密码" : "Random password")}</p>
        <pre className="generated-secret">{revealed?.id === item.id ? revealed.value : (zh ? "已隐藏" : "Hidden")}</pre>
        <div className="button-row">
          <button type="button" className="secondary" disabled={busy} onClick={() => revealed?.id === item.id ? setRevealed(null) : void act(item, "show")}>{revealed?.id === item.id ? (zh ? "隐藏" : "Hide") : (zh ? "显示" : "Show")}</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => void act(item, "copy")}>{zh ? "复制" : "Copy"}</button>
          {onUse && <button type="button" className="secondary" disabled={busy} onClick={() => void act(item, "use")}>{zh ? "载入密码草稿" : "Use in password draft"}</button>}
        </div>
      </section>)}
    </div>
    <div className="button-row"><button type="button" className="secondary" autoFocus onClick={onClose}>{zh ? "关闭" : "Close"}</button></div>
  </dialog>;
}
