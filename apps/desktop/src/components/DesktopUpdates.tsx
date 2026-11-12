import SettingsCard from "./SettingsCard";
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { api } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import ConfirmDialog from "./ConfirmDialog";
import type { DesktopPreferences } from "../desktop";

export default function DesktopUpdates({ preferences, onPreferences, onBusy, savingPreferences = false }: { savingPreferences?: boolean; preferences: DesktopPreferences; onPreferences: (value: DesktopPreferences) => Promise<void>; onBusy: (value: boolean) => void }) {
  const { locale, t } = useI18n(), { showToast } = useToast();
  const [update, setUpdate] = useState<{ version: string; notes: string } | null>(null);
  const [busy, setBusy] = useState(false), [checking, setChecking] = useState(false), [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState(""), [progress, setProgress] = useState<{ downloaded: number; total: number | null; stage: string } | null>(null);
  useEffect(() => { onBusy(busy); return () => onBusy(false); }, [busy, onBusy]);
  useEffect(() => { let active = true; void api.updateStatus().then(value => { if (active) setUpdate(value); }).catch(() => {}); return () => { active = false; }; }, []);
  useEffect(() => {
    let active = true; let stop: (() => void) | undefined;
    void listen<{ downloaded: number; total: number | null; stage: string }>("desktop-update-progress", event => { if (active) setProgress(event.payload); }).then(value => { if (active) stop = value; else value(); });
    return () => { active = false; stop?.(); };
  }, []);
  async function check() {
    setChecking(true); setMessage(""); setUpdate(null);
    try { const value = await api.checkDesktopUpdate(); setUpdate(value); if (!value) setMessage(t("DesktopUpdates.thisVersionIsUpToDate")); }
    catch { setMessage(t("DesktopUpdates.couldNotCheckForUpdatesTryAgain")); }
    finally { setChecking(false); }
  }
  async function install() {
    if (!update) return; setConfirm(false); setBusy(true); setMessage("");
    try { await api.installDesktopUpdate(update.version); }
    catch (reason) {
      const value = String(reason);
      const message = value.includes("backup") ? t("DesktopUpdates.unlockAgainAndRetryInstallationStopsIf") : value.includes("install_failed") ? t("DesktopUpdates.theInstallerCouldNotStartYourVault") : t("DesktopUpdates.theUpdateCouldNotBeVerifiedOr");
      setMessage(message); showToast(message, "error"); setUpdate(null);
    } finally { setBusy(false); setProgress(null); }
  }
  return <SettingsCard id="desktop-updates-heading" title={t("DesktopUpdates.applicationUpdates")} mode="immediate">
    <label className="checkbox-field"><input type="checkbox" checked={Boolean(preferences.check_updates)} disabled={busy || checking || savingPreferences} onChange={event => void onPreferences({ ...preferences, check_updates: event.target.checked })}/><span>{t("DesktopUpdates.checkForUpdatesWhenTheAppStarts")}</span></label>
    <p className="field-hint">{t("DesktopUpdates.checksContactTheProjectSGitHubReleases")}</p>
    <button type="button" className="secondary" disabled={busy || checking || savingPreferences} onClick={() => void check()}>{checking ? t("DesktopUpdates.checking") : t("DesktopUpdates.checkForUpdates")}</button>
    {update && <div className="nested-panel"><h4>{t("DesktopUpdates.availableVersion")} {update.version}</h4><p style={{ whiteSpace: "pre-wrap" }}>{update.notes}</p><button className="primary" type="button" disabled={busy || checking || savingPreferences} onClick={() => setConfirm(true)}>{t("DesktopUpdates.reviewUpdate")}</button></div>}
    {message && <p role="status">{message}</p>}
    {busy && <p role="status">{progress?.stage === "preparing" ? t("DesktopUpdates.creatingEncryptedBackup") : progress?.stage === "installing" ? t("DesktopUpdates.startingInstaller") : t("DesktopUpdates.downloadingAndVerifying")} {progress?.stage === "downloading" && `${Math.round(progress.downloaded / 1048576)} MB${progress.total ? ` / ${Math.round(progress.total / 1048576)} MB` : ""}`}</p>}
    <ConfirmDialog open={confirm} idPrefix="desktop-update" title={t("DesktopUpdates.installUpdate")} message={t("DesktopUpdates.downloadVersionVerifyItsSignatureBackUp", { value1: update?.version ?? "" })} onCancel={() => setConfirm(false)} onConfirm={() => void install()} />
  </SettingsCard>;
}
