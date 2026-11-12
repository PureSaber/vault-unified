import SettingsCard from "./SettingsCard";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, clearToken, PersonalSettings } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import ImportWizard from "./ImportWizard";
import PathPicker from "./PathPicker";
import ConfirmDialog from "./ConfirmDialog";
import RecoveryRehearsal from "./RecoveryRehearsal";

const defaults: PersonalSettings = {
  lock_after_seconds: 15 * 60,
  auto_backup_enabled: false,
  auto_backup_interval_hours: 24,
  auto_backup_destination: "",
  last_auto_backup_at: "",
  backup_status: {
    last_success_at: "",
    last_error_at: "",
    last_error_summary: "",
    last_verification_at: "",
    last_verification_status: "unverified",
    recovery_kit_created_at: "",
  },
};

function sameEditableSettings(left: PersonalSettings, right: PersonalSettings) {
  return left.lock_after_seconds === right.lock_after_seconds
    && left.auto_backup_enabled === right.auto_backup_enabled
    && left.auto_backup_interval_hours === right.auto_backup_interval_hours
    && left.auto_backup_destination === right.auto_backup_destination;
}

function notifyStatusChanged() {
  window.dispatchEvent(new Event("vault-security-status-changed"));
}

function downloadText(filename: string, mimeType: string, content: string) {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function PersonalCenter({ section, onDirtyChange, onSavingChange }: {
  section: string; onDirtyChange: (value: boolean) => void; onSavingChange: (value: boolean) => void;
}) {
  const { locale, t } = useI18n();
  const { showToast: publishToast } = useToast();
  const alive = useRef(true);
  const showToast = useCallback((message: string, type?: "success" | "error" | "info") => { if (alive.current) publishToast(message, type); }, [publishToast]);
  const [childDirty, setChildDirty] = useState(false);
  const [childBusy, setChildBusy] = useState(false);
  const [operationBusy, setOperationBusy] = useState(false);
  const [saveError, setSaveError] = useState("");
  useEffect(() => {
    alive.current = true;
    const locked = () => { alive.current = false; };
    window.addEventListener("vault-ui-locked", locked);
    return () => { alive.current = false; window.removeEventListener("vault-ui-locked", locked); onDirtyChange(false); onSavingChange(false); };
  }, [onDirtyChange, onSavingChange]);

  const [settings, setSettings] = useState<PersonalSettings>(defaults);
  const [savedSettings, setSavedSettings] = useState<PersonalSettings>(defaults);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  const [saving, setSaving] = useState(false);
  const [recoveryCode, setRecoveryCode] = useState("");
  const [recoveryConfirm, setRecoveryConfirm] = useState("");
  const [recoveryDestination, setRecoveryDestination] = useState("");
  const [createdRecoveryPath, setCreatedRecoveryPath] = useState("");
  const [pendingExport, setPendingExport] = useState<"json" | "csv" | null>(null);
  const [destinationResult, setDestinationResult] = useState("");
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const [backupBusy, setBackupBusy] = useState(false);

  const settingsDirty = !sameEditableSettings(settings, savedSettings);
  useEffect(() => { onDirtyChange(!loading && (settingsDirty || Boolean(recoveryCode) || Boolean(pendingExport) || childDirty)); }, [loading, settingsDirty, recoveryCode, pendingExport, childDirty, onDirtyChange]);
  useEffect(() => { onSavingChange(saving || backupBusy || operationBusy || childBusy); }, [saving, backupBusy, operationBusy, childBusy, onSavingChange]);

  useEffect(() => {
    setLoading(true); setLoadError(false);
    api.getPersonalSettings()
      .then((loaded) => {
        if (!alive.current) return;
        setSettings(loaded);
        setSavedSettings(loaded);
      })
      .catch(() => { if (alive.current) setLoadError(true); })
      .finally(() => { if (alive.current) setLoading(false); });
  }, [reload]);

  async function saveSettings(e: React.FormEvent) {
    e.preventDefault();
    if (settings.auto_backup_enabled && !settings.auto_backup_destination.trim()) {
      setDestinationResult(t("PersonalCenter.chooseAnAutomaticBackupFolderBeforeSaving"));
      return;
    }
    setSaving(true); setSaveError("");
    try {
      const saved = await api.savePersonalSettings({
        lock_after_seconds: settings.lock_after_seconds,
        auto_backup_enabled: settings.auto_backup_enabled,
        auto_backup_interval_hours: settings.auto_backup_interval_hours,
        auto_backup_destination: settings.auto_backup_destination,
      });
      if (!alive.current) return;
      setSettings(saved);
      setSavedSettings(saved);
      window.dispatchEvent(new CustomEvent("vault-personal-settings-changed", { detail: saved }));
      notifyStatusChanged();
      showToast(t("PersonalCenter.autoLockAndAutomaticBackupSettingsSaved"));
    } catch (error) {
      if (alive.current) setSaveError(String(error).replace(/^Error:\s*/, ""));
    } finally {
      if (alive.current) setSaving(false);
    }
  }

  async function exportVault(format: "json" | "csv") {
    setPendingExport(null);
    setOperationBusy(true);
    try {
      const result = await api.exportTransfer(format);
      if (!alive.current) return;
      downloadText(result.filename, result.mime_type, result.content);
      showToast(t("PersonalCenter.plaintextExportDownloadedDeleteItAfterUse"));
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally { if (alive.current) setOperationBusy(false); }
  }

  async function generateRecoveryCode() {
    setOperationBusy(true);
    try {
      const result = await api.newRecoveryCode();
      if (!alive.current) return;
      setRecoveryCode(result.recovery_code);
      setRecoveryConfirm("");
      showToast(t("PersonalCenter.theRecoveryCodeIsShownOnlyHere"));
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally { if (alive.current) setOperationBusy(false); }
  }

  async function createRecoveryKit() {
    if (!recoveryCode || recoveryCode !== recoveryConfirm) {
      showToast(t("PersonalCenter.reEnterTheRecoveryCodeExactlyBefore"), "error");
      return;
    }
    setOperationBusy(true);
    try {
      const result = await api.createRecoveryKit(recoveryCode, recoveryDestination);
      if (!alive.current) return;
      setCreatedRecoveryPath(result.path);
      showToast(result.warning || (t("PersonalCenter.recoveryKitCreated", { value1: result.path })), result.warning ? "error" : "info");
      setRecoveryCode("");
      setRecoveryConfirm("");
      notifyStatusChanged();
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally { if (alive.current) setOperationBusy(false); }
  }

  async function testDestination() {
    if (!settings.auto_backup_destination.trim()) {
      setDestinationResult(t("PersonalCenter.chooseABackupFolderFirst"));
      return;
    }
    setBackupBusy(true);
    try {
      const result = await api.testBackupDestination(settings.auto_backup_destination);
      if (!alive.current) return;
      setDestinationResult(
        result.exists && result.writable
          ? `${t("PersonalCenter.writableFreeSpace")}: ${(result.free_bytes / (1024 ** 3)).toFixed(2)} GiB`
          : (t("PersonalCenter.thisLocationIsMissingOrNotWritable")),
      );
    } catch {
      setDestinationResult(t("PersonalCenter.theBackupFolderCouldNotBeTested"));
    } finally {
      setBackupBusy(false);
    }
  }

  async function retryBackup() {
    setBackupBusy(true);
    try {
      const result = await api.createBackup(settings.auto_backup_destination.trim() || undefined);
      if (!alive.current) return;
      showToast(result.warning || (t("PersonalCenter.encryptedBackupCreated")), result.warning ? "error" : "info");
      notifyStatusChanged();
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
      notifyStatusChanged();
    } finally {
      setBackupBusy(false);
    }
  }

  async function openRecoveryKitRestore() {
    window.location.hash = "recovery-kit";
    try {
      await api.lock();
    } catch {
      // Clearing the renderer credential is still the safe fallback.
    }
    clearToken();
    window.location.reload();
  }

  if (loadError) return <div><p className="error" role="alert">{t("settingsSave.loadFailed")}</p><button type="button" className="secondary" onClick={() => setReload(value => value + 1)}>{t("settingsSave.retry")}</button></div>;
  if (loading) return <div className="loading-state">{t("PersonalCenter.loadingPersonalSettings")}</div>;

  return (
    <>
      {section === "protection" && <SettingsCard id="personal-security-heading" title={t("PersonalCenter.autoLockAndScheduledBackups")} mode="submit">
        <form onSubmit={saveSettings}>
          <fieldset className="settings-fields" disabled={saving || backupBusy}>
          <div className="field">
            <label className="field-label" htmlFor="lock-after">
              {t("PersonalCenter.autoLockAfter")}
            </label>
            <select
              id="lock-after"
              value={settings.lock_after_seconds}
              onChange={(e) => setSettings({ ...settings, lock_after_seconds: Number(e.target.value) })}
            >
              <option value={60}>{t("PersonalCenter.1Minute")}</option>
              <option value={300}>{t("PersonalCenter.5Minutes")}</option>
              <option value={900}>{t("PersonalCenter.15Minutes")}</option>
              <option value={1800}>{t("PersonalCenter.30Minutes")}</option>
              <option value={3600}>{t("PersonalCenter.60Minutes")}</option>
            </select>
          </div>
          <h4>{t("PersonalCenter.automaticBackups")}</h4>
          <p className="field-hint">
            {t("PersonalCenter.thisFolderAndIntervalAreRememberedAfter")}
          </p>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={settings.auto_backup_enabled}
              onChange={(e) => setSettings({ ...settings, auto_backup_enabled: e.target.checked })}
            />
            <span>{t("PersonalCenter.createEncryptedBackupsWhileTheAppIs")}</span>
          </label>
          <p className="field-hint">
            {t("PersonalCenter.chooseASyncedOneDriveDropboxOrNAS")}
          </p>
          {settings.auto_backup_enabled && (
            <>
              <div className="field">
                <label className="field-label" htmlFor="backup-interval">
                  {t("PersonalCenter.backupIntervalHours")}
                </label>
                <input
                  id="backup-interval"
                  type="number"
                  min={1}
                  max={720}
                  value={settings.auto_backup_interval_hours}
                  onChange={(e) =>
                    setSettings({ ...settings, auto_backup_interval_hours: Math.max(1, Math.min(720, Number(e.target.value) || 1)) })
                  }
                />
              </div>
              <PathPicker
                id="auto-backup-destination"
                label={t("PersonalCenter.automaticBackupFolder")}
                mode="directory"
                value={settings.auto_backup_destination}
                onChange={(auto_backup_destination) => {
                  setSettings({ ...settings, auto_backup_destination });
                  setDestinationResult("");
                }}
                placeholder={t("PersonalCenter.forExampleDOneDriveVaultBackups")}
                required
              />
              <div className="button-row">
                <button className="secondary" type="button" onClick={() => void testDestination()} disabled={backupBusy}>
                  {t("PersonalCenter.testAutomaticBackupLocation")}
                </button>
                <button className="secondary" type="button" onClick={() => void retryBackup()} disabled={backupBusy || settingsDirty}>
                  {settings.backup_status?.last_error_summary ? (t("PersonalCenter.retryNow")) : (t("PersonalCenter.backUpToThisFolderNow"))}
                </button>
              </div>
              {destinationResult && <p className="field-hint" role="status">{destinationResult}</p>}
            </>
          )}
          {settingsDirty ? (
            <div className="context-notice context-notice-warning" role="status">
              <span>
                <strong>{t("PersonalCenter.changesNotSaved")}</strong><br />
                {t("PersonalCenter.automaticBackupsAreEnabledOrUpdatedOnly")}
              </span>
            </div>
          ) : (
            <div className="success" role="status">
              {settings.auto_backup_enabled
                ? (t("PersonalCenter.automaticBackupSettingsAreSavedAndEnabled"))
                : (t("PersonalCenter.settingsAreSavedAutomaticBackupsAreCurrently"))}
            </div>
          )}
          {saveError && <p className="error" role="alert">{saveError}</p>}
          <button className="primary" type="submit" disabled={saving || !settingsDirty}>
            {saving
              ? (t("PersonalCenter.saving"))
              : (t("PersonalCenter.saveAutoLockAndAutomaticBackupSettings"))}
          </button>
          </fieldset>
        </form>
      </SettingsCard>}

      {section === "transfer" && <section className="settings-section" aria-labelledby="transfer-heading">
        <h3 id="transfer-heading" className="section-title">{t("PersonalCenter.importAndExport")}</h3>
        <p className="field-hint">
          {t("PersonalCenter.plaintextExportIsAShortLivedMigration")}
        </p>
        <div className="button-row">
          <button className="secondary" type="button" onClick={() => setPendingExport("json")}>JSON</button>
          <button className="secondary" type="button" onClick={() => setPendingExport("csv")}>CSV</button>
        </div>
        <p className="field-hint">{t("PersonalCenter.plaintextExportIncludesActiveVaultEntriesUse")}</p>
        <ImportWizard onDirtyChange={setChildDirty} onSavingChange={setChildBusy} />
      </section>}

      {section === "recovery" && <section className="settings-section" aria-labelledby="recovery-heading">
        <h3 id="recovery-heading" className="section-title">{t("PersonalCenter.emergencyRecoveryKit")}</h3>
        <p className="field-hint">
          {t("PersonalCenter.anEmergencyKitIsForALost")}
        </p>
        <div className="button-row">
          <button className="secondary" type="button" disabled={operationBusy} onClick={generateRecoveryCode}>
            {recoveryCode
              ? (t("PersonalCenter.generateANewRecoveryCode"))
              : (t("PersonalCenter.createRecoveryKit"))}
          </button>
          <button className="secondary" type="button" onClick={() => setRestoreConfirm(true)}>
            {t("PersonalCenter.restoreFromRecoveryKit")}
          </button>
        </div>
        {recoveryCode && (
          <>
            <div className="field">
              <label className="field-label" htmlFor="recovery-code">{t("PersonalCenter.recoveryCodeRecordOfflineNow")}</label>
              <input id="recovery-code" value={recoveryCode} readOnly />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="recovery-confirm">{t("PersonalCenter.reEnterRecoveryCodeToConfirm")}</label>
              <input id="recovery-confirm" value={recoveryConfirm} onChange={(e) => setRecoveryConfirm(e.target.value)} autoComplete="off" />
            </div>
            <PathPicker
              id="recovery-destination"
              label={t("PersonalCenter.recoveryKitFolderPreferUSBOrAnother")}
              mode="directory"
              value={recoveryDestination}
              onChange={setRecoveryDestination}
            />
            <button className="secondary" type="button" disabled={operationBusy} onClick={createRecoveryKit}>
              {t("PersonalCenter.createRecoveryKit")}
            </button>
          </>
        )}
        {createdRecoveryPath && <p className="path-break">{t("PersonalCenter.latestRecoveryKit")}{createdRecoveryPath}</p>}
        <RecoveryRehearsal suggestedPath={createdRecoveryPath} onDirtyChange={setChildDirty} onSavingChange={setChildBusy} />
      </section>}

      <ConfirmDialog open={restoreConfirm} idPrefix="open-recovery" title={t("PersonalCenter.lockAndOpenRecovery")}
        message={t("PersonalCenter.theVaultWillLockAndUnsavedSettings")}
        confirmLabel={t("PersonalCenter.lockAndContinue")} onCancel={() => setRestoreConfirm(false)} onConfirm={() => void openRecoveryKitRestore()} />
      <ConfirmDialog
        open={pendingExport !== null}
        idPrefix="plaintext-export-confirm"
        title={t("PersonalCenter.exportAPlaintextMigrationFile")}
        message={t("PersonalCenter.theFileWillContainPlaintextPasswordsKeep")}
        confirmLabel={t("PersonalCenter.continueExport")}
        cancelLabel={t("PersonalCenter.cancel")}
        variant="danger"
        onConfirm={() => pendingExport && void exportVault(pendingExport)}
        onCancel={() => setPendingExport(null)}
      />

    </>
  );
}
