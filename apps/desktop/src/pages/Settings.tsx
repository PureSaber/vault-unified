import { useEffect, useState } from "react";
import { api, SyncPrefs } from "../api/client";
import { useToast } from "../components/Toast";

export default function Settings() {
  const { showToast } = useToast();
  const [prefs, setPrefs] = useState<SyncPrefs | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getPrefs()
      .then(setPrefs)
      .catch((err) => setError(String(err)));
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!prefs) return;
    setSaving(true);
    setError("");
    try {
      await api.savePrefs(prefs);
      showToast("Settings saved");
    } catch (err) {
      setError(String(err));
      showToast(String(err), "error");
    } finally {
      setSaving(false);
    }
  }

  if (!prefs) {
    return <div className="loading-state">Loading settings…</div>;
  }

  return (
    <div className="card">
      <h2>Settings</h2>

      <form onSubmit={handleSave}>
        <section className="settings-section" aria-labelledby="sync-prefs-heading">
          <h3 id="sync-prefs-heading" className="section-title">Sync behavior</h3>
          <div className="field">
            <label className="field-label" htmlFor="primary-source">
              Primary data source
            </label>
            <select
              id="primary-source"
              value={prefs.primary}
              onChange={(e) => setPrefs({ ...prefs, primary: e.target.value })}
            >
              <option value="local">Local vault (default)</option>
              <option value="proton_pass">Proton Pass</option>
              <option value="bitwarden">Bitwarden</option>
              <option value="keepassxc">KeePassXC</option>
              <option value="gopass">gopass</option>
            </select>
            <p className="field-hint">
              Daily edits on the primary source win conflicts by default. Local primary enables auto-push on edit.
            </p>
          </div>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={prefs.auto_push_on_edit}
              onChange={(e) => setPrefs({ ...prefs, auto_push_on_edit: e.target.checked })}
            />
            <span>Auto-push to cloud when editing (when primary is local)</span>
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={prefs.auto_pull_on_sync}
              onChange={(e) => setPrefs({ ...prefs, auto_pull_on_sync: e.target.checked })}
            />
            <span>Auto-pull from cloud on sync</span>
          </label>
        </section>

        <section className="settings-section" aria-labelledby="proton-heading">
          <h3 id="proton-heading" className="section-title">Proton Pass</h3>
          <div className="field">
            <label className="field-label" htmlFor="proton-vault-name">Vault name</label>
            <input
              id="proton-vault-name"
              value={prefs.proton_vault_name}
              onChange={(e) => setPrefs({ ...prefs, proton_vault_name: e.target.value })}
              placeholder="Optional default vault"
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="proton-share-id">Share ID</label>
            <input
              id="proton-share-id"
              value={prefs.proton_share_id}
              onChange={(e) => setPrefs({ ...prefs, proton_share_id: e.target.value })}
              placeholder="Required for push to Proton"
            />
          </div>
        </section>

        {error && <div className="error" role="alert">{error}</div>}

        <div className="button-row">
          <button className="primary" type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        </div>
      </form>
    </div>
  );
}
