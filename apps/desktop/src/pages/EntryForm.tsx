import { useEffect, useState } from "react";
import { api, Entry } from "../api/client";
import PasswordField from "../components/PasswordField";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n";

interface Props {
  entry?: Entry | null;
  onDone: () => void;
}

export default function EntryForm({ entry, onDone }: Props) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const isEdit = !!entry;
  const [loading, setLoading] = useState(isEdit);
  const [title, setTitle] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");
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
      if (entry) {
        await api.updateEntry(entry.id, { title, username, password, url, notes });
        showToast(t("form.updated"));
      } else {
        await api.createEntry({ title, username, password, url, notes });
        showToast(t("form.added"));
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
