import { useEffect, useRef, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-shell";
import { api, type Entry, type TotpCode } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import AutoTypeButton from "./AutoTypeButton";
import Icon from "./Icon";

const TEMPLATE_TYPES: Entry["entry_type"][] = ["recovery_code", "software_license", "api_credential"];

/** The unrevealed response blanks template data and every custom-field value,
 * so items that have them load the full entry and keep only non-secret
 * metadata. Secret values are dropped before anything reaches component state. */
function metadataOnly(full: Entry): Entry {
  const template = full.template_data || {};
  return {
    ...full, password: "", notes: "", totp_secret: "",
    custom_fields: full.custom_fields.map(field => field.concealed ? { ...field, value: "" } : field),
    template_data: {
      registered_to: template.registered_to, expires_on: template.expires_on,
      environment: template.environment, scopes: template.scopes,
      recovery_codes: template.recovery_codes?.map(code => ({ ...code, value: "" })),
    },
  };
}

export default function ItemDetail({ entry, onEdit, onBack, onShare }: {
  entry: Entry; onEdit: (entry: Entry) => void; onBack: () => void; onShare: (entry: Entry) => void;
}) {
  const { t, locale } = useI18n(); const zh = locale === "zh"; const { showToast } = useToast();
  const [item, setItem] = useState<Entry | null>(null);
  const [error, setError] = useState(false);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [totp, setTotp] = useState<(TotpCode & { deadline: number }) | null>(null);
  const [tick, setTick] = useState(performance.now());
  const generation = useRef(0);
  const expiry = useRef<ReturnType<typeof setTimeout>>();
  const codeRefresh = useRef<ReturnType<typeof setTimeout>>();
  const heading = useRef<HTMLHeadingElement>(null);
  function hide() {
    ++generation.current; clearTimeout(expiry.current); clearTimeout(codeRefresh.current);
    setSecrets({}); setTotp(null);
  }
  useEffect(() => {
    let active = true; let request = 0;
    const load = () => {
      const stamp = ++request;
      hide(); setItem(null); setError(false);
      // Decide from the current unrevealed entry, not the possibly stale prop
      // (for example the pre-edit object shown again after saving).
      void api.getEntry(entry.id, false)
        .then(async value => {
          if (!active || stamp !== request) return;
          if (!TEMPLATE_TYPES.includes(value.entry_type) && !value.custom_fields.length) { setItem(value); return; }
          const full = await api.getEntry(entry.id, true);
          if (active && stamp === request) setItem(metadataOnly(full));
        })
        .catch(() => { if (active && stamp === request) setError(true); });
    };
    load();
    window.addEventListener("vault-entries-changed", load);
    window.addEventListener("blur", hide); document.addEventListener("visibilitychange", hide);
    return () => {
      active = false; window.removeEventListener("vault-entries-changed", load); ++generation.current; clearTimeout(expiry.current); clearTimeout(codeRefresh.current);
      window.removeEventListener("blur", hide); document.removeEventListener("visibilitychange", hide);
    };
  }, [entry.id, entry.updated_at]);
  useEffect(() => {
    // In the single-pane layout the list (and its focused row) is hidden.
    if (window.matchMedia?.("(max-width: 850px)").matches) heading.current?.focus();
  }, [entry.id]);
  useEffect(() => {
    if (!totp) return;
    const interval = window.setInterval(() => setTick(performance.now()), 1000);
    return () => clearInterval(interval);
  }, [totp]);

  async function reveal(field: string) {
    if (secrets[field] !== undefined) { hide(); return; }
    hide(); const stamp = generation.current;
    try {
      const full = await api.getEntry(entry.id, true);
      if (stamp !== generation.current) return;
      const value = field === "password" ? full.password : field === "notes" ? full.notes : field.startsWith("recovery:") ? full.template_data?.recovery_codes?.find(code => code.id === field.slice(9))?.value || "" : full.custom_fields[Number(field)]?.value || "";
      setSecrets({ [field]: value });
      expiry.current = setTimeout(hide, 30_000);
    } catch { if (stamp === generation.current) showToast(zh ? "无法显示内容，请重试。" : "Could not show this value. Try again.", "error"); }
  }
  async function showCode() {
    if (totp) { hide(); return; }
    hide(); const stamp = generation.current;
    const refresh = async () => {
      const started = performance.now();
      try {
        const value = await api.getTotp(entry.id);
        if (stamp !== generation.current) return;
        const remaining = Math.max(0, value.remaining_seconds * 1000 - (performance.now() - started));
        setTotp({ ...value, deadline: performance.now() + remaining });
        codeRefresh.current = setTimeout(() => void refresh(), Math.max(100, remaining + 40));
      } catch { if (stamp === generation.current) { hide(); showToast(zh ? "无法读取验证码，请重试。" : "Could not read the verification code. Try again.", "error"); } }
    };
    expiry.current = setTimeout(hide, 30_000); await refresh();
  }
  async function copy(field: "password" | "username" | "totp") {
    const stamp = generation.current;
    try {
      const result = field === "totp" ? await api.copyTotp(entry.id) : await api.copy(entry.id, field);
      if (stamp !== generation.current) return;
      showToast(zh ? `已复制，${result.clears_in_seconds} 秒后清除剪贴板` : `Copied; clipboard clears in ${result.clears_in_seconds} seconds`);
    } catch { if (stamp === generation.current) showToast(zh ? "复制失败，请重试。" : "Could not copy. Try again.", "error"); }
  }
  const current = item || entry;
  const copyButton = (field: "password" | "username" | "totp", label: string) => <button type="button" className="ghost detail-icon" aria-label={label} title={label} disabled={!item} onClick={() => void copy(field)}><Icon name="copy" size={17} /></button>;
  const revealButton = (field: string, label: string) => <button type="button" className="ghost detail-icon" aria-label={label} title={label} disabled={!item} aria-pressed={secrets[field] !== undefined} onClick={() => void reveal(field)}><Icon name="eye" size={17} /></button>;
  const remaining = totp ? Math.max(0, Math.ceil((totp.deadline - tick) / 1000)) : 0;
  let website = ""; try { const url = new URL(current.url); if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) website = url.href; } catch { /* Non-web credentials need no external link. */ }
  async function openWebsite(event: React.MouseEvent) {
    // WebView2 does not hand target=_blank links to the default browser.
    event.preventDefault();
    try { if (isTauri()) await open(website); else window.open(website, "_blank", "noopener,noreferrer"); }
    catch { showToast(zh ? "无法打开网站，请在浏览器中手动访问。" : "Could not open the website. Open it in your browser.", "error"); }
  }
  const templateLabels = { registered_to: zh ? "登记人" : "Registered to", expires_on: zh ? "到期日" : "Expiry date", environment: zh ? "环境" : "Environment", scopes: zh ? "权限范围" : "Scopes" } as const;
  const templateRows = (Object.keys(templateLabels) as Array<keyof typeof templateLabels>)
    .map(key => [key, item?.template_data?.[key]] as const).filter(([, value]) => Boolean(value));
  const count = (value: number, one: string, many: string) => `${value} ${value === 1 ? one : many}`;
  const active = (current.state || "active") === "active";
  return <article className="item-detail" aria-label={zh ? "账号详情" : "Account details"}>
    <div className="detail-toolbar">
      <button type="button" className="ghost detail-back" onClick={onBack}><Icon name="back" size={16} />{zh ? "返回密码" : "Back to passwords"}</button>
      <button type="button" className="secondary" disabled={!item} onClick={() => { hide(); onEdit(current); }}><Icon name="edit" size={16} />{t("list.edit")}</button>
    </div>
    <div className="detail-heading"><span className="account-avatar large" aria-hidden="true">{current.title.slice(0, 1).toUpperCase()}</span><div><h2 ref={heading} tabIndex={-1}>{current.title}</h2><p className="field-hint">{current.entry_type === "secure_note" ? (zh ? "安全备注" : "Secure note") : current.entry_type === "recovery_code" ? (zh ? "恢复码" : "Recovery codes") : current.url || (zh ? "保存在这台设备" : "Stored on this device")}</p></div></div>
    {error && <p role="alert" className="error">{zh ? "无法读取条目，请重新选择后重试。" : "Could not load this item. Select it again to retry."}</p>}
    {!item && !error && <p role="status">{zh ? "正在读取…" : "Loading…"}</p>}
    {current.state && current.state !== "active" && <p className="context-notice context-notice-warning">{current.state === "trash" ? (zh ? "已在回收站，不参与浏览器填充。" : "In trash; excluded from browser filling.") : (zh ? "已归档，不参与浏览器填充。" : "Archived; excluded from browser filling.")}</p>}
    <dl className="detail-fields">
      {current.username && <div><dt>{zh ? "用户名" : "Username"}</dt><dd><span>{current.username}</span>{copyButton("username", t("list.copyUser"))}</dd></div>}
      {current.has_password && <div><dt>{["software_license", "api_credential"].includes(current.entry_type) ? (zh ? "密钥" : "Key") : (zh ? "密码" : "Password")}</dt><dd><span className="secret-value">{secrets.password ?? "••••••••••••"}</span>{revealButton("password", secrets.password !== undefined ? t("list.hidePassword") : t("list.showPassword"))}{copyButton("password", t("list.copyPass"))}</dd></div>}
      {current.has_totp_secret && <div><dt>{zh ? "验证码" : "Verification code"}</dt><dd><button className="ghost code-reveal" type="button" disabled={!item} onClick={() => void showCode()} aria-label={totp && remaining > 0 ? undefined : (zh ? "显示验证码" : "Show verification code")} title={totp ? (zh ? "隐藏验证码" : "Hide verification code") : (zh ? "显示验证码" : "Show verification code")}>{totp && remaining > 0 ? totp.code : "••• •••"}</button>{totp && <span className="field-hint" role="timer">{zh ? `${remaining} 秒` : `${remaining}s`}</span>}{copyButton("totp", zh ? "复制验证码" : "Copy verification code")}</dd></div>}
      {website && <div><dt>{zh ? "网站" : "Website"}</dt><dd><a href={website} rel="noreferrer noopener" onClick={event => void openWebsite(event)}>{current.url}</a></dd></div>}
      {current.tags.length > 0 && <div><dt>{zh ? "标签" : "Tags"}</dt><dd><span className="entry-chips">{current.tags.map(tag => <span key={tag} className="chip">{tag}</span>)}</span></dd></div>}
      {current.has_notes && <div><dt>{zh ? "备注" : "Notes"}</dt><dd><span className="detail-notes">{secrets.notes ?? "••••••••"}</span>{revealButton("notes", secrets.notes !== undefined ? (zh ? "隐藏备注" : "Hide notes") : (zh ? "显示备注" : "Show notes"))}</dd></div>}
      {item?.custom_fields.map((field, index) => <div key={`${index}-${field.label}`}><dt>{field.label}</dt><dd><span>{field.concealed ? secrets[String(index)] ?? "••••••••" : field.value}</span>{field.concealed && revealButton(String(index), zh ? `显示 ${field.label}` : `Show ${field.label}`)}</dd></div>)}
    </dl>
    {templateRows.length > 0 && <dl className="detail-fields">
      {templateRows.map(([key, value]) => <div key={key}><dt>{templateLabels[key]}</dt><dd>{value}</dd></div>)}
    </dl>}
    {item?.template_data?.recovery_codes?.length ? <section className="detail-section" aria-label={zh ? "恢复码" : "Recovery codes"}>
      <h3>{zh ? "恢复码" : "Recovery codes"}</h3>
      {item.template_data.recovery_codes.map((code, index) => <div className="recovery-code-row" key={code.id}>
        <span>{index + 1}</span><span className="secret-value">{secrets[`recovery:${code.id}`] ?? "••••••••"}</span>
        <span className="field-hint">{code.used_at ? (zh ? "已使用" : "Used") : (zh ? "未使用" : "Unused")}</span>
        {revealButton(`recovery:${code.id}`, zh ? `显示恢复码 ${index + 1}` : `Show recovery code ${index + 1}`)}
      </div>)}
      <button type="button" className="secondary" onClick={() => { hide(); onEdit(item); }}>{zh ? "编辑使用状态" : "Edit usage status"}</button>
    </section> : null}
    {item && <div className="detail-section">
      <details><summary>{zh ? `附件与历史 · ${item.attachments.length} 个附件 · ${item.history_count} 个版本` : `Attachments and history · ${count(item.attachments.length, "file", "files")} · ${count(item.history_count, "version", "versions")}`}</summary>
        {item.attachments.map(file => <p key={file.id}>{file.filename} <span className="field-hint">{Math.ceil(file.size / 1024)} KiB</span></p>)}
        <button type="button" className="secondary" onClick={() => onEdit(item)}>{zh ? "管理附件与历史" : "Manage attachments and history"}</button>
      </details>
      {(item.passkeys?.length || 0) > 0 && <details><summary>{zh ? `通行密钥（${item.passkeys?.length}）` : `Passkeys (${item.passkeys?.length})`}</summary><p className="field-hint">{zh ? "登录时由浏览器请求并确认使用。" : "The browser requests approval when signing in."}</p></details>}
    </div>}
    <div className="detail-bottom"><span className="field-hint">{zh ? "修改于 " : "Updated "}{new Date(current.updated_at).toLocaleString(zh ? "zh-CN" : "en-US")}</span>
      {item && active && <div className="button-row"><AutoTypeButton entry={item} /><button type="button" className="ghost" onClick={() => { hide(); onShare(item); }}><Icon name="sharing" size={16} />{zh ? "分享…" : "Share…"}</button></div>}
    </div>
  </article>;
}
