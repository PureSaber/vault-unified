import { useEffect, useRef, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-shell";
import { api, type Entry, type PasswordHealthItem, type PasswordHealthReport } from "../api/client";
import { useI18n } from "../i18n";

export default function PasswordHealth({ onOpen }: { onOpen: (entry: Entry) => void }) {
  const { locale } = useI18n(); const zh = locale === "zh";
  const [report, setReport] = useState<PasswordHealthReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [network, setNetwork] = useState(false);
  const [running, setRunning] = useState(false);
  const [exposure, setExposure] = useState<Record<string, number | "error">>({});
  const [filter, setFilter] = useState("attention");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(50);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  function stop() { generation.current++; controller.current?.abort(); controller.current = null; setRunning(false); }
  async function checkLocal() {
    stop(); const stamp = generation.current;
    setBusy(true); setError(""); setExposure({});
    try { const result = await api.passwordHealth(); if (stamp === generation.current) { setReport(result); setLimit(50); } }
    catch { if (stamp === generation.current) setError(zh ? "检查失败，请重试。" : "Check failed. Try again."); }
    finally { if (stamp === generation.current) setBusy(false); }
  }
  async function checkNetwork(items: PasswordHealthItem[]) {
    if (!network || running) return;
    stop(); const stamp = generation.current;
    const abort = new AbortController(); controller.current = abort; setRunning(true); setError("");
    const completed = new Set<string>();
    for (const item of items) {
      if (stamp !== generation.current) break;
      if (completed.has(item.id)) continue;
      try {
        const result = await api.checkExposure(item.id, true, abort.signal);
        if (stamp !== generation.current) break;
        result.matching_entry_ids.forEach(id => completed.add(id));
        setExposure(previous => ({ ...previous, ...Object.fromEntries(result.matching_entry_ids.map(id => [id, result.count])) }));
      } catch {
        if (stamp !== generation.current) break;
        setExposure(previous => ({ ...previous, [item.id]: "error" }));
        setError(zh ? "联网查询未完成，已停止后续请求。请刷新后重试。" : "The network check did not complete; remaining requests stopped. Refresh and retry.");
        break;
      }
    }
    if (stamp === generation.current) { controller.current = null; setRunning(false); }
  }
  async function edit(item: PasswordHealthItem) {
    setError("");
    const stamp = generation.current;
    try { const entry = await api.getEntry(item.id, false); if (stamp === generation.current) onOpen(entry); }
    catch { setError(zh ? "条目无法打开，请刷新检查结果。" : "Could not open the login. Refresh the results."); }
  }
  async function visit(url: string) {
    setError("");
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "https:" || parsed.username || parsed.password) throw new Error();
      if (isTauri()) await open(parsed.href); else window.open(parsed.href, "_blank", "noopener,noreferrer");
    } catch { setError(zh ? "无法打开网站，请在浏览器中进入账号设置。" : "Could not open the website. Open its account settings in your browser."); }
  }
  const results = report?.entries.filter(item => {
    const count = exposure[item.id];
    const matches = filter === "all" || (filter === "weak" && item.weak) || (filter === "reused" && item.reused) || (filter === "exposed" && typeof count === "number" && count > 0) || (filter === "attention" && (item.weak || item.reused || item.score === null || (typeof count === "number" && count > 0)));
    return matches && `${item.title} ${item.username}`.toLocaleLowerCase().includes(query.toLocaleLowerCase());
  }) || [];
  return <section className="settings-section" aria-labelledby="password-health-heading">
    <h3 className="section-title" id="password-health-heading">{zh ? "密码检查" : "Password check"}</h3>
    <p className="field-hint">{zh ? "在本机检查有效登录条目的弱密码与重复密码。" : "Check active logins for weak and reused passwords on this computer."}</p>
    <button className="secondary" type="button" disabled={busy || running} onClick={() => void checkLocal()}>{busy ? (zh ? "正在检查…" : "Checking…") : (zh ? "检查本地密码" : "Check local passwords")}</button>
    {error && <p role="alert" className="error">{error}</p>}
    {report && <>
      <p role="status">{zh ? `已检查 ${report.total} 个账号 · 弱密码 ${report.weak} · 重复密码 ${report.reused}` : `${report.total} logins checked · ${report.weak} weak · ${report.reused} reused`}</p>
      {report.unscored > 0 && <p className="field-hint">{zh ? `${report.unscored} 个长密码未做强度评估，仍已检查重复使用。` : `${report.unscored} long passwords were checked for reuse without a strength estimate.`}</p>}
      <label className="checkbox-label"><input type="checkbox" checked={network} disabled={busy} onChange={event => { setNetwork(event.target.checked); if (!event.target.checked) stop(); }} />{zh ? "本次允许联网查询泄露记录" : "Allow exposure lookups for this visit"}</label>
      <p className="field-hint">{zh ? "查询使用 Have I Been Pwned，仅发送密码 SHA-1 的前 5 位；密码、账号和完整哈希留在本机。" : "Lookups use Have I Been Pwned and send only the first 5 SHA-1 characters. Passwords, usernames and full hashes stay here."}</p>
      <div className="button-row"><button className="secondary" type="button" disabled={!network || running || !report.total} onClick={() => void checkNetwork(report.entries)}>{zh ? "查询这些账号的泄露记录" : "Check these logins for exposure"}</button>{running && <button type="button" className="secondary" onClick={stop}>{zh ? "停止查询" : "Stop checking"}</button>}</div>
      {running && <p role="status">{zh ? `正在查询，已有 ${Object.keys(exposure).length} 个结果…` : `Checking; ${Object.keys(exposure).length} results so far…`}</p>}
      <p className="field-hint">{zh ? "先在网站修改密码，再更新这里保存的登录信息。编辑器可生成新密码，生成历史可随时找回和复制。" : "Change the password on the website, then update the saved login here. The editor can generate passwords; generated history lets you recover and copy them."}</p>
      <div className="button-row">
        <label>{zh ? "筛选问题" : "Filter findings"}<select aria-label={zh ? "筛选问题" : "Filter findings"} value={filter} onChange={event => { setFilter(event.target.value); setLimit(50); }}><option value="attention">{zh ? "需要处理" : "Needs attention"}</option><option value="all">{zh ? "全部" : "All"}</option><option value="weak">{zh ? "弱密码" : "Weak"}</option><option value="reused">{zh ? "重复密码" : "Reused"}</option><option value="exposed">{zh ? "已泄露" : "Exposed"}</option></select></label>
        <label>{zh ? "查找账号" : "Find a login"}<input value={query} onChange={event => { setQuery(event.target.value); setLimit(50); }} /></label>
      </div>
      {!results.length && <p>{zh ? "此筛选下没有待处理账号。" : "No logins to address with this filter."}</p>}
      <div className="history-field-list">{results.slice(0, limit).map(item => <section key={item.id} className="history-field" aria-label={item.title}>
        <strong>{item.title}</strong><p>{item.username || "—"}</p>
        <p>{[item.weak ? (zh ? "弱密码" : "Weak password") : "", item.reused ? (zh ? `与其他 ${item.reuse_count - 1} 个账号重复` : `Reused by ${item.reuse_count - 1} other logins`) : "", item.score === null ? (zh ? "强度未评估" : "Strength not assessed") : ""].filter(Boolean).join(" · ")}</p>
        {exposure[item.id] !== undefined && <p>{exposure[item.id] === "error" ? (zh ? "查询失败，可重试" : "Lookup failed; retry") : exposure[item.id] === 0 ? (zh ? "此密码未出现在查询结果中" : "This password was not found in the lookup") : (zh ? `此密码出现在泄露记录中（${exposure[item.id]} 次）` : `This password appears in exposure records (${exposure[item.id]} times)`)}</p>}
        <div className="button-row">
          {item.change_url && <button type="button" className="secondary" onClick={() => void visit(item.change_url)}>{zh ? "打开网站改密" : "Open website to change password"}</button>}
          <button type="button" className="secondary" onClick={() => void edit(item)}>{zh ? "更新已存密码" : "Update saved password"}</button>
          <button type="button" className="secondary" disabled={!network || running} onClick={() => void checkNetwork([item])}>{zh ? "查询泄露记录" : "Check exposure"}</button>
        </div>
      </section>)}</div>
      {results.length > limit && <button type="button" className="secondary" onClick={() => setLimit(value => value + 50)}>{zh ? "显示更多" : "Show more"}</button>}
    </>}
  </section>;
}
