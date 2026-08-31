import { useEffect, useMemo, useRef, useState } from "react";
import { api, Attachment, Entry } from "../api/client";
import ConfirmDialog from "../components/ConfirmDialog";
import PasswordField from "../components/PasswordField";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n";

interface Props {
  entry?: Entry | null;
  onDone: (saved?: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onSavingChange?: (saving: boolean) => void;
}

type EntryType = "login" | "secure_note" | "card" | "identity" | "ssh_key" | "recovery_code";
type CustomField = { clientId: string; label: string; value: string; concealed: boolean };
type PendingAttachment = { clientId: string; file: File };
type Draft = {
  title: string;
  username: string;
  password: string;
  url: string;
  notes: string;
  tags: string[];
  entryType: EntryType;
  customFields: CustomField[];
  totpSecret: string;
  attachments: Attachment[];
  pendingAttachments: PendingAttachment[];
  restoreHistoryId: string | null;
};

const ENTRY_TYPES: EntryType[] = ["login", "secure_note", "card", "identity", "ssh_key", "recovery_code"];

function clientId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `draft-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptyDraft(): Draft {
  return {
    title: "",
    username: "",
    password: "",
    url: "",
    notes: "",
    tags: [],
    entryType: "login",
    customFields: [],
    totpSecret: "",
    attachments: [],
    pendingAttachments: [],
    restoreHistoryId: null,
  };
}

function draftFromEntry(entry: Entry): Draft {
  return {
    title: entry.title || "",
    username: entry.username || "",
    password: entry.password || "",
    url: entry.url || "",
    notes: entry.notes || "",
    tags: [...(entry.tags || [])],
    entryType: entry.entry_type || "login",
    customFields: (entry.custom_fields || []).map((field) => ({ ...field, clientId: clientId() })),
    totpSecret: entry.totp_secret || "",
    attachments: [...(entry.attachments || [])],
    pendingAttachments: [],
    restoreHistoryId: null,
  };
}

function fingerprint(draft: Draft): string {
  return JSON.stringify({
    title: draft.title,
    username: draft.username,
    password: draft.password,
    url: draft.url,
    notes: draft.notes,
    tags: draft.tags,
    entryType: draft.entryType,
    customFields: draft.customFields.map(({ label, value, concealed }) => ({ label, value, concealed })),
    totpSecret: draft.totpSecret,
    attachmentIds: draft.attachments.map((item) => item.id),
    pendingAttachments: draft.pendingAttachments.map(({ clientId: id, file }) => ({
      id,
      name: file.name,
      size: file.size,
      type: file.type,
      lastModified: file.lastModified,
    })),
    restoreHistoryId: draft.restoreHistoryId,
  });
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read attachment"));
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.slice(value.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}

function downloadAttachment(filename: string, mimeType: string, dataB64: string) {
  const raw = atob(dataB64);
  const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function EntryForm({ entry, onDone, onDirtyChange, onSavingChange }: Props) {
  const { t, locale } = useI18n();
  const { showToast } = useToast();
  const zh = locale === "zh";
  const isEdit = Boolean(entry);
  const initial = useMemo(emptyDraft, []);
  const [original, setOriginal] = useState<Draft>(initial);
  const [draft, setDraft] = useState<Draft>(initial);
  const [loading, setLoading] = useState(isEdit);
  const [history, setHistory] = useState<Array<{ id: string; saved_at: string }>>([]);
  const [historyToRestore, setHistoryToRestore] = useState<string | null>(null);
  const [historyPreviewing, setHistoryPreviewing] = useState(false);
  const [genLength, setGenLength] = useState(20);
  const [genSymbols, setGenSymbols] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const transactionId = useRef(clientId());

  const dirty = fingerprint(draft) !== fingerprint(original);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    onSavingChange?.(saving);
  }, [saving, onSavingChange]);

  useEffect(() => () => {
    onDirtyChange?.(false);
    onSavingChange?.(false);
  }, [onDirtyChange, onSavingChange]);

  useEffect(() => {
    transactionId.current = clientId();
    if (!entry) {
      const blank = emptyDraft();
      setOriginal(blank);
      setDraft(blank);
      setHistory([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([api.getEntry(entry.id, true), api.entryHistory(entry.id, false)])
      .then(([full, historyResult]) => {
        if (cancelled) return;
        const loaded = draftFromEntry(full);
        setOriginal(loaded);
        setDraft(loaded);
        setHistory(historyResult.history.map((item) => ({ id: item.id, saved_at: item.saved_at })));
      })
      .catch((err) => {
        if (cancelled) return;
        const message = String(err).replace(/^Error:\s*/, "");
        setError(message);
        showToast(message, "error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [entry, showToast]);

  function patchDraft(patch: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  async function handleGenerate() {
    try {
      const result = await api.generate(genLength, genSymbols);
      patchDraft({ password: result.password });
      showToast(t("form.generated"));
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    setError("");
    setSaving(true);
    try {
      const addAttachments = await Promise.all(
        draft.pendingAttachments.map(async ({ file }) => ({
          filename: file.name,
          mime_type: file.type || "application/octet-stream",
          data_b64: await fileToBase64(file),
        })),
      );
      const keptIds = new Set(draft.attachments.map((attachment) => attachment.id));
      await api.commitEntry({
        transaction_id: transactionId.current,
        entry_id: entry?.id ?? null,
        expected_updated_at: entry?.updated_at ?? null,
        title: draft.title,
        username: draft.username,
        password: draft.password,
        url: draft.url,
        notes: draft.notes,
        tags: draft.tags,
        entry_type: draft.entryType,
        custom_fields: draft.customFields.map(({ label, value, concealed }) => ({ label, value, concealed })),
        totp_secret: draft.totpSecret,
        add_attachments: addAttachments,
        remove_attachment_ids: original.attachments.filter((attachment) => !keptIds.has(attachment.id)).map((attachment) => attachment.id),
        restore_history_id: draft.restoreHistoryId,
      });
      setDraft(emptyDraft());
      setOriginal(emptyDraft());
      onDirtyChange?.(false);
      showToast(entry ? t("form.updated") : t("form.added"));
      onDone(true);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message || t("form.saveError"), "error");
    } finally {
      setSaving(false);
    }
  }

  function updateCustomField(id: string, patch: Partial<CustomField>) {
    patchDraft({ customFields: draft.customFields.map((field) => field.clientId === id ? { ...field, ...patch } : field) });
  }

  async function saveExistingAttachment(attachment: Attachment) {
    if (!entry) return;
    try {
      const result = await api.downloadAttachment(entry.id, attachment.id);
      downloadAttachment(result.filename, result.mime_type, result.data_b64);
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function previewHistoryRestore() {
    if (!entry || !historyToRestore || historyPreviewing) return;
    setHistoryPreviewing(true);
    try {
      const preview = await api.previewEntryHistory(entry.id, historyToRestore);
      const restored = draftFromEntry(preview.entry);
      setDraft((current) => ({
        ...current,
        title: restored.title,
        username: restored.username,
        password: restored.password,
        url: restored.url,
        notes: restored.notes,
        tags: restored.tags,
        entryType: restored.entryType,
        customFields: restored.customFields,
        totpSecret: restored.totpSecret,
        restoreHistoryId: historyToRestore,
      }));
      showToast(zh ? "历史版本已载入草稿；保存前不会修改保险库" : "Version loaded into the draft; the vault is unchanged until you save");
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    } finally {
      setHistoryPreviewing(false);
      setHistoryToRestore(null);
    }
  }

  if (loading) return <div className="loading-state">{t("form.loading")}</div>;

  return (
    <div className="card">
      <h2>{isEdit ? t("form.edit") : t("form.add")}</h2>
      <form onSubmit={handleSave} aria-busy={saving}>
        <div className="field">
          <label className="field-label" htmlFor="entry-title">{t("form.title")}</label>
          <input id="entry-title" value={draft.title} onChange={(event) => patchDraft({ title: event.target.value })} required placeholder={t("form.titlePlaceholder")} />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-type">{zh ? "条目类型" : "Entry type"}</label>
          <select id="entry-type" value={draft.entryType} onChange={(event) => patchDraft({ entryType: event.target.value as EntryType })}>
            {ENTRY_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-username">{t("form.username")}</label>
          <input id="entry-username" value={draft.username} onChange={(event) => patchDraft({ username: event.target.value })} placeholder={t("form.usernamePlaceholder")} autoComplete="off" />
        </div>
        <PasswordField id="entry-totp" label={zh ? "TOTP 密钥（可选）" : "TOTP secret (optional)"} value={draft.totpSecret} onChange={(totpSecret) => patchDraft({ totpSecret })} hint={zh ? "仅保存在本地加密库；目前不会写回外部服务。" : "Stored only in the local encrypted vault; it is not written to external services."} />
        <section className="settings-section" aria-labelledby="custom-fields-heading">
          <h3 id="custom-fields-heading" className="section-title">{zh ? "自定义字段" : "Custom fields"}</h3>
          {draft.customFields.map((field) => (
            <div className="generate-row" key={field.clientId}>
              <label className="sr-only" htmlFor={`custom-label-${field.clientId}`}>{zh ? "字段标签" : "Field label"}</label>
              <input id={`custom-label-${field.clientId}`} value={field.label} onChange={(event) => updateCustomField(field.clientId, { label: event.target.value })} placeholder={zh ? "标签" : "Label"} />
              <label className="sr-only" htmlFor={`custom-value-${field.clientId}`}>{zh ? "字段值" : "Field value"}</label>
              <input id={`custom-value-${field.clientId}`} value={field.value} onChange={(event) => updateCustomField(field.clientId, { value: event.target.value })} placeholder={zh ? "值" : "Value"} />
              <label className="checkbox-field">
                <input type="checkbox" checked={field.concealed} onChange={(event) => updateCustomField(field.clientId, { concealed: event.target.checked })} />
                <span>{zh ? "隐藏" : "Hide"}</span>
              </label>
              <button type="button" className="secondary" onClick={() => patchDraft({ customFields: draft.customFields.filter((item) => item.clientId !== field.clientId) })}>{zh ? "移除" : "Remove"}</button>
            </div>
          ))}
          <button type="button" className="secondary" onClick={() => patchDraft({ customFields: [...draft.customFields, { clientId: clientId(), label: "", value: "", concealed: false }] })} disabled={draft.customFields.length >= 32}>{zh ? "添加字段" : "Add field"}</button>
        </section>
        <section className="settings-section" aria-labelledby="attachments-heading">
          <h3 id="attachments-heading" className="section-title">{zh ? "加密附件" : "Encrypted attachments"}</h3>
          <p className="field-hint">{zh ? "附件更改会和条目一起保存；取消不会修改保险库。" : "Attachment changes are saved with the entry; cancel leaves the vault unchanged."}</p>
          {draft.attachments.map((attachment) => (
            <div className="button-row" key={attachment.id}>
              <span>{attachment.filename} ({Math.ceil(attachment.size / 1024)} KiB)</span>
              <button type="button" className="secondary" onClick={() => saveExistingAttachment(attachment)}>{zh ? "下载" : "Download"}</button>
              <button type="button" className="secondary" onClick={() => patchDraft({ attachments: draft.attachments.filter((item) => item.id !== attachment.id) })}>{zh ? "保存时删除" : "Remove on save"}</button>
            </div>
          ))}
          {draft.pendingAttachments.map(({ clientId: id, file }) => (
            <div className="button-row" key={id}>
              <span>{file.name} ({Math.ceil(file.size / 1024)} KiB)</span>
              <button type="button" className="secondary" onClick={() => patchDraft({ pendingAttachments: draft.pendingAttachments.filter((item) => item.clientId !== id) })}>{zh ? "移除待添加项" : "Remove pending file"}</button>
            </div>
          ))}
          <label className="field-label" htmlFor="entry-attachments">{zh ? "选择附件" : "Choose attachments"}</label>
          <input id="entry-attachments" type="file" multiple onChange={(event) => {
            const additions = Array.from(event.target.files || []).map((file) => ({ clientId: clientId(), file }));
            patchDraft({ pendingAttachments: [...draft.pendingAttachments, ...additions] });
            event.target.value = "";
          }} />
        </section>
        {entry && (
          <section className="settings-section" aria-labelledby="history-heading">
            <h3 id="history-heading" className="section-title">{zh ? "条目历史" : "Entry history"}</h3>
            {history.length === 0 ? <p className="field-hint">{zh ? "尚无历史版本。" : "No saved versions yet."}</p> : history.map((item) => (
              <div className="button-row" key={item.id}>
                <span>{new Date(item.saved_at).toLocaleString()}</span>
                <button type="button" className="secondary" onClick={() => setHistoryToRestore(item.id)}>{zh ? "载入草稿预览" : "Preview in draft"}</button>
              </div>
            ))}
          </section>
        )}
        <PasswordField id="entry-password" label={t("form.password")} value={draft.password} onChange={(password) => patchDraft({ password })} hint={t("form.passwordHint")} />
        <div className="generate-row">
          <div className="field generate-length">
            <label className="field-label" htmlFor="gen-length">{t("form.genLength")}</label>
            <input id="gen-length" type="number" min={12} max={64} value={genLength} onChange={(event) => setGenLength(Math.min(64, Math.max(12, Number(event.target.value) || 12)))} />
          </div>
          <label className="checkbox-field"><input type="checkbox" checked={genSymbols} onChange={(event) => setGenSymbols(event.target.checked)} /><span>{t("form.genSymbols")}</span></label>
          <button type="button" className="secondary" onClick={handleGenerate}>{t("form.generate")}</button>
        </div>
        <div className="field"><label className="field-label" htmlFor="entry-url">{t("form.url")}</label><input id="entry-url" type="url" value={draft.url} onChange={(event) => patchDraft({ url: event.target.value })} placeholder="https://" /></div>
        <div className="field"><label className="field-label" htmlFor="entry-notes">{t("form.notes")}</label><textarea id="entry-notes" value={draft.notes} onChange={(event) => patchDraft({ notes: event.target.value })} rows={3} placeholder={t("form.notesPlaceholder")} /></div>
        {error && <div className="error" role="alert" id="entry-form-error">{error}</div>}
        <div className="button-row">
          <button className="primary" type="submit" disabled={saving}>{saving ? t("form.saving") : t("form.save")}</button>
          <button className="secondary" type="button" onClick={() => onDone()} disabled={saving}>{t("form.cancel")}</button>
        </div>
      </form>
      <ConfirmDialog
        open={historyToRestore !== null}
        idPrefix="history-draft-confirm"
        title={zh ? "将历史版本载入草稿？" : "Load this version into the draft?"}
        message={zh ? "这只会更新当前表单。只有点击保存后才会修改保险库。" : "This updates only the current form. The vault changes only after you save."}
        confirmLabel={historyPreviewing ? (zh ? "正在载入…" : "Loading…") : (zh ? "载入草稿" : "Load draft")}
        cancelLabel={t("form.cancel")}
        onConfirm={() => void previewHistoryRestore()}
        onCancel={() => setHistoryToRestore(null)}
      />
    </div>
  );
}
