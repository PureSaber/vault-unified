import TaskNavigation from "../components/TaskNavigation";
import DiscardChanges from "../components/DiscardChanges";
import SettingsCard from "../components/SettingsCard";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Entry, type FamilyPending, type SharedEntry, type SharedFamily, type SharedValues, type SharingAction, type SharingOptions, type SharingPreview, type SharingStatus } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";
import PasswordField from "../components/PasswordField";

const emptyValues: SharedValues = { title: "", username: "", password: "", url: "", notes: "" };
const emptyStatus: SharingStatus = { service: "", identity: "", shares: [], families: [], outbox: [] };

export default function Sharing({ onDirtyChange, onSavingChange, initialEntryId }: { initialEntryId?: string; onDirtyChange: (value: boolean) => void; onSavingChange: (value: boolean) => void }) {
  const { locale, t } = useI18n(); const { showToast: publishToast } = useToast();
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
  const [task, setTask] = useState("links");
  const [pendingTask, setPendingTask] = useState<string | null>(null);
  const connectionDirty = server !== status.service || Boolean(admin);
  const unsaved = dirty || Boolean(preview) || connectionDirty || Boolean(name || invite);
  const content = useRef<HTMLDivElement>(null);
  const navigate = (next: string) => {
    if (next === task || busy) return;
    if (unsaved) { setPendingTask(next); return; }
    setRevealed(null); setDraft(null); setTask(next);
  };
  useEffect(() => { content.current?.focus(); }, [task]);
  const mounted = useRef(true);
  const showToast = (message: string, type?: "success" | "error" | "info") => { if (mounted.current) publishToast(message, type); };
  const [connectionSaveError, setConnectionSaveError] = useState(false);
  const activePreview = useRef<string | null>(null);
  useEffect(() => () => { if (activePreview.current) void api.cancelSharing(activePreview.current).catch(() => {}); }, []);
  const serverEdited = useRef(false);
  const loadSequence = useRef(0);
  useEffect(() => {
    mounted.current = true;
    const locked = () => { mounted.current = false; };
    window.addEventListener("vault-ui-locked", locked);
    return () => { mounted.current = false; window.removeEventListener("vault-ui-locked", locked); onDirtyChange(false); onSavingChange(false); };
  }, [onDirtyChange, onSavingChange]);
  useEffect(() => { onDirtyChange(unsaved); }, [unsaved, onDirtyChange]);
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
    setError(t(message.includes("changed") ? "Sharing.errorChanged" : message.includes("read-only") || message.includes("access was removed") ? "Sharing.errorAccess" : message.includes("token") || message.includes("Credential") ? "Sharing.errorToken" : "Sharing.errorGeneric"));
  }
  async function run(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError("");
    try { await work(); } catch (reason) { if (mounted.current) failure(reason); }
    finally { if (mounted.current) { await load().catch(() => {}); setBusy(false); } }
  }
  function title(action: SharingAction) {
    return t(`Sharing.action.${action}`);
  }
  const fieldLabel = (field: string) => ({ title: t("Sharing.title"), username: t("Sharing.username"), password: t("Sharing.password"), url: t("Sharing.website"), notes: t("Sharing.notes") }[field] || field);
  const roleLabel = (value: string) => value === "owner" ? t("Sharing.owner") : value === "editor" ? t("Sharing.canEdit") : t("Sharing.readOnly");
  async function review(options: SharingOptions) { await run(async () => { const info = await api.previewSharing(options); if (mounted.current) { activePreview.current = info.preview_token; setPreview({ info, options }); } else { void api.cancelSharing(info.preview_token).catch(() => {}); } }); }
  async function openFamily(id: string) {
    await run(async () => {
      setDraft(null); setDirty(false); setMembers(null); setFamily(null);
      try { const result = await api.refreshFamily(id); if (!mounted.current) return; if (result.pending) { setFamily(null); showToast(t("Sharing.waitingForTheOwnerToApproveYour"), "info"); return; } }
      catch (reason) { if (!mounted.current) return; failure(reason); }
      const result = await api.sharedFamily(id); if (mounted.current) setFamily(result);
    });
  }
  async function confirm() {
    const selected = preview; if (!selected) return; activePreview.current = null; setPreview(null);
    await run(async () => {
      const result = await api.applySharing(selected.options, selected.info.preview_token);
      if (!mounted.current) return;
      if (result.invitation) setRevealed({ value: result.invitation, invitation: true });
      setInvite(""); setName("");
      if (["save-entry", "trash-entry", "restore-entry", "restore-history"].includes(result.action)) { setDraft(null); setDirty(false); }
      if (family) { setFamily(await api.sharedFamily(family.id)); setMembers(null); }
      showToast(t("Sharing.sharingOperationCompleted"), "success");
    });
  }
  function cancelReview() { activePreview.current = null; const value = preview; setPreview(null); if (value) void api.cancelSharing(value.info.preview_token).catch(() => {}); }
  return <div className="card sharing-page">
    <h2>{t("Sharing.sharing")}</h2>
    <p className="field-hint">{t("Sharing.useYourOwnOptionalSharingServiceFor")}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <TaskNavigation label={t("Sharing.sharingSections")} current={task} busy={busy} onChange={navigate} items={[
      { id: "links", label: t("Sharing.limitedShares") },
      { id: "family", label: t("Sharing.familyVaults") },
      { id: "connection", label: t("Sharing.connection") },
      { id: "pending", label: t("Sharing.pendingChanges") },
    ]} />
    {!status.service && task !== "connection" && <div className="context-notice"><span>{t("Sharing.connectASharingServiceToCreateLinks")}</span><button type="button" className="secondary" disabled={busy} onClick={() => navigate("connection")}>{t("Sharing.setUpConnection")}</button></div>}
    <div ref={content} className="task-content" tabIndex={-1}>
    {task === "connection" && <SettingsCard id="sharing-connection-heading" title={t("Sharing.sharingServiceConnection")} mode="submit" state={busy ? "saving" : connectionSaveError ? "error" : connectionDirty ? "unsaved" : status.service ? "saved" : undefined}>
      <form onSubmit={event => { event.preventDefault(); const token = admin; setAdmin(""); setConnectionSaveError(false); void run(async () => { try { await api.configureSharing(server, token); } catch (reason) { if (mounted.current) setConnectionSaveError(true); throw reason; } if (!mounted.current) return; serverEdited.current = false; setStatus(current => ({ ...current, service: server })); showToast(t("Sharing.connectionSaved"), "success"); }); }}>
        <fieldset className="settings-fields" disabled={busy}><label>{t("Sharing.sharingServiceAddress")}<input value={server} onChange={event => { serverEdited.current = true; setServer(event.target.value); }} placeholder="https://share.example.com" required maxLength={2000} /></label>
        <PasswordField id="sharing-admin" label={t("Sharing.serviceAdministrationToken")} value={admin} onChange={setAdmin} hint={t("Sharing.requiredToCreateLinksOrVaultsSaved")}/>
        <button className="primary" disabled={busy} type="submit">{t("Sharing.saveServiceConnection")}</button>
        </fieldset>
      </form>
    </SettingsCard>}
    {task === "links" && <section className="settings-section" aria-labelledby="limited-share-heading">
      <h3 id="limited-share-heading">{t("Sharing.limitedLinks")}</h3>
      <form onSubmit={event => { event.preventDefault(); void review({ action: "share", entry_id: personalId, fields, hours, max_reads: views }); }}>
        <fieldset disabled={busy || dirty}><legend>{t("Sharing.shareASavedPersonalAccount")}</legend>
          {missingInitial && <p className="context-notice context-notice-warning" role="status">{t("Sharing.theSelectedAccountIsNotAvailableFor")}</p>}
          <label>{t("Sharing.personalAccount")}<select value={personalId} onChange={event => { setPersonalId(event.target.value); setMissingInitial(false); }} required><option value="">{t("Sharing.chooseAnAccount")}</option>{personal.map(entry => <option key={entry.id} value={entry.id}>{entry.title}</option>)}</select></label>
          <div className="button-row">{["username", "password", "url", "notes"].map(field => <label key={field} className="checkbox-label"><input type="checkbox" checked={fields.includes(field)} onChange={event => setFields(current => event.target.checked ? [...current, field] : current.filter(item => item !== field))} />{fieldLabel(field)}</label>)}</div>
          <div className="sharing-grid"><label>{t("Sharing.expiresAfterHours")}<input type="number" min={1} max={720} value={hours} onChange={event => setHours(Number(event.target.value))} required /></label><label>{t("Sharing.maximumViews")}<input type="number" min={1} max={100} value={views} onChange={event => setViews(Number(event.target.value))} required /></label></div>
          <button className="primary" type="submit" disabled={!status.service || !personalId || !fields.length}>{t("Sharing.previewShare")}</button>
        </fieldset>
      </form>
      {status.shares.map(item => <article className="nested-panel" key={item.id} aria-label={item.title}>
        <strong>{item.title}</strong><p>{new Date(item.expires * 1000).toLocaleString(locale)} · {item.max_reads} {t("Sharing.maximumViews2")} · {item.phase === "ready" ? t("Sharing.created") : item.phase === "revoked" ? t("Sharing.revoked") : t("Sharing.pending")}</p>
        <div className="button-row"><button className="primary" type="button" disabled={busy || item.phase !== "ready"} onClick={() => void run(async () => { await api.copySharingLink(item.id); })}>{t("Sharing.copyLink")}</button>
          <button type="button" className="secondary" disabled={busy || item.phase !== "ready"} onClick={() => void run(async () => { const value = await api.sharingLink(item.id); setRevealed({ value: value.link, invitation: false }); })}>{t("Sharing.showLink")}</button>
          <button type="button" className="danger" disabled={busy || dirty || item.phase === "revoked"} onClick={() => void review({ action: "revoke-share", entry_id: item.id })}>{t("Sharing.revoke")}</button></div>
      </article>)}
    </section>}
    {revealed && <section className="nested-panel" aria-label={t("Sharing.createdSharingCode")}>
      <label htmlFor="sharing-revealed">{revealed.invitation ? t("Sharing.invitationCode") : t("Sharing.shareLink")}</label><textarea id="sharing-revealed" readOnly value={revealed.value} autoComplete="off" rows={3} />
      {revealed.invitation && <button className="primary" type="button" disabled={busy} onClick={() => void run(async () => { await api.copyFamilyInvitation(revealed.value); })}>{t("Sharing.copyInvitation")}</button>}
      <button type="button" className="secondary" onClick={() => setRevealed(null)}>{t("Sharing.hideCode")}</button>
    </section>}
    {task === "family" && <section className="settings-section" aria-labelledby="family-vaults-heading">
      <h3 id="family-vaults-heading">{t("Sharing.familyVaults")}</h3>
      <p className="field-hint">{t("Sharing.personalAccountsStaySeparateInviteesJoinOnly")}</p>
      {status.identity && <details><summary>{t("Sharing.myIdentityCode")}</summary><code className="sharing-code">{status.identity}</code></details>}
      <div className="sharing-grid">
        <form onSubmit={event => { event.preventDefault(); void review({ action: "create-family", name }); }}><label>{t("Sharing.newSharedVaultName")}<input value={name} onChange={event => setName(event.target.value)} maxLength={100} required /></label><button className="primary" disabled={busy || dirty || !status.service} type="submit">{t("Sharing.previewNewVault")}</button></form>
        <form onSubmit={event => { event.preventDefault(); void review({ action: "join-family", invite }); }}><label>{t("Sharing.receivedInvitationCode")}<input type="password" autoComplete="off" value={invite} onChange={event => setInvite(event.target.value)} maxLength={6000} required /></label><button className="primary" disabled={busy || dirty} type="submit">{t("Sharing.previewJoining")}</button></form>
      </div>
      <div className="button-row">{status.families.map(item => <button type="button" className="secondary" disabled={busy || dirty} key={item.id} onClick={() => void openFamily(item.id)}>{item.name || t("Sharing.awaitingApproval")}{item.removed ? t("Sharing.accessRemoved") : ""}</button>)}</div>
      {family && <section className="nested-panel" aria-label={family.name}>
        <h4>{family.name} · {roleLabel(family.role)}</h4>
        <div className="button-row"><button type="button" className="secondary" disabled={busy || dirty} onClick={() => void openFamily(family.id)}>{t("Sharing.refreshSharedVault")}</button>
          {family.role !== "reader" && <button className="primary" type="button" disabled={busy || dirty} onClick={() => { setDraft({ id: "", values: { ...emptyValues }, history: [] }); setDirty(false); }}>{t("Sharing.addSharedAccount")}</button>}
          {family.role === "owner" && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void run(async () => setMembers(await api.familyPending(family.id)))}>{t("Sharing.manageMembers")}</button>}</div>
        {family.entries.map(entry => <article key={entry.id} className="sharing-entry" aria-label={entry.title}><span><strong>{entry.title}</strong> · {entry.username}{entry.trashed_at ? t("Sharing.trash30Days") : ""}</span>
          <div className="button-row"><button type="button" className="secondary" disabled={busy || dirty} onClick={() => void run(async () => { const value = await api.sharedEntry(family.id, entry.id); setDraft({ id: entry.id, values: { title: value.title, username: value.username, password: value.password, url: value.url, notes: value.notes }, history: value.history }); setDirty(false); })}>{t("Sharing.openSharedAccount")}</button>
          {!entry.trashed_at && <button type="button" className="secondary" disabled={busy} onClick={() => void run(async () => { await api.copySharedEntry(family.id, entry.id, "password"); })}>{t("Sharing.copySharedPassword")}</button>}
          {family.role !== "reader" && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void review({ action: entry.trashed_at ? "restore-entry" : "trash-entry", family_id: family.id, entry_id: entry.id })}>{entry.trashed_at ? t("Sharing.restore") : t("Sharing.moveToTrash")}</button>}</div>
        </article>)}
        {draft && <form className="nested-panel" aria-label={t("Sharing.sharedAccountEditor")} onSubmit={event => { event.preventDefault(); void review({ action: "save-entry", family_id: family.id, entry_id: draft.id, values: draft.values, replace_pending_id: draft.replacement }); }}>
          <h4>{t("Sharing.sharedAccount")}</h4>
          {(["title", "username", "url", "notes"] as const).map(field => <label key={field}>{fieldLabel(field)}<input value={draft.values[field]} readOnly={family.role === "reader"} required={field === "title"} maxLength={field === "title" ? 1000 : 100000} onChange={event => { setDraft({ ...draft, values: { ...draft.values, [field]: event.target.value } }); setDirty(true); }} /></label>)}
          <PasswordField id="family-password" label={fieldLabel("password")} value={draft.values.password} readOnly={family.role === "reader"} onChange={value => { setDraft({ ...draft, values: { ...draft.values, password: value } }); setDirty(true); }} />
          {draft.replacement && <details className="nested-panel"><summary>{t("Sharing.compareWithTheLatestSharedAccount")}</summary><p>{t("Sharing.yourPendingDraftIsLoadedAboveChoose")}</p>
            {draft.current ? (Object.keys(emptyValues) as Array<keyof SharedValues>).map(field => <div key={field}><PasswordField id={`shared-current-${field}`} label={`${t("Sharing.current")} ${fieldLabel(field)}`} readOnly value={draft.current![field]} onChange={() => {}} /><button type="button" className="secondary" onClick={() => { setDraft({ ...draft, values: { ...draft.values, [field]: draft.current![field] } }); setDirty(true); }}>{t("Sharing.useCurrent")} {fieldLabel(field)}</button></div>) : <p>{t("Sharing.thisAccountIsNotInTheLatest")}</p>}
          </details>}
          <div className="button-row">{family.role !== "reader" && <button className="primary" type="submit" disabled={busy}>{t("Sharing.previewAccountSave")}</button>}<button type="button" className="secondary" disabled={busy} onClick={() => { setDraft(null); setDirty(false); }}>{t("Sharing.closeWithoutSaving")}</button></div>
          {!!draft.history.length && <details><summary>{t("Sharing.sharedAccountHistory")}</summary>{draft.history.map((old, index) => <p key={index}>{new Date(old.updated_at * 1000).toLocaleString(locale)} · {old.title} {family.role !== "reader" && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void review({ action: "restore-history", family_id: family.id, entry_id: draft.id, history_index: index })}>{t("Sharing.reviewRestoration")}</button>}</p>)}</details>}
        </form>}
        {members && family.role === "owner" && <section className="nested-panel" aria-label={t("Sharing.familyMembers")}>
          <label>{t("Sharing.newMemberPermission")}<select value={role} onChange={event => setRole(event.target.value as "reader" | "editor")}><option value="reader">{roleLabel("reader")}</option><option value="editor">{roleLabel("editor")}</option></select></label>
          <button className="primary" type="button" disabled={busy || dirty} onClick={() => void review({ action: "invite", family_id: family.id, role })}>{t("Sharing.previewInvitation")}</button>
          {members.requests.map(member => <article className="sharing-entry" key={member.id}><p>{t("Sharing.compareThisCodeWithTheInviteeBefore")}<code className="sharing-code">{member.identity}</code>{roleLabel(member.role)}</p><button className="primary" type="button" disabled={busy || dirty} onClick={() => void review({ action: "approve-member", family_id: family.id, pending_id: member.id, member_id: member.identity, role: member.role })}>{t("Sharing.reviewMemberApproval")}</button></article>)}
          {family.members.map(member => <article className="sharing-entry" key={member.id}><code className="sharing-code">{member.id}</code><span>{roleLabel(member.role)}</span>{member.role !== "owner" && <button type="button" className="danger" disabled={busy || dirty} onClick={() => void review({ action: "remove-member", family_id: family.id, member_id: member.id })}>{t("Sharing.reviewMemberRemoval")}</button>}</article>)}
          {members.invitations.map(item => <p key={item.id}>{roleLabel(item.role)} · {new Date(item.expires * 1000).toLocaleString(locale)} <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void review({ action: "revoke-invite", family_id: family.id, pending_id: item.id })}>{t("Sharing.revokeInvitation")}</button></p>)}
        </section>}
      </section>}
    </section>}
    {task === "pending" && <section className="settings-section" aria-labelledby="sharing-outbox"><h3 id="sharing-outbox">{t("Sharing.pendingOperations")}</h3><p>{t("Sharing.theseOperationsAreSavedEncryptedRetryAfter")}</p>
      {!status.outbox.length && <p role="status">{t("Sharing.noPendingChanges")}</p>}
      {status.outbox.map(item => <article key={item.id} className="sharing-entry"><span>{title(item.action)} · {item.title}</span><div className="button-row"><button className="primary" type="button" disabled={busy || dirty} onClick={() => void run(async () => { const result = await api.pendingSharing(item.id, "retry"); if (result.invitation) setRevealed({ value: result.invitation, invitation: true }); if (family) setFamily(await api.sharedFamily(family.id)); })}>{t("Sharing.retryOperation")}</button>
        {["save-entry", "restore-history"].includes(item.action) && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void run(async () => { const result = await api.reviewPendingSharing(item.id); setFamily(await api.sharedFamily(item.family)); setMembers(null); setDraft({ id: result.options.entry_id || "", values: result.options.values!, history: [], replacement: item.id, current: result.current }); setDirty(true); setTask("family"); })}>{t("Sharing.reviewPendingDraft")}</button>}
        {!item.action.includes("share") && <button type="button" className="secondary" disabled={busy || dirty} onClick={() => setPendingDiscard(item.id)}>{t("Sharing.discardPendingChange")}</button>}</div></article>)}
    </section>}
    </div>
    <DiscardChanges open={pendingTask !== null} onCancel={() => setPendingTask(null)} onConfirm={() => {
      if (!pendingTask) return;
      cancelReview(); setDirty(false); setDraft(null); setRevealed(null); setAdmin(""); setName(""); setInvite("");
      setServer(status.service); serverEdited.current = false; setConnectionSaveError(false);
      setTask(pendingTask); setPendingTask(null);
    }} />
    <ConfirmDialog open={Boolean(preview)} idPrefix="sharing-review" title={preview ? title(preview.options.action) : ""}
      message={preview?.options.action === "remove-member" ? t("Sharing.remainingMembersReceiveANewKeyEarlier") : t("Sharing.reviewTheDetailsBeforeConfirming")}
      details={preview ? [
        { label: t("Sharing.item"), value: preview.info.title },
        { label: t("Sharing.service"), value: preview.info.server },
        { label: t("Sharing.includedFields"), value: preview.info.details.map(field => fieldLabel(field)).join(t("Sharing.message")) },
        ...(preview.options.action === "share" ? [{ label: t("Sharing.expiresIn"), value: `${hours} ${t("Sharing.hours")}` }, { label: t("Sharing.viewLimit"), value: String(views) }] : []),
      ] : []}
      onConfirm={() => void confirm()} onCancel={cancelReview} />
    <ConfirmDialog open={Boolean(pendingDiscard)} idPrefix="sharing-discard" title={t("Sharing.discardPendingChange")} message={t("Sharing.refreshRemoteContentAndDiscardThisSaved")} onCancel={() => setPendingDiscard(null)} onConfirm={() => { const id = pendingDiscard; setPendingDiscard(null); if (id) void run(async () => { await api.pendingSharing(id, "discard"); }); }} />
  </div>;
}
