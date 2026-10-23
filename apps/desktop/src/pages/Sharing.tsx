import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Entry, type FamilyPending, type SharedEntry, type SharedFamily, type SharedValues, type SharingAction, type SharingOptions, type SharingPreview, type SharingStatus } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";
import PasswordField from "../components/PasswordField";

const emptyValues: SharedValues = { title: "", username: "", password: "", url: "", notes: "" };
const emptyStatus: SharingStatus = { service: "", identity: "", shares: [], families: [], outbox: [] };

export default function Sharing({ onDirtyChange, onSavingChange, initialEntryId }: { initialEntryId?: string; onDirtyChange: (value: boolean) => void; onSavingChange: (value: boolean) => void }) {
  const { locale } = useI18n(); const zh = locale === "zh"; const { showToast } = useToast();
  const text = (en: string, cn: string) => zh ? cn : en;
  const [status, setStatus] = useState(emptyStatus), [server, setServer] = useState(""), [admin, setAdmin] = useState("");
  const [personal, setPersonal] = useState<Entry[]>([]), [personalId, setPersonalId] = useState(""), [missingInitial, setMissingInitial] = useState(false);
  const [fields, setFields] = useState(["username", "password", "url"]), [hours, setHours] = useState(24), [views, setViews] = useState(1);
  const [name, setName] = useState(""), [invite, setInvite] = useState(""), [role, setRole] = useState<"reader" | "editor">("reader");
  const [family, setFamily] = useState<SharedFamily | null>(null), [members, setMembers] = useState<FamilyPending | null>(null);
  const [draft, setDraft] = useState<{ id: string; values: SharedValues; history: SharedEntry["history"]; replacement?: string; current?: SharedValues | null } | null>(null), [dirty, setDirty] = useState(false);
  const [preview, setPreview] = useState<{ info: SharingPreview; options: SharingOptions } | null>(null);
  const [pendingDiscard, setPendingDiscard] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [revealed, setRevealed] = useState<{ value: string; invitation: boolean } | null>(null);
  const mounted = useRef(true);
  const serverEdited = useRef(false);
  const loadSequence = useRef(0);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; onDirtyChange(false); onSavingChange(false); }; }, [onDirtyChange, onSavingChange]);
  useEffect(() => { onDirtyChange(dirty || Boolean(preview)); }, [dirty, preview, onDirtyChange]);
  useEffect(() => { onSavingChange(busy); }, [busy, onSavingChange]);
  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    const value = await api.sharingStatus();
    if (mounted.current && sequence === loadSequence.current) { setStatus(value); if (!serverEdited.current) setServer(value.service); }
  }, []);
  useEffect(() => {
    void load().catch(() => {});
    void api.listEntries().then(values => {
      if (!mounted.current) return;
      setPersonal(values);
      // Never silently substitute another account for the one the user chose to share.
      const found = Boolean(initialEntryId) && values.some(entry => entry.id === initialEntryId);
      setPersonalId(found ? initialEntryId! : initialEntryId ? "" : values[0]?.id || "");
      setMissingInitial(Boolean(initialEntryId) && !found);
    }).catch(() => {});
  }, [load]);
  useEffect(() => {
    if (!revealed) return;
    const clear = () => setRevealed(null); const timer = window.setTimeout(clear, 45000);
    window.addEventListener("blur", clear); document.addEventListener("visibilitychange", clear);
    return () => { window.clearTimeout(timer); window.removeEventListener("blur", clear); document.removeEventListener("visibilitychange", clear); };
  }, [revealed]);
  function failure(reason: unknown) {
    const message = String(reason);
    setError(zh ? (message.includes("changed") ? "共享内容已改变。请刷新后核对；待发送操作会保留。" : message.includes("read-only") || message.includes("access was removed") ? "此共享库只读或访问权限已被移除。" : message.includes("token") || message.includes("Credential") ? "请检查分享服务的管理令牌和 Windows 凭据存储。" : "未能完成操作。请检查服务连接，或查看下方待发送操作后重试。") : message.replace(/^Error: /, ""));
  }
  async function run(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError("");
    try { await work(); } catch (reason) { if (mounted.current) failure(reason); }
    finally { if (mounted.current) { await load().catch(() => {}); setBusy(false); } }
  }
  function title(action: SharingAction) {
    const labels: Record<SharingAction, [string, string]> = { share: ["Create a limited share", "创建限时分享"], "revoke-share": ["Revoke this share", "撤销分享"], "create-family": ["Create a shared vault", "创建家庭共享库"], "join-family": ["Request to join", "申请加入共享库"], invite: ["Create an invitation", "创建成员邀请"], "approve-member": ["Approve this member", "批准成员加入"], "remove-member": ["Remove member and rotate key", "移除成员并更换共享密钥"], "revoke-invite": ["Revoke invitation", "撤销成员邀请"], "save-entry": ["Save shared account", "保存共享账号"], "trash-entry": ["Move to shared trash", "移入共享回收站"], "restore-entry": ["Restore shared account", "恢复共享账号"], "restore-history": ["Restore shared history", "恢复共享历史版本"] };
    return text(...labels[action]);
  }
  const fieldLabel = (field: string) => ({ title: text("Title", "名称"), username: text("Username", "用户名"), password: text("Password", "密码"), url: text("Website", "网站"), notes: text("Notes", "备注") }[field] || field);
  const roleLabel = (value: string) => value === "owner" ? text("Owner", "所有者") : value === "editor" ? text("Can edit", "可编辑") : text("Read-only", "只读");
  async function review(options: SharingOptions) { await run(async () => { const info = await api.previewSharing(options); if (mounted.current) setPreview({ info, options }); }); }
  async function openFamily(id: string) {
    await run(async () => {
      setDraft(null); setDirty(false); setMembers(null); setFamily(null);
      try { const result = await api.refreshFamily(id); if (result.pending) { setFamily(null); showToast(text("Waiting for the owner to approve your identity.", "等待所有者确认你的身份后批准加入。"), "info"); return; } }
      catch (reason) { failure(reason); }
      const result = await api.sharedFamily(id); if (mounted.current) setFamily(result);
    });
  }
  async function confirm() {
    const selected = preview; if (!selected) return; setPreview(null);
    await run(async () => {
      const result = await api.applySharing(selected.options, selected.info.preview_token);
      if (!mounted.current) return;
      if (result.invitation) setRevealed({ value: result.invitation, invitation: true });
      setInvite(""); setName("");
      if (["save-entry", "trash-entry", "restore-entry", "restore-history"].includes(result.action)) { setDraft(null); setDirty(false); }
      if (family) { setFamily(await api.sharedFamily(family.id)); setMembers(null); }
      showToast(text("Sharing operation completed", "分享操作已完成"), "success");
    });
  }
  function cancelReview() { const value = preview; setPreview(null); if (value) void api.cancelSharing(value.info.preview_token).catch(() => {}); }
  return <div className="card sharing-page">
    <h2>{text("Sharing", "分享")}</h2>
    <p className="field-hint">{text("Use your own optional sharing service for limited links and a separate family vault.", "通过自选分享服务创建限时链接，或使用独立的家庭共享库。")}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <details className="settings-section" open={!status.service}>
      <summary>{text("Sharing service connection", "分享服务连接")}</summary>
      <form onSubmit={event => { event.preventDefault(); const token = admin; setAdmin(""); void run(async () => { await api.configureSharing(server, token); showToast(text("Connection saved", "连接已保存"), "success"); }); }}>
        <label>{text("Sharing service address", "分享服务地址")}<input value={server} onChange={event => { serverEdited.current = true; setServer(event.target.value); }} placeholder="https://share.example.com" required maxLength={2000} /></label>
        <PasswordField id="sharing-admin" label={text("Service administration token", "服务管理令牌")} value={admin} onChange={setAdmin} hint={text("Required to create links or vaults. Saved in Windows Credential Manager. Leave empty to keep the saved token.", "创建分享或共享库时需要，保存到 Windows 凭据管理器。留空会保留已保存的令牌。")}/>
        <button className="primary" disabled={busy} type="submit">{text("Save service connection", "保存服务连接")}</button>
      </form>
    </details>
    <section className="settings-section" aria-labelledby="limited-share-heading">
      <h3 id="limited-share-heading">{text("Limited links", "限时链接")}</h3>
      <form onSubmit={event => { event.preventDefault(); void review({ action: "share", entry_id: personalId, fields, hours, max_reads: views }); }}>
        <fieldset disabled={busy || dirty}><legend>{text("Share a saved personal account", "分享已保存的个人账号")}</legend>
          {missingInitial && <p className="context-notice context-notice-warning" role="status">{text("The selected account is not available for sharing. Only accounts in the vault (not archived or in trash) can be shared. Choose an account below.", "所选账号当前不可分享。只有保险库中的账号（不含归档和回收站）可以分享，请在下方选择账号。")}</p>}
          <label>{text("Personal account", "个人账号")}<select value={personalId} onChange={event => { setPersonalId(event.target.value); setMissingInitial(false); }} required><option value="">{text("Choose an account", "选择账号")}</option>{personal.map(entry => <option key={entry.id} value={entry.id}>{entry.title}</option>)}</select></label>
          <div className="button-row">{["username", "password", "url", "notes"].map(field => <label key={field} className="checkbox-label"><input type="checkbox" checked={fields.includes(field)} onChange={event => setFields(current => event.target.checked ? [...current, field] : current.filter(item => item !== field))} />{fieldLabel(field)}</label>)}</div>
          <div className="sharing-grid"><label>{text("Expires after (hours)", "有效时长（小时）")}<input type="number" min={1} max={720} value={hours} onChange={event => setHours(Number(event.target.value))} required /></label><label>{text("Maximum views", "最多查看次数")}<input type="number" min={1} max={100} value={views} onChange={event => setViews(Number(event.target.value))} required /></label></div>
          <button className="primary" type="submit" disabled={!status.service || !personalId || !fields.length}>{text("Preview share", "预览分享")}</button>
        </fieldset>
      </form>
      {status.shares.map(item => <article className="nested-panel" key={item.id} aria-label={item.title}>
        <strong>{item.title}</strong><p>{new Date(item.expires * 1000).toLocaleString(locale)} · {item.max_reads} {text("maximum views", "次查看上限")} · {item.phase === "ready" ? text("Created", "已创建") : item.phase === "revoked" ? text("Revoked", "已撤销") : text("Pending", "待完成")}</p>
        <div className="button-row"><button className="primary" type="button" disabled={busy || item.phase !== "ready"} onClick={() => void run(async () => { await api.copySharingLink(item.id); showToast(text("Link copied", "链接已复制"), "success"); })}>{text("Copy link", "复制链接")}</button>
          <button type="button" className="secondary" disabled={busy || item.phase !== "ready"} onClick={() => void run(async () => { const value = await api.sharingLink(item.id); setRevealed({ value: value.link, invitation: false }); })}>{text("Show link", "显示链接")}</button>
          <button type="button" className="danger" disabled={busy || dirty || item.phase === "revoked"} onClick={() => void review({ action: "revoke-share", entry_id: item.id })}>{text("Revoke", "撤销")}</button></div>
      </article>)}
    </section>
    {revealed && <section className="nested-panel" aria-label={text("Created sharing code", "已创建的分享代码")}>
      <label htmlFor="sharing-revealed">{revealed.invitation ? text("Invitation code", "邀请码") : text("Share link", "分享链接")}</label><textarea id="sharing-revealed" readOnly value={revealed.value} autoComplete="off" rows={3} />
      {revealed.invitation && <button className="primary" type="button" disabled={busy} onClick={() => void run(async () => { await api.copyFamilyInvitation(revealed.value); showToast(text("Invitation copied", "邀请码已复制"), "success"); })}>{text("Copy invitation", "复制邀请码")}</button>}
      <button type="button" className="secondary" onClick={() => setRevealed(null)}>{text("Hide code", "隐藏代码")}</button>
    </section>}
    <section className="settings-section" aria-labelledby="family-vaults-heading">
      <h3 id="family-vaults-heading">{text("Family vaults", "家庭共享库")}</h3>
      <p className="field-hint">{text("Personal accounts stay separate. Invitees join only after the owner approves their identity code.", "个人账号保持独立。受邀者提交申请后，需要所有者核对身份码并批准加入。")}</p>
      {status.identity && <details><summary>{text("My identity code", "我的身份码")}</summary><code className="sharing-code">{status.identity}</code></details>}
      <div className="sharing-grid">
        <form onSubmit={event => { event.preventDefault(); void review({ action: "create-family", name }); }}><label>{text("New shared vault name", "新共享库名称")}<input value={name} onChange={event => setName(event.target.value)} maxLength={100} required /></label><button className="primary" disabled={busy || dirty || !status.service} type="submit">{text("Preview new vault", "预览新共享库")}</button></form>
        <form onSubmit={event => { event.preventDefault(); void review({ action: "join-family", invite }); }}><label>{text("Received invitation code", "收到的邀请码")}<input type="password" autoComplete="off" value={invite} onChange={event => setInvite(event.target.value)} maxLength={6000} required /></label><button className="primary" disabled={busy || dirty} type="submit">{text("Preview joining", "预览加入")}</button></form>
      </div>
      <div className="button-row">{status.families.map(item => <button type="button" className="secondary" disabled={busy || dirty} key={item.id} onClick={() => void openFamily(item.id)}>{item.name || text("Awaiting approval", "等待批准")}{item.removed ? text(" (access removed)", "（已移除）") : ""}</button>)}</div>
      {family && <section className="nested-panel" aria-label={family.name}>
        <h4>{family.name} · {roleLabel(family.role)}</h4>
        <div className="button-row"><button type="button" className="secondary" disabled={busy || dirty} onClick={() => void openFamily(family.id)}>{text("Refresh shared vault", "刷新共享库")}</button>
          {family.role !== "reader" && <button className="primary" type="button" disabled={busy || dirty} onClick={() => { setDraft({ id: "", values: { ...emptyValues }, history: [] }); setDirty(false); }}>{text("Add shared account", "添加共享账号")}</button>}
          {family.role === "owner" && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void run(async () => setMembers(await api.familyPending(family.id)))}>{text("Manage members", "管理成员")}</button>}</div>
        {family.entries.map(entry => <article key={entry.id} className="sharing-entry" aria-label={entry.title}><span><strong>{entry.title}</strong> · {entry.username}{entry.trashed_at ? text(" · Trash (30 days)", " · 回收站（30 天）") : ""}</span>
          <div className="button-row"><button type="button" className="secondary" disabled={busy || dirty} onClick={() => void run(async () => { const value = await api.sharedEntry(family.id, entry.id); setDraft({ id: entry.id, values: { title: value.title, username: value.username, password: value.password, url: value.url, notes: value.notes }, history: value.history }); setDirty(false); })}>{text("Open shared account", "打开共享账号")}</button>
          {!entry.trashed_at && <button type="button" className="secondary" disabled={busy} onClick={() => void run(async () => { await api.copySharedEntry(family.id, entry.id, "password"); showToast(text("Password copied", "密码已复制"), "success"); })}>{text("Copy shared password", "复制共享密码")}</button>}
          {family.role !== "reader" && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void review({ action: entry.trashed_at ? "restore-entry" : "trash-entry", family_id: family.id, entry_id: entry.id })}>{entry.trashed_at ? text("Restore", "恢复") : text("Move to trash", "移入回收站")}</button>}</div>
        </article>)}
        {draft && <form className="nested-panel" aria-label={text("Shared account editor", "共享账号编辑器")} onSubmit={event => { event.preventDefault(); void review({ action: "save-entry", family_id: family.id, entry_id: draft.id, values: draft.values, replace_pending_id: draft.replacement }); }}>
          <h4>{text("Shared account", "共享账号")}</h4>
          {(["title", "username", "url", "notes"] as const).map(field => <label key={field}>{fieldLabel(field)}<input value={draft.values[field]} readOnly={family.role === "reader"} required={field === "title"} maxLength={field === "title" ? 1000 : 100000} onChange={event => { setDraft({ ...draft, values: { ...draft.values, [field]: event.target.value } }); setDirty(true); }} /></label>)}
          <PasswordField id="family-password" label={fieldLabel("password")} value={draft.values.password} readOnly={family.role === "reader"} onChange={value => { setDraft({ ...draft, values: { ...draft.values, password: value } }); setDirty(true); }} />
          {draft.replacement && <details className="nested-panel"><summary>{text("Compare with the latest shared account", "与最新共享账号比较")}</summary><p>{text("Your pending draft is loaded above. Choose newer values below where needed, then preview saving again.", "上方已载入待发送草稿。按需采用下方的最新字段，再预览保存。")}</p>
            {draft.current ? (Object.keys(emptyValues) as Array<keyof SharedValues>).map(field => <div key={field}><PasswordField id={`shared-current-${field}`} label={`${text("Current", "当前")} ${fieldLabel(field)}`} readOnly value={draft.current![field]} onChange={() => {}} /><button type="button" className="secondary" onClick={() => { setDraft({ ...draft, values: { ...draft.values, [field]: draft.current![field] } }); setDirty(true); }}>{text("Use current", "采用当前字段")} {fieldLabel(field)}</button></div>) : <p>{text("This account is not in the latest shared vault; saving will add it.", "最新共享库中没有此账号，保存将新增账号。")}</p>}
          </details>}
          <div className="button-row">{family.role !== "reader" && <button className="primary" type="submit" disabled={busy}>{text("Preview account save", "预览保存账号")}</button>}<button type="button" className="secondary" disabled={busy} onClick={() => { setDraft(null); setDirty(false); }}>{text("Close without saving", "关闭且不保存")}</button></div>
          {!!draft.history.length && <details><summary>{text("Shared account history", "共享账号历史")}</summary>{draft.history.map((old, index) => <p key={index}>{new Date(old.updated_at * 1000).toLocaleString(locale)} · {old.title} {family.role !== "reader" && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void review({ action: "restore-history", family_id: family.id, entry_id: draft.id, history_index: index })}>{text("Review restoration", "预览恢复")}</button>}</p>)}</details>}
        </form>}
        {members && family.role === "owner" && <section className="nested-panel" aria-label={text("Family members", "家庭成员")}>
          <label>{text("New member permission", "新成员权限")}<select value={role} onChange={event => setRole(event.target.value as "reader" | "editor")}><option value="reader">{roleLabel("reader")}</option><option value="editor">{roleLabel("editor")}</option></select></label>
          <button className="primary" type="button" disabled={busy || dirty} onClick={() => void review({ action: "invite", family_id: family.id, role })}>{text("Preview invitation", "预览邀请")}</button>
          {members.requests.map(member => <article className="sharing-entry" key={member.id}><p>{text("Compare this code with the invitee before approving:", "批准前请与受邀者核对身份码：")}<code className="sharing-code">{member.identity}</code>{roleLabel(member.role)}</p><button className="primary" type="button" disabled={busy || dirty} onClick={() => void review({ action: "approve-member", family_id: family.id, pending_id: member.id, member_id: member.identity, role: member.role })}>{text("Review member approval", "预览成员批准")}</button></article>)}
          {family.members.map(member => <article className="sharing-entry" key={member.id}><code className="sharing-code">{member.id}</code><span>{roleLabel(member.role)}</span>{member.role !== "owner" && <button type="button" className="danger" disabled={busy || dirty} onClick={() => void review({ action: "remove-member", family_id: family.id, member_id: member.id })}>{text("Review member removal", "预览移除成员")}</button>}</article>)}
          {members.invitations.map(item => <p key={item.id}>{roleLabel(item.role)} · {new Date(item.expires * 1000).toLocaleString(locale)} <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void review({ action: "revoke-invite", family_id: family.id, pending_id: item.id })}>{text("Revoke invitation", "撤销邀请")}</button></p>)}
        </section>}
      </section>}
    </section>
    {!!status.outbox.length && <section className="settings-section" aria-labelledby="sharing-outbox"><h3 id="sharing-outbox">{text("Pending operations", "待发送操作")}</h3><p>{text("These operations are saved encrypted. Retry after reconnecting; a conflict preserves your proposed change.", "这些操作已加密保存。连接恢复后可重试；发生冲突时，待发送修改会保留。")}</p>
      {status.outbox.map(item => <article key={item.id} className="sharing-entry"><span>{title(item.action)} · {item.title}</span><div className="button-row"><button className="primary" type="button" disabled={busy || dirty} onClick={() => void run(async () => { const result = await api.pendingSharing(item.id, "retry"); if (result.invitation) setRevealed({ value: result.invitation, invitation: true }); if (family) setFamily(await api.sharedFamily(family.id)); })}>{text("Retry operation", "重试操作")}</button>
        {["save-entry", "restore-history"].includes(item.action) && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void run(async () => { const result = await api.reviewPendingSharing(item.id); setFamily(await api.sharedFamily(item.family)); setMembers(null); setDraft({ id: result.options.entry_id || "", values: result.options.values!, history: [], replacement: item.id, current: result.current }); setDirty(true); })}>{text("Review pending draft", "核对待发送草稿")}</button>}
        {!item.action.includes("share") && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => setPendingDiscard(item.id)}>{text("Discard pending change", "放弃待发送修改")}</button>}</div></article>)}
    </section>}
    <ConfirmDialog open={Boolean(preview)} idPrefix="sharing-review" title={preview ? title(preview.options.action) : ""}
      message={preview?.options.action === "remove-member" ? text("Remaining members receive a new key. Earlier copies cannot be recalled.", "剩余成员将获得新密钥，已被对方保存的旧内容不会被删除。") : text("Review the details before confirming.", "请核对以下内容后确认。")}
      details={preview ? [
        { label: text("Item", "条目"), value: preview.info.title },
        { label: text("Service", "服务"), value: preview.info.server },
        { label: text("Included fields", "包含字段"), value: preview.info.details.map(field => fieldLabel(field)).join(locale === "zh" ? "、" : ", ") },
        ...(preview.options.action === "share" ? [{ label: text("Expires in", "有效期"), value: `${hours} ${text("hours", "小时")}` }, { label: text("View limit", "查看次数"), value: String(views) }] : []),
      ] : []}
      onConfirm={() => void confirm()} onCancel={cancelReview} />
    <ConfirmDialog open={Boolean(pendingDiscard)} idPrefix="sharing-discard" title={text("Discard pending change", "放弃待发送修改")} message={text("Refresh remote content and discard this saved proposal. An already completed server operation stays completed.", "刷新远端内容并放弃这份待发送修改。服务器上已完成的操作会保留。")} onCancel={() => setPendingDiscard(null)} onConfirm={() => { const id = pendingDiscard; setPendingDiscard(null); if (id) void run(async () => { await api.pendingSharing(id, "discard"); }); }} />
  </div>;
}
