import { useEffect, useRef, useState } from "react";
import { api, type PersonalSyncSetup, type PersonalSyncPreview, type PersonalSyncStatus, type PersonalSyncConflicts, type PersonalSyncChoice } from "../api/client";
import { useI18n } from "../i18n";
import ConfirmDialog from "./ConfirmDialog";
import PathPicker from "./PathPicker";

function fieldName(path: string[], zh: boolean) {
  const names: Record<string, [string, string]> = { title: ["名称", "Name"], username: ["用户名", "Username"], password: ["密码", "Password"], url: ["网址", "Website"], notes: ["备注", "Notes"], tags: ["标签", "Tags"], totp_secret: ["验证码密钥", "Authenticator key"], attachments: ["附件", "Attachments"], history: ["历史版本", "History"], custom_fields: ["自定义字段", "Custom fields"], favorite: ["收藏", "Favorite"], state: ["条目状态", "Entry state"], template_data: ["模板字段", "Template fields"], website_rules: ["网站规则", "Website rules"] };
  if (!path.length) return zh ? "删除或修改" : "Deletion or edit";
  for (const part of [...path].reverse()) if (names[part]) return names[part][zh ? 0 : 1];
  return zh ? "其他内容" : "Other content";
}

function Conflicts({ onDone }: { onDone: () => void }) {
  const { locale } = useI18n(); const zh = locale === "zh";
  const [data, setData] = useState<PersonalSyncConflicts | null>(null);
  const [object, setObject] = useState("");
  const [choices, setChoices] = useState<Record<string, "local" | "remote">>({});
  const [revealed, setRevealed] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  async function load(reveal = false) {
    const stamp = ++sequence.current;
    setError("");
    try {
      const result = await api.personalSyncConflicts(reveal);
      if (stamp !== sequence.current) return;
      setData(result); setRevealed(reveal); setChoices({}); setConfirm(false);
      setObject(current => result.items.some(item => item.object === current) ? current : result.items[0]?.object || "");
    } catch { if (stamp === sequence.current) setError(zh ? "无法读取冲突，请刷新重试。" : "Could not load conflicts. Refresh and retry."); }
  }
  useEffect(() => { void load(); return () => { sequence.current++; }; }, []);
  useEffect(() => {
    if (!revealed) return;
    const hide = () => { if (document.visibilityState !== "visible" || !document.hasFocus()) void load(); };
    const timer = window.setTimeout(() => void load(), 45_000);
    window.addEventListener("blur", hide); document.addEventListener("visibilitychange", hide);
    return () => { window.clearTimeout(timer); window.removeEventListener("blur", hide); document.removeEventListener("visibilitychange", hide); };
  }, [revealed]);
  const items = data?.items.filter(item => item.object === object) || [];
  const groups = new Map(data?.items.map(item => [item.object, item.title || (zh ? "密码库内容" : "Vault content")]) || []);
  async function apply() {
    if (!data || busy) return;
    setConfirm(false); setBusy(true); setError("");
    try { await api.resolvePersonalSync(data.generation, choices); await load(); onDone(); }
    catch { setError(zh ? "内容已变化或保存失败，请刷新后重新选择。" : "Content changed or could not be saved. Refresh and choose again."); }
    finally { setBusy(false); }
  }
  function display(value: PersonalSyncChoice["local"]) {
    if (!value.present) return zh ? "已永久删除" : "Permanently removed";
    const state = value.state === "trash" ? (zh ? "回收站" : "Trash") : value.state === "archived" ? (zh ? "归档" : "Archived") : value.state ? (zh ? "正常" : "Active") : "";
    return (state ? `${state} · ` : "") + (value.value || (zh ? "空值" : "Empty")) + (value.truncated ? "…" : "");
  }
  return <section className="nested-panel" aria-labelledby="personal-sync-conflicts-heading">
    <h4 id="personal-sync-conflicts-heading">{zh ? "处理多电脑修改冲突" : "Review changes from other computers"}</h4>
    <p className="field-hint">{zh ? "分别选择保留哪一边。确认后先保存在这台电脑，下次同步会把选择发送给其他电脑。" : "Choose which value to keep for each field. Confirmation saves locally; the next sync sends your choices to the other computers."}</p>
    <div className="button-row"><button className="secondary" disabled={busy} onClick={() => void load()}>{zh ? "刷新冲突" : "Refresh conflicts"}</button><button className="secondary" disabled={busy || !items.length} onClick={() => void load(!revealed)}>{revealed ? (zh ? "隐藏冲突内容" : "Hide conflict values") : (zh ? "显示冲突内容" : "Reveal conflict values")}</button></div>
    {error && <p role="alert" className="error">{error}</p>}
    {data && !data.items.length && <p role="status">{zh ? "没有待处理冲突。" : "No conflicts to resolve."}</p>}
    {items.length > 0 && <>
      <div className="field"><label htmlFor="sync-conflict-entry">{zh ? "需要处理的条目" : "Entry to review"}</label><select id="sync-conflict-entry" disabled={busy} value={object} onChange={event => { setObject(event.target.value); setChoices({}); }}>{[...groups].map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></div>
      {items.map((item, index) => <fieldset className="personal-sync-choice" key={item.id} disabled={busy}>
        <legend>{fieldName(item.path, zh)}</legend>
        {(["local", "remote"] as const).map(side => <label className="personal-sync-option" key={side}>
          <input type="radio" name={`sync-choice-${index}`} value={side} checked={choices[item.id] === side} onChange={() => setChoices(current => ({ ...current, [item.id]: side }))} />
          <span><strong>{side === "local" ? (zh ? "保留这台电脑" : "Keep this computer") : (zh ? `采用其他电脑（${item.device}）` : `Use other computer (${item.device})`)}</strong><span className="personal-sync-value">{display(item[side])}</span></span>
        </label>)}
      </fieldset>)}
      <button className="primary" disabled={busy || items.some(item => !choices[item.id])} onClick={() => setConfirm(true)}>{zh ? "确认所选内容" : "Confirm selected values"}</button>
    </>}
    <ConfirmDialog open={confirm} idPrefix="personal-sync-resolution" title={zh ? "保存冲突处理结果" : "Save conflict choices"} message={zh ? `将按你的选择处理 ${items.length} 处冲突。` : `Apply your choices to ${items.length} conflicting fields.`} onCancel={() => setConfirm(false)} onConfirm={() => void apply()} />
  </section>;
}

const blank: PersonalSyncSetup = { provider: "folder", mode: "create", location: "", label: "", automatic: false, code: "", username: "", password: "" };

export default function PersonalSync() {
  const { locale } = useI18n(); const zh = locale === "zh";
  const [status, setStatus] = useState<PersonalSyncStatus | null>(null);
  const [setup, setSetup] = useState<PersonalSyncSetup>(blank);
  const [expanded, setExpanded] = useState(false);
  const [preview, setPreview] = useState<PersonalSyncPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [errorDetail, setErrorDetail] = useState("");
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [automatic, setAutomatic] = useState(false);
  const [showConflicts, setShowConflicts] = useState(false);
  const [confirmation, setConfirmation] = useState<"connect" | "disconnect" | null>(null);
  const alive = useRef(true); const working = useRef(false); const pending = useRef<string | null>(null);
  async function refresh() {
    try { const value = await api.personalSyncStatus(); if (alive.current) setStatus(value); }
    catch { if (alive.current) setError(zh ? "无法读取同步设置，请重新解锁后重试。" : "Could not load sync settings. Unlock again and retry."); }
  }
  useEffect(() => {
    alive.current = true; void refresh();
    const update = () => { void refresh(); };
    window.addEventListener("vault-personal-sync-updated", update);
    return () => { alive.current = false; window.removeEventListener("vault-personal-sync-updated", update); if (pending.current) void api.cancelPersonalSync(pending.current).catch(() => {}); };
  }, []);
  useEffect(() => { setLabel(status?.label || ""); setAutomatic(Boolean(status?.automatic)); }, [status?.label, status?.automatic]);
  useEffect(() => {
    if (!code) return;
    const hide = () => setCode(""); const timer = window.setTimeout(hide, 45_000);
    window.addEventListener("blur", hide); document.addEventListener("visibilitychange", hide);
    return () => { window.clearTimeout(timer); window.removeEventListener("blur", hide); document.removeEventListener("visibilitychange", hide); };
  }, [code]);
  function changed() { window.dispatchEvent(new Event("vault-personal-sync-updated")); }
  async function action(work: () => Promise<void>) {
    if (working.current) return;
    working.current = true; setBusy(true); setError(""); setErrorDetail(""); setNotice("");
    try { await work(); }
    catch (failure) {
      if (alive.current) setError(zh ? "操作未完成。请检查连接、连接码或密码库是否已变化，再重试。" : "Operation did not complete. Check the connection, connection code and recent vault changes, then retry.");
      if (alive.current && failure instanceof Error) setErrorDetail(failure.message);
    } finally { working.current = false; if (alive.current) { setBusy(false); await refresh(); } }
  }
  async function prepare(event: React.FormEvent) {
    event.preventDefault();
    await action(async () => {
      const result = await api.previewPersonalSync(setup);
      if (!alive.current) { void api.cancelPersonalSync(result.preview_token).catch(() => {}); return; }
      pending.current = result.preview_token; setPreview(result);
      setSetup(current => ({ ...current, password: "", code: "" }));
    });
  }
  function cancelPreview() {
    if (pending.current) void api.cancelPersonalSync(pending.current).catch(() => {});
    pending.current = null; setPreview(null); setConfirmation(null); setSetup(current => ({ ...current, password: "", code: "" }));
  }
  async function confirm() {
    const mode = confirmation; setConfirmation(null);
    await action(async () => {
      if (mode === "connect" && preview) {
        pending.current = null; setPreview(null);
        const result = await api.connectPersonalSync(preview.preview_token);
        if (!alive.current) return;
        setPreview(null); setExpanded(false); setSetup(blank);
        setNotice(result.backup_path ? (zh ? `已连接。合并前的加密备份：${result.backup_path}` : `Connected. Encrypted backup before merging: ${result.backup_path}`) : (zh ? "已连接。点击“立即同步”上传这台电脑的修改。" : "Connected. Select Sync now to upload this computer's changes."));
      } else if (mode === "disconnect") {
        const result = await api.disconnectPersonalSync();
        if (!alive.current) return;
        setCode(""); setShowConflicts(false);
        setNotice(result.cleanup_pending ? (zh ? "同步已停止。Windows 凭据尚未清理，请再次点击断开以重试。" : "Sync stopped. Windows credential cleanup is pending; disconnect again to retry.") : (zh ? "已断开，这台电脑的数据已保留。" : "Disconnected. This computer's data was retained."));
      }
      changed();
    });
  }
  return <section className="settings-section personal-sync" aria-labelledby="personal-sync-heading">
    <h3 id="personal-sync-heading" className="section-title">{zh ? "多电脑完整同步" : "Full vault sync between computers"}</h3>
    <p className="field-hint">{zh ? "使用你自己的同步文件夹或 WebDAV，传输加密的账号、附件和历史。两台电脑各自使用主密码，无需云账号。" : "Use your own synchronized folder or WebDAV to transfer encrypted accounts, attachments and history. Each computer keeps its own master password; no cloud account is needed."}</p>
    {error && <p className="error" role="alert">{error}</p>}
    {errorDetail && <details><summary>{zh ? "错误详情" : "Error details"}</summary><p>{errorDetail}</p></details>}
    {notice && <p role="status">{notice}</p>}
    {status && !status.connected && <>
      {status.reconnect && <p className="field-hint">{zh ? "这是恢复或迁移后的密码库，请用另一台电脑的连接码重新加入。" : "This vault was restored or moved. Rejoin with the connection code from another computer."}</p>}
      {status.upgrade_required && <p className="field-hint">{zh ? "请先到“安全与恢复”升级密码库格式，再启用完整同步。" : "First upgrade the vault format in Security & recovery, then enable full synchronization."}</p>}
      {!expanded && <button className="secondary" disabled={status.upgrade_required} onClick={() => setExpanded(true)}>{zh ? "设置多电脑同步" : "Set up computer sync"}</button>}
      {expanded && !preview && <form onSubmit={event => void prepare(event)}>
        <fieldset className="personal-sync-fields" disabled={busy}>
          <div className="field"><label htmlFor="personal-sync-mode">{zh ? "连接方式" : "Connection mode"}</label><select id="personal-sync-mode" value={setup.mode} onChange={event => setSetup({ ...setup, mode: event.target.value as PersonalSyncSetup["mode"] })}><option value="create">{zh ? "第一台电脑：创建同步空间" : "First computer: create a sync space"}</option><option value="join">{zh ? "其他电脑：加入已有空间" : "Another computer: join an existing space"}</option></select></div>
          <div className="field"><label htmlFor="personal-sync-provider">{zh ? "存储方式" : "Storage type"}</label><select id="personal-sync-provider" value={setup.provider} onChange={event => setSetup({ ...setup, provider: event.target.value as PersonalSyncSetup["provider"], location: "", password: "", username: "" })}><option value="folder">{zh ? "同步文件夹" : "Synchronized folder"}</option><option value="webdav">WebDAV</option></select></div>
          {setup.provider === "folder" ? <PathPicker id="personal-sync-folder" label={zh ? "同步文件夹位置" : "Synchronized folder location"} value={setup.location} onChange={location => setSetup({ ...setup, location })} mode="directory" required hint={zh ? "选择已由 OneDrive、网盘或局域网在两台电脑间同步的文件夹。" : "Choose a folder already shared between your computers through OneDrive, another drive service or your local network."} /> : <>
            <div className="field"><label htmlFor="personal-sync-location">{zh ? "WebDAV 文件夹地址" : "WebDAV folder address"}</label><input id="personal-sync-location" type="url" value={setup.location} onChange={event => setSetup({ ...setup, location: event.target.value })} placeholder="https://dav.example.com/vaults/" required /></div>
            <div className="field"><label htmlFor="personal-sync-username">{zh ? "WebDAV 用户名" : "WebDAV username"}</label><input id="personal-sync-username" autoComplete="off" value={setup.username} onChange={event => setSetup({ ...setup, username: event.target.value })} maxLength={200} /></div>
            <div className="field"><label htmlFor="personal-sync-password">{zh ? "WebDAV 密码" : "WebDAV password"}</label><input id="personal-sync-password" type="password" autoComplete="off" value={setup.password} onChange={event => setSetup({ ...setup, password: event.target.value })} maxLength={512} /></div>
          </>}
          <div className="field"><label htmlFor="personal-sync-device">{zh ? "这台电脑的名称" : "This computer's name"}</label><input id="personal-sync-device" value={setup.label} onChange={event => setSetup({ ...setup, label: event.target.value })} maxLength={100} required /></div>
          {setup.mode === "join" && <div className="field"><label htmlFor="personal-sync-join-code">{zh ? "另一台电脑的连接码" : "Connection code from another computer"}</label><input id="personal-sync-join-code" type="password" autoComplete="off" value={setup.code} onChange={event => setSetup({ ...setup, code: event.target.value })} maxLength={100} required /></div>}
          <label className="checkbox-field"><input type="checkbox" checked={setup.automatic} onChange={event => setSetup({ ...setup, automatic: event.target.checked })} />{zh ? "解锁期间自动同步" : "Sync automatically while unlocked"}</label>
          <div className="button-row"><button className="primary" type="submit" disabled={!setup.location.trim() || !setup.label.trim()}>{busy ? (zh ? "正在读取…" : "Reading…") : (zh ? "预览连接" : "Preview connection")}</button><button className="secondary" type="button" onClick={() => { setExpanded(false); setSetup(blank); }}>{zh ? "取消设置" : "Cancel setup"}</button></div>
        </fieldset>
      </form>}
      {preview && <div className="nested-panel" role="region" aria-label={zh ? "同步连接预览" : "Sync connection preview"}>
        <p>{zh ? `连接后有 ${preview.result_entries} 个条目，本地变化 ${preview.total} 处，待处理冲突 ${preview.conflicts} 处。` : `${preview.result_entries} entries after joining, ${preview.total} local changes and ${preview.conflicts} conflicts to review.`}</p>
        <p className="field-hint">{zh ? "加入后会保留这台电脑已有条目；冲突内容需另行选择。同步期间非冲突修改会自动合并。" : "Joining retains this computer's entries; conflicts need a separate choice. Later sync merges non-conflicting changes automatically."}</p>
        {preview.items.length > 0 && <ul>{preview.items.map(item => <li key={item.id}>{item.title || (zh ? "密码库内容" : "Vault content")} · {({ add: zh ? "新增" : "Add", update: zh ? "更新" : "Update", remove: zh ? "删除" : "Remove" })[item.action]}</li>)}</ul>}
        {preview.total > preview.items.length && <p>{zh ? "仅显示前 100 项。" : "Showing the first 100 changes."}</p>}
        <div className="button-row"><button className="primary" disabled={busy} onClick={() => setConfirmation("connect")}>{zh ? "连接并应用" : "Connect and apply"}</button><button className="secondary" disabled={busy} onClick={cancelPreview}>{zh ? "取消连接" : "Cancel connection"}</button></div>
      </div>}
    </>}
    {status?.connected && <>
      <dl className="status-grid"><div className="status-row"><dt>{zh ? "存储位置" : "Storage location"}</dt><dd>{status.location}</dd></div><div className="status-row"><dt>{zh ? "同步状态" : "Sync state"}</dt><dd>{status.disabled ? (zh ? "已停止，等待清理凭据" : "Stopped; credential cleanup pending") : status.busy || busy ? (zh ? "正在处理" : "Working") : status.error ? (zh ? "连接中断，将保留本地修改并重试" : "Connection interrupted; local changes retained for retry") : (zh ? "已连接" : "Connected")}</dd></div><div className="status-row"><dt>{zh ? "待上传 / 冲突" : "Pending / conflicts"}</dt><dd>{(status.pending || 0) + (status.outbox || 0)} / {status.conflicts || 0}</dd></div><div className="status-row"><dt>{zh ? "最近同步" : "Last sync"}</dt><dd>{status.last_success ? new Date(status.last_success * 1000).toLocaleString(locale) : (zh ? "本次启动尚未同步" : "Not synced in this session")}</dd></div></dl>
      {(status.waiting || status.more) && <p role="status">{zh ? "正在等待更多修改记录，下一轮同步会继续。" : "Waiting for more change records; the next sync will continue."}</p>}
      <div className="button-row"><button className="primary" disabled={busy || status.busy || status.disabled} onClick={() => void action(async () => { await api.runPersonalSync(); if (alive.current) setNotice(zh ? "本轮同步已完成。" : "Sync cycle completed."); changed(); })}>{zh ? "立即同步" : "Sync now"}</button><button className="secondary" disabled={busy} onClick={() => void refresh()}>{zh ? "刷新状态" : "Refresh status"}</button><button className="secondary" disabled={busy} onClick={() => { setCode(""); setConfirmation("disconnect"); }}>{zh ? "断开这台电脑" : "Disconnect this computer"}</button></div>
      {!status.disabled && <>
        <div className="field"><label htmlFor="personal-sync-current-name">{zh ? "这台电脑的名称" : "This computer's name"}</label><input id="personal-sync-current-name" maxLength={100} disabled={busy} value={label} onChange={event => setLabel(event.target.value)} /></div>
        <label className="checkbox-field"><input type="checkbox" disabled={busy} checked={automatic} onChange={event => setAutomatic(event.target.checked)} />{zh ? "解锁期间自动同步" : "Sync automatically while unlocked"}</label>
        <button className="secondary" disabled={busy || !label.trim() || (label === status.label && automatic === status.automatic)} onClick={() => void action(async () => { await api.updatePersonalSync(automatic, label); changed(); })}>{zh ? "保存同步设置" : "Save sync settings"}</button>
        <details className="personal-sync-devices"><summary>{zh ? "连接另一台电脑与设备列表" : "Connect another computer and view devices"}</summary>
          <p className="field-hint">{zh ? "在另一台电脑选择相同的存储位置并粘贴连接码。连接码包含解密密钥，只交给你自己的设备。" : "Choose the same storage location on your other computer and paste the connection code. It contains the decryption key; give it only to your own devices."}</p>
          <div className="button-row"><button className="secondary" disabled={busy} onClick={() => void action(async () => { const result = await api.personalSyncCode(); if (alive.current) setCode(result.code); })}>{zh ? "显示连接码" : "Reveal connection code"}</button><button className="secondary" disabled={busy} onClick={() => void action(async () => { await api.copyPersonalSyncCode(); if (alive.current) setNotice(zh ? "连接码已复制，45 秒后自动清除。" : "Connection code copied; it clears after 45 seconds."); })}>{zh ? "复制连接码" : "Copy connection code"}</button>{code && <button className="secondary" onClick={() => setCode("")}>{zh ? "隐藏连接码" : "Hide connection code"}</button>}</div>
          {code && <div className="field"><label htmlFor="personal-sync-shown-code">{zh ? "同步连接码" : "Sync connection code"}</label><input id="personal-sync-shown-code" readOnly value={code} autoComplete="off" /></div>}
          <ul>{status.devices?.map(device => <li key={device.id}>{device.label}{device.current ? (zh ? "（这台电脑）" : " (this computer)") : ""}</li>)}</ul>
          {Boolean(status.pending_deletions) && <p className="field-hint">{zh ? `${status.pending_deletions} 条删除记录等待其他电脑确认。` : `${status.pending_deletions} deletion records are waiting for other computers to acknowledge them.`}</p>}
        </details>
        {Boolean(status.conflicts) && <button className="secondary" disabled={busy} onClick={() => setShowConflicts(value => !value)}>{showConflicts ? (zh ? "收起冲突处理" : "Close conflict review") : (zh ? "处理多电脑冲突" : "Review computer sync conflicts")}</button>}
        {showConflicts && <Conflicts onDone={changed} />}
      </>}
    </>}
    <ConfirmDialog open={confirmation !== null} idPrefix="personal-sync-confirm" title={confirmation === "disconnect" ? (zh ? "断开多电脑同步" : "Disconnect computer sync") : (zh ? "确认连接同步空间" : "Connect to this sync space")} message={confirmation === "disconnect" ? (zh ? "保留本地数据，停止这台电脑的上传和下载。共享存储中的加密记录会保留。" : "Keep local data and stop this computer's uploads and downloads. Encrypted records in shared storage remain.") : (zh ? "确认后应用预览中的合并，并按你的设置同步后续修改。需要修改本地数据时会先创建加密备份。" : "Apply the previewed merge and sync future changes according to your settings. An encrypted backup is created before changing local data.")} onCancel={() => setConfirmation(null)} onConfirm={() => void confirm()} />
  </section>;
}
