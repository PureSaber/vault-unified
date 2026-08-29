import { useEffect, useState } from "react";
import { api, Attachment, Entry } from "../api/client";
import PasswordField from "../components/PasswordField";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n";

interface Props {
  entry?: Entry | null;
  onDone: () => void;
}

type CustomField = { label: string; value: string; concealed: boolean };

const ENTRY_TYPES = ["login", "secure_note", "card", "identity", "ssh_key", "recovery_code"] as const;

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

export default function EntryForm({ entry, onDone }: Props) {
  const { t, locale } = useI18n();
  const { showToast } = useToast();
  const zh = locale === "zh";
  const isEdit = !!entry;
  const [loading, setLoading] = useState(isEdit);
  const [title, setTitle] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [entryType, setEntryType] = useState<(typeof ENTRY_TYPES)[number]>("login");
  const [customFields, setCustomFields] = useState<CustomField[]>([]);
  const [totpSecret, setTotpSecret] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [newAttachments, setNewAttachments] = useState<File[]>([]);
  const [history, setHistory] = useState<Array<{ id: string; saved_at: string }>>([]);
  const [genLength, setGenLength] = useState(20);
  const [genSymbols, setGenSymbols] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!entry) {
      setLoading(false);
      setTitle("");
      setUsername("");
      setPassword("");
      setUrl("");
      setNotes("");
      setEntryType("login");
      setCustomFields([]);
      setTotpSecret("");
      setAttachments([]);
      setNewAttachments([]);
      setHistory([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .getEntry(entry.id, true)
      .then((full) => {
        if (cancelled) return;
        setTitle(full.title || "");
        setUsername(full.username || "");
        setPassword(full.password || "");
        setUrl(full.url || "");
        setNotes(full.notes || "");
        setEntryType(full.entry_type || "login");
        setCustomFields(full.custom_fields || []);
        setTotpSecret(full.totp_secret || "");
        setAttachments(full.attachments || []);
        return api.entryHistory(entry.id, false);
      })
      .then((historyResult) => {
        if (cancelled || !historyResult) return;
        setHistory(historyResult.history.map((item) => ({ id: item.id, saved_at: item.saved_at })));
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = String(err).replace(/^Error:\s*/, "");
        setError(msg);
        showToast(msg, "error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [entry, showToast]);

  async function handleGenerate() {
    try {
      const res = await api.generate(genLength, genSymbols);
      setPassword(res.password);
      showToast(t("form.generated"));
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      let saved: Entry;
      if (entry) {
        saved = await api.updateEntry(entry.id, {
          title,
          username,
          password,
          url,
          notes,
          entry_type: entryType,
          custom_fields: customFields,
          totp_secret: totpSecret,
        });
        showToast(t("form.updated"));
      } else {
        saved = await api.createEntry({
          title,
          username,
          password,
          url,
          notes,
          entry_type: entryType,
          custom_fields: customFields,
          totp_secret: totpSecret,
        });
        showToast(t("form.added"));
      }
      for (const file of newAttachments) {
        await api.addAttachment(
          saved.id,
          file.name,
          file.type || "application/octet-stream",
          await fileToBase64(file)
        );
      }
      onDone();
    } catch (err) {
      const msg = String(err).replace(/^Error:\s*/, "");
      setError(msg);
      showToast(msg || t("form.saveError"), "error");
    } finally {
      setSaving(false);
    }
  }

  function updateCustomField(index: number, patch: Partial<CustomField>) {
    setCustomFields((current) => current.map((field, itemIndex) => itemIndex === index ? { ...field, ...patch } : field));
  }

  async function removeExistingAttachment(attachment: Attachment) {
    if (!entry) return;
    try {
      const result = await api.removeAttachment(entry.id, attachment.id);
      setAttachments(result.entry.attachments);
      showToast(zh ? "附件已删除" : "Attachment removed");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function saveExistingAttachment(attachment: Attachment) {
    if (!entry) return;
    try {
      const result = await api.downloadAttachment(entry.id, attachment.id);
      downloadAttachment(result.filename, result.mime_type, result.data_b64);
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function restoreVersion(historyId: string) {
    if (!entry) return;
    if (!window.confirm(zh ? "恢复此版本将覆盖当前字段，并保留一个当前版本历史。继续？" : "Restore this version? Current fields will be preserved in history.")) return;
    try {
      const restored = await api.restoreEntryHistory(entry.id, historyId);
      setTitle(restored.title);
      setUsername(restored.username);
      setPassword(restored.password);
      setUrl(restored.url);
      setNotes(restored.notes);
      setEntryType(restored.entry_type);
      setCustomFields(restored.custom_fields);
      setTotpSecret(restored.totp_secret);
      setAttachments(restored.attachments);
      const refreshed = await api.entryHistory(entry.id, false);
      setHistory(refreshed.history.map((item) => ({ id: item.id, saved_at: item.saved_at })));
      showToast(zh ? "已恢复条目版本" : "Entry version restored");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  if (loading) {
    return <div className="loading-state">{t("form.loading")}</div>;
  }

  return (
    <div className="card">
      <h2>{isEdit ? t("form.edit") : t("form.add")}</h2>
      <form onSubmit={handleSave}>
        <div className="field">
          <label className="field-label" htmlFor="entry-title">
            {t("form.title")}
          </label>
          <input
            id="entry-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder={t("form.titlePlaceholder")}
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-type">
            {zh ? "条目类型" : "Entry type"}
          </label>
          <select id="entry-type" value={entryType} onChange={(e) => setEntryType(e.target.value as (typeof ENTRY_TYPES)[number])}>
            {ENTRY_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-username">
            {t("form.username")}
          </label>
          <input
            id="entry-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder={t("form.usernamePlaceholder")}
            autoComplete="off"
          />
        </div>
        <PasswordField
          id="entry-totp"
          label={zh ? "TOTP 密钥（可选）" : "TOTP secret (optional)"}
          value={totpSecret}
          onChange={setTotpSecret}
          hint={zh ? "仅保存在本地加密库；目前不会写回外部服务。" : "Stored only in the local encrypted vault; it is not written to external services."}
        />
        <section className="settings-section" aria-labelledby="custom-fields-heading">
          <h3 id="custom-fields-heading" className="section-title">{zh ? "自定义字段" : "Custom fields"}</h3>
          {customFields.map((field, index) => (
            <div className="generate-row" key={`${field.label}-${index}`}>
              <input value={field.label} onChange={(e) => updateCustomField(index, { label: e.target.value })} placeholder={zh ? "标签" : "Label"} />
              <input value={field.value} onChange={(e) => updateCustomField(index, { value: e.target.value })} placeholder={zh ? "值" : "Value"} />
              <label className="checkbox-field">
                <input type="checkbox" checked={field.concealed} onChange={(e) => updateCustomField(index, { concealed: e.target.checked })} />
                <span>{zh ? "隐藏" : "Hide"}</span>
              </label>
              <button type="button" className="secondary" onClick={() => setCustomFields((current) => current.filter((_, itemIndex) => itemIndex !== index))}>{zh ? "移除" : "Remove"}</button>
            </div>
          ))}
          <button type="button" className="secondary" onClick={() => setCustomFields((current) => [...current, { label: "", value: "", concealed: false }])} disabled={customFields.length >= 32}>
            {zh ? "添加字段" : "Add field"}
          </button>
        </section>
        <section className="settings-section" aria-labelledby="attachments-heading">
          <h3 id="attachments-heading" className="section-title">{zh ? "加密附件" : "Encrypted attachments"}</h3>
          <p className="field-hint">{zh ? "每个附件最多 1 MiB，每个条目最多 10 个；附件只保存在本地加密保险库。" : "Up to 1 MiB each and 10 per entry. Attachments stay only in the local encrypted vault."}</p>
          {attachments.map((attachment) => (
            <div className="button-row" key={attachment.id}>
              <span>{attachment.filename} ({Math.ceil(attachment.size / 1024)} KiB)</span>
              <button type="button" className="secondary" onClick={() => saveExistingAttachment(attachment)}>{zh ? "下载" : "Download"}</button>
              <button type="button" className="secondary" onClick={() => removeExistingAttachment(attachment)}>{zh ? "删除" : "Remove"}</button>
            </div>
          ))}
          <input type="file" multiple onChange={(e) => setNewAttachments(Array.from(e.target.files || []))} />
          {newAttachments.length > 0 && <p className="field-hint">{zh ? `待上传 ${newAttachments.length} 个附件，保存时写入加密库。` : `${newAttachments.length} attachment(s) will be encrypted when you save.`}</p>}
        </section>
        {entry && (
          <section className="settings-section" aria-labelledby="history-heading">
            <h3 id="history-heading" className="section-title">{zh ? "条目历史" : "Entry history"}</h3>
            {history.length === 0 ? <p className="field-hint">{zh ? "尚无历史版本。" : "No saved versions yet."}</p> : history.map((item) => (
              <div className="button-row" key={item.id}>
                <span>{new Date(item.saved_at).toLocaleString()}</span>
                <button type="button" className="secondary" onClick={() => restoreVersion(item.id)}>{zh ? "恢复此版本" : "Restore version"}</button>
              </div>
            ))}
          </section>
        )}
        <PasswordField
          id="entry-password"
          label={t("form.password")}
          value={password}
          onChange={setPassword}
          hint={t("form.passwordHint")}
        />
        <div className="generate-row">
          <div className="field generate-length">
            <label className="field-label" htmlFor="gen-length">
              {t("form.genLength")}
            </label>
            <input
              id="gen-length"
              type="number"
              min={12}
              max={64}
              value={genLength}
              onChange={(e) =>
                setGenLength(Math.min(64, Math.max(12, Number(e.target.value) || 12)))
              }
            />
          </div>
          <label className="checkbox-field generate-symbols">
            <input
              type="checkbox"
              checked={genSymbols}
              onChange={(e) => setGenSymbols(e.target.checked)}
            />
            <span>{t("form.genSymbols")}</span>
          </label>
          <button type="button" className="secondary" onClick={handleGenerate}>
            {t("form.generate")}
          </button>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-url">
            {t("form.url")}
          </label>
          <input
            id="entry-url"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://"
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-notes">
            {t("form.notes")}
          </label>
          <textarea
            id="entry-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder={t("form.notesPlaceholder")}
          />
        </div>
        {error && (
          <div className="error" role="alert" id="entry-form-error">
            {error}
          </div>
        )}
        <div className="button-row">
          <button className="primary" type="submit" disabled={saving}>
            {saving ? t("form.saving") : t("form.save")}
          </button>
          <button className="secondary" type="button" onClick={onDone}>
            {t("form.cancel")}
          </button>
        </div>
      </form>
    </div>
  );
}
