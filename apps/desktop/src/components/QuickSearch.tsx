import { useEffect, useRef, useState } from "react";
import { api, type Entry } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import AutoTypeButton from "./AutoTypeButton";

export default function QuickSearch({ onClose, onOpen }: { onClose: () => void; onOpen: (entry: Entry) => void }) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const { showToast } = useToast();
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [copying, setCopying] = useState(false);
  const sequence = useRef(0);
  const current = entries[index];
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    dialog.current?.showModal(); input.current?.focus();
    return () => { ++sequence.current; before?.focus(); };
  }, []);
  useEffect(() => {
    const stamp = ++sequence.current;
    setLoading(true); setError(false); setEntries([]); setIndex(0);
    const timer = setTimeout(() => {
      void api.listEntries(query || undefined, "active").then(values => {
        if (stamp !== sequence.current) return;
        setEntries(values.sort((left, right) => Number(Boolean(right.favorite)) - Number(Boolean(left.favorite)) || right.updated_at.localeCompare(left.updated_at)).slice(0, 20));
        setLoading(false);
      }).catch(() => { if (stamp === sequence.current) { setError(true); setLoading(false); } });
    }, 150);
    return () => { clearTimeout(timer); ++sequence.current; };
  }, [query]);
  useEffect(() => { document.getElementById(`quick-option-${index}`)?.scrollIntoView({ block: "nearest" }); }, [index]);
  async function copy(field: "password" | "username") {
    if (!current || copying || loading || (field === "password" ? !current.has_password : !current.username)) return;
    setCopying(true);
    const stamp = sequence.current;
    try {
      await api.copy(current.id, field);
      if (stamp === sequence.current) showToast(zh ? "已复制，45 秒后清除剪贴板" : "Copied; clipboard clears in 45 seconds");
    } catch { if (stamp === sequence.current) showToast(zh ? "复制失败，请重试" : "Could not copy. Try again.", "error"); }
    finally { setCopying(false); }
  }
  return <dialog className="card history-review quick-search" ref={dialog} aria-labelledby="quick-search-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <h2 id="quick-search-title">{zh ? "快捷搜索" : "Quick search"}</h2>
    <label className="field-label" htmlFor="quick-search-query">{zh ? "搜索网站、账号或标签" : "Search websites, accounts or tags"}</label>
    <input id="quick-search-query" ref={input} role="combobox" aria-autocomplete="list" aria-expanded={true} aria-controls="quick-search-results" aria-activedescendant={current ? `quick-option-${index}` : undefined} autoComplete="off" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setIndex(value => Math.max(0, Math.min(entries.length - 1, value + (event.key === "ArrowDown" ? 1 : -1)))); }
      if (event.key === "Enter") { event.preventDefault(); void copy(event.shiftKey ? "username" : "password"); }
    }} />
    <p className="field-hint">{zh ? "↑ ↓ 选择 · Enter 复制密码 · Shift+Enter 复制用户名 · Esc 关闭" : "↑ ↓ choose · Enter copy password · Shift+Enter copy username · Esc close"}</p>
    {loading && <p role="status">{zh ? "正在搜索…" : "Searching…"}</p>}
    {error && <p role="alert" className="error">{zh ? "搜索失败，请修改搜索内容后重试。" : "Search failed. Change the query to retry."}</p>}
    {!loading && !error && !entries.length && <p>{zh ? "没有匹配的条目。" : "No matching entries."}</p>}
    <div id="quick-search-results" role="listbox" aria-label={zh ? "搜索结果" : "Search results"} className="quick-search-results">
      {entries.map((entry, position) => <div id={`quick-option-${position}`} key={entry.id} role="option" aria-selected={position === index} className={position === index ? "quick-option selected" : "quick-option"} onClick={() => { setIndex(position); input.current?.focus(); }}>
        <strong>{entry.title}</strong><span>{entry.username || "—"}</span><small>{entry.url || "—"}</small>
      </div>)}
    </div>
    <div className="button-row">
      <button className="primary" type="button" disabled={!current?.has_password || copying || loading} onClick={() => void copy("password")}>{zh ? "复制密码" : "Copy password"}</button>
      <button className="secondary" type="button" disabled={!current?.username || copying || loading} onClick={() => void copy("username")}>{zh ? "复制用户名" : "Copy username"}</button>
      <button className="secondary" type="button" disabled={!current || loading} onClick={() => current && onOpen(current)}>{zh ? "打开条目" : "Open entry"}</button>
      <AutoTypeButton entry={current} disabled={loading || copying} />
      <button className="secondary" type="button" onClick={onClose}>{zh ? "关闭" : "Close"}</button>
    </div>
  </dialog>;
}
