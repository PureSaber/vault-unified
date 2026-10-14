import { useEffect, useRef, useState } from "react";
import { api, mergeFields, type Entry, type MergeField, type MergeChange, type MergePreview } from "../api/client";
import { useI18n } from "../i18n";
import { templateDisplay } from "./template-display";

interface Props { ids: [string, string]; onCancel: () => void; onMerged: () => void }

export default function DuplicateMerge({ ids, onCancel, onMerged }: Props) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const dialog = useRef<HTMLDialogElement>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [choices, setChoices] = useState<MergeChange["choices"]>(() => Object.fromEntries(mergeFields.map(field => [field, "target"])) as MergeChange["choices"]);
  const [plan, setPlan] = useState<MergePreview | null>(null);
  const [revealed, setRevealed] = useState<MergeField[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const labels: Record<MergeField, string> = { title: zh ? "名称" : "Name", username: zh ? "用户名" : "Username", password: zh ? "密码" : "Password", url: zh ? "网站" : "Website", notes: zh ? "备注" : "Notes", tags: zh ? "标签" : "Tags", custom_fields: zh ? "自定义字段" : "Custom fields", totp_secret: zh ? "验证码密钥" : "Authenticator key", template_data: zh ? "模板详情与恢复码" : "Template details and recovery codes" };
  const sensitive = new Set<MergeField>(["password", "notes", "custom_fields", "totp_secret", "template_data"]);
  useEffect(() => {
    let cancelled = false;
    const before = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    void Promise.all(ids.map(id => api.getEntry(id, true))).then(values => { if (!cancelled) setEntries(values); }).catch(() => { if (!cancelled) setError(zh ? "无法读取账号，请关闭后重试。" : "Could not load accounts. Close and try again."); });
    const hide = () => setRevealed([]);
    window.addEventListener("blur", hide); document.addEventListener("visibilitychange", hide);
    return () => { cancelled = true; before?.focus(); window.removeEventListener("blur", hide); document.removeEventListener("visibilitychange", hide); };
  }, []);
  useEffect(() => {
    if (!revealed.length) return;
    const timer = window.setTimeout(() => setRevealed([]), 30_000);
    return () => window.clearTimeout(timer);
  }, [revealed]);
  const change: MergeChange = { target_id: ids[0], source_id: ids[1], choices };
  function cancel() {
    if (busy) return;
    if (plan) void api.cancelMerge(plan.preview_token).catch(() => {});
    onCancel();
  }
  async function preview() {
    setBusy(true); setError(""); setRevealed([]);
    try { setPlan(await api.previewMerge(change)); }
    catch (err) { setError(String(err).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }
  async function apply() {
    if (!plan || busy) return;
    setBusy(true); setError("");
    try { await api.applyMerge(change, plan.preview_token); onMerged(); }
    catch (err) { setPlan(null); setError(String(err).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }
  function display(field: MergeField, entry: Entry) {
    if (sensitive.has(field) && !revealed.includes(field)) return zh ? "已隐藏" : "Hidden";
    if (field === "template_data") return templateDisplay(entry.template_data, zh);
    const value = entry[field];
    if (value && !Array.isArray(value) && typeof value === "object") return JSON.stringify(value, null, 2);
    return Array.isArray(value) ? (value.length ? JSON.stringify(value, null, 2) : "—") : String(value || "—");
  }
  return <dialog className="card history-review" ref={dialog} aria-labelledby="merge-title" onCancel={event => { event.preventDefault(); cancel(); }}>
    <h2 id="merge-title">{zh ? "比较并合并账号" : "Compare and merge accounts"}</h2>
    <p>{zh ? "逐字段选择要保留的内容。保留第一条账号，两边历史与附件会一并保留；第二条账号移入回收站，保留 30 天。" : "Choose each value to keep. The first account remains with both histories and attachments; the second moves to trash for 30 days."}</p>
    {error && <p role="alert" className="error">{error}</p>}
    {!entries.length && !error && <p role="status">{zh ? "正在读取账号…" : "Loading accounts…"}</p>}
    {!plan && <div className="history-field-list">
      {entries.length === 2 && mergeFields.map(field => <fieldset className="history-field" key={field} disabled={busy}>
        <legend>{labels[field]}</legend>
        <div className="history-values">{entries.map((entry, index) => <div key={entry.id}>
          <label className="merge-choice"><input type="radio" name={`merge-${field}`} value={index === 0 ? "target" : "source"} checked={choices[field] === (index === 0 ? "target" : "source")} onChange={() => setChoices(current => ({ ...current, [field]: index === 0 ? "target" : "source" }))} />{`${index + 1}. ${entry.title}`}</label>
          <pre>{display(field, entry)}</pre>
        </div>)}</div>
        {sensitive.has(field) && <button type="button" className="secondary" onClick={() => setRevealed(current => current.includes(field) ? current.filter(value => value !== field) : [...current, field])}>{`${revealed.includes(field) ? (zh ? "隐藏" : "Hide") : (zh ? "显示" : "Show")} ${labels[field]}`}</button>}
      </fieldset>)}
    </div>}
    {plan && <div role="status">
      <p>{zh ? `保留账号：${plan.target_title}；移入回收站：${plan.source_title}` : `Kept account: ${plan.target_title}; moved to trash: ${plan.source_title}`}</p>
      <p>{zh ? `将保留 ${plan.history_count} 个历史版本、${plan.attachment_count} 个附件。` : `${plan.history_count} saved versions and ${plan.attachment_count} attachments will be retained.`}</p>
    </div>}
    <div className="button-row">
      <button type="button" className="secondary" autoFocus disabled={busy} onClick={cancel}>{zh ? "取消" : "Cancel"}</button>
      {plan && <button type="button" className="secondary" disabled={busy} onClick={() => { void api.cancelMerge(plan.preview_token).catch(() => {}); setPlan(null); }}>{zh ? "调整选择" : "Edit choices"}</button>}
      <button type="button" className="primary" disabled={busy || entries.length !== 2} onClick={() => void (plan ? apply() : preview())}>{busy ? (zh ? "处理中…" : "Working…") : plan ? (zh ? "确认合并" : "Confirm merge") : (zh ? "预览合并" : "Preview merge")}</button>
    </div>
  </dialog>;
}
