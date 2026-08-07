import { useEffect, useState } from "react";
import { api, SyncPrefs } from "../api/client";
import { useToast } from "../components/Toast";

const REMOTE_SOURCES = [
  { id: "proton_pass", label: "Proton Pass" },
  { id: "bitwarden", label: "Bitwarden" },
  { id: "keepassxc", label: "KeePassXC" },
  { id: "gopass", label: "gopass" },
] as const;

function allRemoteIds(): string[] {
  return REMOTE_SOURCES.map((s) => s.id);
}

function effectiveEnabled(prefs: SyncPrefs): string[] {
  if (prefs.enabled_sources === null || prefs.enabled_sources === undefined) {
    return allRemoteIds();
  }
  return prefs.enabled_sources;
}

function isEnabled(prefs: SyncPrefs, id: string): boolean {
  return effectiveEnabled(prefs).includes(id);
}

function toggleSource(prefs: SyncPrefs, id: string, checked: boolean): SyncPrefs {
  const current = new Set(effectiveEnabled(prefs));
  if (checked) {
    current.add(id);
  } else {
    current.delete(id);
  }
  let next: SyncPrefs = {
    ...prefs,
    enabled_sources: Array.from(current),
  };
  if (next.primary !== "local" && !current.has(next.primary)) {
    next = { ...next, primary: "local" };
  }
  return next;
}

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
      const saved = await api.savePrefs(prefs);
      setPrefs(saved);
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

  const enabledIds = effectiveEnabled(prefs);
  const primaryOptions = [
    { value: "local", label: "Local vault (default)" },
    ...REMOTE_SOURCES.filter((s) => enabledIds.includes(s.id)).map((s) => ({
      value: s.id,
      label: s.label,
    })),
  ];

  return (
    <div className="card">
      <h2>Settings</h2>

      <form onSubmit={handleSave}>
        <section className="settings-section" aria-labelledby="enabled-sources-heading">
          <h3 id="enabled-sources-heading" className="section-title">
            Enabled external sources
          </h3>
          <p className="field-hint">
            Only checked sources participate in sync. Unchecked sources keep local links but
            stop pull/push.
          </p>
          {REMOTE_SOURCES.map((src) => (
            <label className="checkbox-field" key={src.id}>
              <input
                type="checkbox"
                checked={isEnabled(prefs, src.id)}
                onChange={(e) => setPrefs(toggleSource(prefs, src.id, e.target.checked))}
              />
              <span>{src.label}</span>
            </label>
          ))}
        </section>

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
              {primaryOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="field-hint">
              Daily edits on the primary source win conflicts by default. Local primary enables
              auto-push on edit.
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
