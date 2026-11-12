import SettingsCard from "../components/SettingsCard";
import packageMetadata from "../../package.json";
import { useEffect, useRef, useState } from "react";
import { useI18n, type Locale } from "../i18n";
import { saveDesktopPreferences, type DesktopPreferences, type DesktopStatus } from "../desktop";
import HelloSettings from "../components/HelloSettings";
import DesktopUpdates from "../components/DesktopUpdates";
import { useAppearance } from "../components/Appearance";

export default function Settings({ desktop, onDesktopChange, onExit, onBusy }: { desktop: DesktopStatus | null; onDesktopChange: (value: DesktopStatus) => void; onExit: () => void; onBusy: (value: boolean) => void }) {
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useAppearance();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [updatesBusy, setUpdatesBusy] = useState(false);
  const [helloBusy, setHelloBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { onBusy(saving || updatesBusy || helloBusy); }, [saving, updatesBusy, helloBusy, onBusy]);
  useEffect(() => () => onBusy(false), [onBusy]);
  async function update(preferences: DesktopPreferences) {
    setSaving(true); setError(""); setSaved(false);
    try { const next = await saveDesktopPreferences(preferences); if (alive.current) { onDesktopChange(next); setSaved(true); } }
    catch (reason) { if (alive.current) setError(String(reason).includes("shortcut_unavailable") ? (t("Settings.thisShortcutIsInUseChooseAnother")) : (t("Settings.couldNotSaveSettingsTryAgain"))); }
    finally { if (alive.current) setSaving(false); }
  }

  return (
    <div className="card">
      <h2>{t("settings.title")}</h2>
      <p className="field-hint">{t("settings.simpleHint")}</p>

      <SettingsCard id="locale-heading" title={t("settings.language")} mode="immediate">
        <div className="field">
          <label className="field-label" htmlFor="settings-locale">
            {t("lang.label")}
          </label>
          <select
            id="settings-locale"
            value={locale}
            onChange={(event) => setLocale(event.target.value as Locale)}
          >
            <option value="zh">{t("lang.zh")}</option>
            <option value="en">{t("lang.en")}</option>
          </select>
        </div>
      </SettingsCard>

      <SettingsCard id="appearance-heading" title={t("Settings.appearance")} mode="immediate">
        <div className="field"><label className="field-label" htmlFor="settings-theme">{t("Settings.theme")}</label>
          <select id="settings-theme" value={theme} onChange={event => setTheme(event.target.value as "system" | "light" | "dark")}>
            <option value="system">{t("Settings.useSystemSetting")}</option><option value="light">{t("Settings.light")}</option><option value="dark">{t("Settings.dark")}</option>
          </select>
        </div>
      </SettingsCard>

      {desktop && <SettingsCard id="desktop-heading" title={t("Settings.quickSearchAndTray")} mode="immediate" state={saving ? "saving" : error ? "error" : saved ? "saved" : undefined}>
        <p className="field-hint">{t("Settings.openSearchFromAnyApplicationCtrlK")}</p>
        <div className="field"><label className="field-label" htmlFor="desktop-shortcut">{t("Settings.globalShortcut")}</label>
          <select id="desktop-shortcut" disabled={saving} value={desktop.preferences.shortcut} onChange={event => void update({ ...desktop.preferences, shortcut: event.target.value })}>
            <option value="Control+Shift+Space">Ctrl+Shift+Space</option><option value="Control+Alt+KeyV">Ctrl+Alt+V</option><option value="Control+Shift+KeyY">Ctrl+Shift+Y</option><option value="">{t("Settings.off")}</option>
          </select>
        </div>
        {desktop.preferences.shortcut && !desktop.shortcut_registered && <p role="status">{t("Settings.theCurrentShortcutIsUnavailableChooseAnother")}</p>}
        <label className="checkbox-field"><input type="checkbox" checked={desktop.preferences.close_to_tray} disabled={saving || !desktop.tray_available} onChange={event => void update({ ...desktop.preferences, close_to_tray: event.target.checked })} /><span>{t("Settings.keepRunningInTheTrayWhenThe")}</span></label>
        {!desktop.tray_available && <p role="status">{t("Settings.theTrayIsUnavailableClosingTheWindow")}</p>}
        <p className="field-hint">{t("Settings.autoLockStaysActiveWhileHiddenUse")}</p>
        <p className="field-hint">{t("Settings.windowsLockOrSleepLocksTheVault")}</p>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="button" className="secondary" onClick={onExit}>{t("Settings.quitVaultUnified")}</button>
      </SettingsCard>}

      {desktop && <HelloSettings onBusy={setHelloBusy} />}
      {desktop && <DesktopUpdates preferences={desktop.preferences} onPreferences={update} savingPreferences={saving} onBusy={setUpdatesBusy} />}
      <SettingsCard id="about-heading" title={t("settings.about")}>
        <dl className="status-grid">
          <div className="status-row">
            <dt>{t("settings.product")}</dt>
            <dd>Vault Unified</dd>
          </div>
          <div className="status-row">
            <dt>{t("settings.version")}</dt>
            <dd>{packageMetadata.version}</dd>
          </div>
          <div className="status-row">
            <dt>{t("settings.platform")}</dt>
            <dd>Windows</dd>
          </div>
        </dl>
      </SettingsCard>
    </div>
  );
}
