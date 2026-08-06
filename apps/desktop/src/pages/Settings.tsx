import { useEffect, useState } from "react";
import { api, SyncPrefs } from "../api/client";

export default function Settings() {
  const [prefs, setPrefs] = useState<SyncPrefs | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getPrefs().then(setPrefs);
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!prefs) return;
    await api.savePrefs(prefs);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  if (!prefs) return <div>Loading...</div>;

  return (
    <div className="card">
      <h2>Settings</h2>
      <form onSubmit={handleSave}>
        <label>Primary source (daily authority)</label>
        <select
          value={prefs.primary}
          onChange={(e) => setPrefs({ ...prefs, primary: e.target.value })}
        >
          <option value="local">Local Vault</option>
          <option value="proton_pass">Proton Pass</option>
          <option value="bitwarden">Bitwarden</option>
        </select>
        <label>
          <input
            type="checkbox"
            checked={prefs.auto_push_on_edit}
            onChange={(e) => setPrefs({ ...prefs, auto_push_on_edit: e.target.checked })}
          />{" "}
          Auto-push on edit (when primary is local)
        </label>
        <label>
          <input
            type="checkbox"
            checked={prefs.auto_pull_on_sync}
            onChange={(e) => setPrefs({ ...prefs, auto_pull_on_sync: e.target.checked })}
          />{" "}
          Auto-pull on sync
        </label>
        <label>Proton vault name</label>
        <input
          value={prefs.proton_vault_name}
          onChange={(e) => setPrefs({ ...prefs, proton_vault_name: e.target.value })}
        />
        <label>Proton share ID</label>
        <input
          value={prefs.proton_share_id}
          onChange={(e) => setPrefs({ ...prefs, proton_share_id: e.target.value })}
        />
        <button className="primary" type="submit">
          Save Settings
        </button>
        {saved && <span style={{ marginLeft: 12, color: "#68d391" }}>Saved!</span>}
      </form>
    </div>
  );
}
