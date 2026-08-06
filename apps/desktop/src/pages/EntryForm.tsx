import { useState } from "react";
import { api, Entry } from "../api/client";
import PasswordField from "../components/PasswordField";
import { useToast } from "../components/Toast";

interface Props {
  entry?: Entry | null;
  onDone: () => void;
}

export default function EntryForm({ entry, onDone }: Props) {
  const { showToast } = useToast();
  const [title, setTitle] = useState(entry?.title || "");
  const [username, setUsername] = useState(entry?.username || "");
  const [password, setPassword] = useState(entry?.password || "");
  const [url, setUrl] = useState(entry?.url || "");
  const [notes, setNotes] = useState(entry?.notes || "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleGenerate() {
    try {
      const res = await api.generate(20);
      setPassword(res.password);
      showToast("Password generated");
    } catch (err) {
      showToast(String(err), "error");
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      if (entry) {
        await api.updateEntry(entry.id, { title, username, password, url, notes });
        showToast("Entry updated");
      } else {
        await api.createEntry({ title, username, password, url, notes });
        showToast("Entry added");
      }
      onDone();
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h2>{entry ? "Edit entry" : "Add entry"}</h2>
      <form onSubmit={handleSave}>
        <div className="field">
          <label className="field-label" htmlFor="entry-title">Title</label>
          <input
            id="entry-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="e.g. GitHub"
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-username">Username</label>
          <input
            id="entry-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="email or username"
            autoComplete="off"
          />
        </div>
        <PasswordField
          id="entry-password"
          label="Password"
          value={password}
          onChange={setPassword}
          hint="Masked by default. Use Generate for a strong random password."
        />
        <div className="input-row" style={{ marginBottom: "var(--space-lg)" }}>
          <button type="button" className="secondary" onClick={handleGenerate}>
            Generate password
          </button>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-url">URL</label>
          <input
            id="entry-url"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://"
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="entry-notes">Notes</label>
          <textarea
            id="entry-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Optional notes"
          />
        </div>
        {error && (
          <div className="error" role="alert" id="entry-form-error">
            {error}
          </div>
        )}
        <div className="button-row">
          <button className="primary" type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button className="secondary" type="button" onClick={onDone}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
