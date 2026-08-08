import { useCallback, useEffect, useState } from "react";
import { api, SyncPrefs } from "../api/client";
import { useToast } from "../components/Toast";
import { useI18n, type Locale } from "../i18n";

const REMOTE_SOURCES = [
  { id: "proton_pass", label: "Proton Pass" },
  { id: "bitwarden", label: "Bitwarden" },
  { id: "keepassxc", label: "KeePassXC" },
  { id: "gopass", label: "gopass" },
] as const;

const ENV_HINT_SOURCES = ["bitwarden", "keepassxc", "gopass"] as const;

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
  const { t, locale, setLocale } = useI18n();
  const { showToast } = useToast();
  const [prefs, setPrefs] = useState<SyncPrefs | null>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError("");
    api
      .getPrefs()
      .then((p) => {
        setPrefs(p);
        setLoadError("");
      })
      .catch((err) => {
        setPrefs(null);
        setLoadError(String(err).replace(/^Error:\s*/, ""));
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!prefs) return;
    setSaving(true);
    setError("");
    try {
      const saved = await api.savePrefs(prefs);
      setPrefs(saved);
      showToast(t("settings.saved"));
    } catch (err) {
      const msg = String(err).replace(/^Error:\s*/, "");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="loading-state">{t("settings.loading")}</div>;
  }

  if (loadError || !prefs) {
    return (
      <div className="card">
        <h2>{t("settings.title")}</h2>
        <div className="error" role="alert">
          {loadError || t("settings.loadError")}
        </div>
        <div className="button-row">
          <button type="button" className="primary" onClick={load}>
            {t("settings.retry")}
          </button>
        </div>
      </div>
    );
  }

  const enabledIds = effectiveEnabled(prefs);
  const primaryOptions = [
    { value: "local", label: t("settings.primaryLocal") },
    ...REMOTE_SOURCES.filter((s) => enabledIds.includes(s.id)).map((s) => ({
      value: s.id,
      label: s.label,
    })),
  ];

  return (
    <div className="card">
      <h2>{t("settings.title")}</h2>

      <form onSubmit={handleSave}>
        <section className="settings-section" aria-labelledby="enabled-sources-heading">
          <h3 id="enabled-sources-heading" className="section-title">
            {t("settings.enabledSources")}
          </h3>
          <p className="field-hint">{t("settings.enabledHint")}</p>
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
          <button
            type="button"
            className="secondary"
            onClick={() => setPrefs({ ...prefs, enabled_sources: null })}
            title={t("settings.resetSourcesHint")}
          >
            {t("settings.resetSources")}
          </button>
        </section>

        <section className="settings-section" aria-labelledby="sync-prefs-heading">
          <h3 id="sync-prefs-heading" className="section-title">
            {t("settings.syncBehavior")}
          </h3>
          <div className="field">
            <label className="field-label" htmlFor="primary-source">
              {t("settings.primary")}
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
            <p className="field-hint">{t("settings.primaryHint")}</p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="conflict-default">
              {t("settings.conflictDefault")}
            </label>
            <select
              id="conflict-default"
              value={prefs.conflict_default || "primary"}
              onChange={(e) =>
                setPrefs({ ...prefs, conflict_default: e.target.value })
              }
            >
              <option value="primary">{t("settings.conflictPrimary")}</option>
              <option value="manual">{t("settings.conflictManual")}</option>
            </select>
          </div>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={prefs.auto_push_on_edit}
              onChange={(e) => setPrefs({ ...prefs, auto_push_on_edit: e.target.checked })}
            />
            <span>{t("settings.autoPush")}</span>
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={prefs.auto_pull_on_sync}
              onChange={(e) => setPrefs({ ...prefs, auto_pull_on_sync: e.target.checked })}
            />
            <span>{t("settings.autoPull")}</span>
          </label>
        </section>

        <section className="settings-section" aria-labelledby="proton-heading">
          <h3 id="proton-heading" className="section-title">
            {t("settings.proton")}
          </h3>
          <div className="field">
            <label className="field-label" htmlFor="proton-vault-name">
              {t("settings.protonVault")}
            </label>
            <input
              id="proton-vault-name"
              value={prefs.proton_vault_name}
              onChange={(e) => setPrefs({ ...prefs, proton_vault_name: e.target.value })}
              placeholder={t("settings.protonVaultPlaceholder")}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="proton-share-id">
              {t("settings.protonShare")}
            </label>
            <input
              id="proton-share-id"
              value={prefs.proton_share_id}
              onChange={(e) => setPrefs({ ...prefs, proton_share_id: e.target.value })}
              placeholder={t("settings.protonSharePlaceholder")}
            />
          </div>
        </section>

        <section className="settings-section" aria-labelledby="source-hints-heading">
          <h3 id="source-hints-heading" className="section-title">
            {t("settings.sourceStatus")}
          </h3>
          <ul className="source-hint-list">
            {ENV_HINT_SOURCES.map((id) => {
              const label = REMOTE_SOURCES.find((s) => s.id === id)?.label || id;
              return (
                <li key={id}>
                  <strong>{label}</strong>: {t("settings.configureHint")}
                </li>
              );
            })}
          </ul>
        </section>

        <section className="settings-section" aria-labelledby="locale-heading">
          <h3 id="locale-heading" className="section-title">
            {t("settings.language")}
          </h3>
          <div className="field">
            <label className="field-label" htmlFor="settings-locale">
              {t("lang.label")}
            </label>
            <select
              id="settings-locale"
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
            >
              <option value="zh">{t("lang.zh")}</option>
              <option value="en">{t("lang.en")}</option>
            </select>
          </div>
        </section>

        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        <div className="button-row">
          <button className="primary" type="submit" disabled={saving}>
            {saving ? t("settings.saving") : t("settings.save")}
          </button>
        </div>
      </form>
    </div>
  );
}
