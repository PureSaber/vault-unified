import { useEffect, useRef, useState } from "react";
import { api, type Entry, type TemplateData } from "../api/client";
import { templateDisplay } from "./template-display";
import { useI18n } from "../i18n";

export const historyFields = ["title", "username", "password", "url", "notes", "tags", "entry_type", "custom_fields", "totp_secret", "template_data"] as const;
export type HistoryField = typeof historyFields[number];
export type HistoryValues = Pick<Entry, HistoryField>;

interface Props {
  entryId: string;
  historyId: string;
  current: HistoryValues;
  onRestore: (entry: Entry, fields: HistoryField[]) => void;
  onCancel: () => void;
}

export default function HistoryReview({ entryId, historyId, current, onRestore, onCancel }: Props) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [previous, setPrevious] = useState<Entry | null>(null);
  const [selected, setSelected] = useState<HistoryField[]>([]);
  const [revealed, setRevealed] = useState<HistoryField[]>([]);
  const [error, setError] = useState(false);
  const initialCurrent = useRef(current);
  const labels: Record<HistoryField, string> = {
    title: zh ? "名称" : "Name", username: zh ? "用户名" : "Username", password: zh ? "密码" : "Password",
    url: zh ? "网站" : "Website", notes: zh ? "备注" : "Notes", tags: zh ? "标签" : "Tags",
    entry_type: zh ? "内容类型" : "Content type", custom_fields: zh ? "自定义字段" : "Custom fields",
    totp_secret: zh ? "验证码密钥" : "Authenticator key",
    template_data: zh ? "模板详情与恢复码" : "Template details and recovery codes",
  };
  const sensitive = new Set<HistoryField>(["password", "notes", "totp_secret", "custom_fields", "template_data"]);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    dialogRef.current?.showModal();
    return () => { before?.focus(); };
  }, []);
  useEffect(() => {
    let cancelled = false;
    void api.previewEntryHistory(entryId, historyId).then(result => {
      if (cancelled) return;
      const previous = { ...result.entry, template_data: result.entry.template_data || {} };
      setPrevious(previous);
      setSelected(historyFields.filter(field => JSON.stringify(initialCurrent.current[field]) !== JSON.stringify(previous[field])));
    }).catch(() => { if (!cancelled) setError(true); });
    const hide = () => setRevealed([]);
    window.addEventListener("blur", hide);
    document.addEventListener("visibilitychange", hide);
    return () => { cancelled = true; window.removeEventListener("blur", hide); document.removeEventListener("visibilitychange", hide); };
  }, [entryId, historyId]);
  useEffect(() => {
    if (!revealed.length) return;
    const timer = window.setTimeout(() => setRevealed([]), 30_000);
    return () => window.clearTimeout(timer);
  }, [revealed]);
  const changed = previous ? historyFields.filter(field => JSON.stringify(current[field]) !== JSON.stringify(previous[field])) : [];
  function display(field: HistoryField, value: unknown) {
    if (sensitive.has(field) && !revealed.includes(field)) return zh ? "已隐藏" : "Hidden";
    if (field === "template_data") return templateDisplay(value as TemplateData, zh);
    if (field === "entry_type") {
      const types: Record<string, string> = { login: zh ? "登录信息" : "Login", secure_note: zh ? "安全备注" : "Secure note", card: zh ? "卡片" : "Card", identity: zh ? "身份信息" : "Identity", ssh_key: zh ? "SSH 密钥" : "SSH key", recovery_code: zh ? "恢复码" : "Recovery codes", software_license: zh ? "软件许可证" : "Software license", api_credential: zh ? "API 凭据" : "API credential" };
      return types[String(value)] || String(value);
    }
    if (Array.isArray(value)) return value.length ? JSON.stringify(value, null, 2) : "—";
    if (value && typeof value === "object") return JSON.stringify(value, null, 2);
    return String(value || "—");
  }
  return <dialog ref={dialogRef} className="card history-review" aria-labelledby="history-review-title" onCancel={event => { event.preventDefault(); onCancel(); }}>
    <h2 id="history-review-title">{zh ? "比较并恢复历史字段" : "Compare and restore history fields"}</h2>
    <p>{zh ? "选择要恢复的字段。先载入草稿，保存后才会修改密码库；现有附件保持不变。" : "Choose fields to restore. Load them into the draft, then save to update the vault. Existing attachments are retained."}</p>
    {error && <p className="error" role="alert">{zh ? "无法读取该版本，请关闭后重试。" : "Could not load this version. Close and try again."}</p>}
    {!previous && !error && <p role="status">{zh ? "正在读取历史版本…" : "Loading history…"}</p>}
    {previous && !changed.length && <p>{zh ? "此版本与当前草稿的字段相同。" : "This version has the same fields as the current draft."}</p>}
    <div className="history-field-list">
      {previous && changed.map(field => <fieldset key={field} className="history-field">
        <legend><label><input type="checkbox" checked={selected.includes(field)} onChange={event => setSelected(values => event.target.checked ? [...values, field] : values.filter(value => value !== field))} />{labels[field]}</label></legend>
        <div className="history-values">
          <div><strong>{zh ? "当前草稿" : "Current draft"}</strong><pre>{display(field, current[field])}</pre></div>
          <div><strong>{zh ? "历史版本" : "Historical version"}</strong><pre>{display(field, previous[field])}</pre></div>
        </div>
        {sensitive.has(field) && <button type="button" className="secondary" onClick={() => setRevealed(values => values.includes(field) ? values.filter(value => value !== field) : [...values, field])}>{`${revealed.includes(field) ? (zh ? "隐藏" : "Hide") : (zh ? "显示" : "Show")} ${labels[field]}`}</button>}
      </fieldset>)}
    </div>
    <div className="button-row">
      <button type="button" className="secondary" autoFocus onClick={onCancel}>{zh ? "取消" : "Cancel"}</button>
      <button type="button" className="primary" disabled={!previous || !selected.length} onClick={() => previous && onRestore(previous, selected)}>{zh ? "载入草稿" : "Load draft"}</button>
    </div>
  </dialog>;
}
