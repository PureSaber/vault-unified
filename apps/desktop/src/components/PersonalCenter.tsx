import { useEffect, useState } from "react";
import { api, clearToken, PersonalSettings } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import ImportWizard from "./ImportWizard";
import PathPicker from "./PathPicker";
import ConfirmDialog from "./ConfirmDialog";

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

export default function PersonalCenter() {
  const { locale } = useI18n();
  const { showToast } = useToast();
  const zh = locale === "zh";
  const [settings, setSettings] = useState<PersonalSettings>(defaults);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [recoveryCode, setRecoveryCode] = useState("");
  const [recoveryConfirm, setRecoveryConfirm] = useState("");
  const [recoveryDestination, setRecoveryDestination] = useState("");
  const [pendingExport, setPendingExport] = useState<"json" | "csv" | null>(null);
  const [destinationResult, setDestinationResult] = useState("");
  const [backupBusy, setBackupBusy] = useState(false);

  useEffect(() => {
    api.getPersonalSettings()
      .then(setSettings)
      .catch((error) => showToast(String(error).replace(/^Error:\s*/, ""), "error"))
      .finally(() => setLoading(false));
  }, [showToast]);

  async function saveSettings(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const saved = await api.savePersonalSettings({
        lock_after_seconds: settings.lock_after_seconds,
        auto_backup_enabled: settings.auto_backup_enabled,
        auto_backup_interval_hours: settings.auto_backup_interval_hours,
        auto_backup_destination: settings.auto_backup_destination,
      });
      setSettings(saved);
      window.dispatchEvent(new CustomEvent("vault-personal-settings-changed", { detail: saved }));
      notifyStatusChanged();
      showToast(zh ? "个人安全设置已保存" : "Personal security settings saved");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally {
      setSaving(false);
    }
  }

  async function exportVault(format: "json" | "csv") {
    setPendingExport(null);
    try {
      const result = await api.exportTransfer(format);
      downloadText(result.filename, result.mime_type, result.content);
      showToast(zh ? "明文导出已下载；请在使用后删除该文件" : "Plaintext export downloaded; delete it after use");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function generateRecoveryCode() {
    try {
      const result = await api.newRecoveryCode();
      setRecoveryCode(result.recovery_code);
      setRecoveryConfirm("");
      showToast(zh ? "恢复码只会显示在此处；请离线保存" : "The recovery code is shown only here; save it offline");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function createRecoveryKit() {
    if (!recoveryCode || recoveryCode !== recoveryConfirm) {
      showToast(zh ? "请准确重新输入恢复码后再创建" : "Re-enter the recovery code exactly before creating the kit", "error");
      return;
    }
    try {
      const result = await api.createRecoveryKit(recoveryCode, recoveryDestination);
      showToast(result.warning || (zh ? `恢复包已创建：${result.path}` : `Recovery kit created: ${result.path}`), result.warning ? "error" : "info");
      setRecoveryCode("");
      setRecoveryConfirm("");
      notifyStatusChanged();
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function testDestination() {
    if (!settings.auto_backup_destination.trim()) {
      setDestinationResult(zh ? "请先选择备份位置。" : "Choose a backup folder first.");
      return;
    }
    setBackupBusy(true);
    try {
      const result = await api.testBackupDestination(settings.auto_backup_destination);
      setDestinationResult(
        result.exists && result.writable
          ? `${zh ? "可写，剩余空间" : "Writable, free space"}: ${(result.free_bytes / (1024 ** 3)).toFixed(2)} GiB`
          : (zh ? "该位置不存在或不可写。" : "This location is missing or not writable."),
      );
    } catch {
      setDestinationResult(zh ? "无法测试该备份位置。" : "The backup folder could not be tested.");
    } finally {
      setBackupBusy(false);
    }
  }

  async function retryBackup() {
    setBackupBusy(true);
    try {
      const result = await api.createBackup(settings.auto_backup_destination.trim() || undefined);
      showToast(result.warning || (zh ? "加密备份已创建" : "Encrypted backup created"), result.warning ? "error" : "info");
      notifyStatusChanged();
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
      notifyStatusChanged();
    } finally {
      setBackupBusy(false);
    }
  }

  async function openRecoveryKitRestore() {
    try {
      await api.lock();
    } catch {
      // Clearing the renderer credential is still the safe fallback.
    }
    clearToken();
    window.location.reload();
  }

  if (loading) return <div className="loading-state">{zh ? "加载个人设置…" : "Loading personal settings…"}</div>;

  return (
    <>
      <section className="settings-section" aria-labelledby="personal-security-heading">
        <h3 id="personal-security-heading" className="section-title">
          {zh ? "自动锁定与自动备份" : "Auto-lock and automatic backup"}
        </h3>
        <form onSubmit={saveSettings}>
          <div className="field">
            <label className="field-label" htmlFor="lock-after">
              {zh ? "自动锁定时间" : "Auto-lock after"}
            </label>
            <select
              id="lock-after"
              value={settings.lock_after_seconds}
              onChange={(e) => setSettings({ ...settings, lock_after_seconds: Number(e.target.value) })}
            >
              <option value={60}>{zh ? "1 分钟" : "1 minute"}</option>
              <option value={300}>{zh ? "5 分钟" : "5 minutes"}</option>
              <option value={900}>{zh ? "15 分钟" : "15 minutes"}</option>
              <option value={1800}>{zh ? "30 分钟" : "30 minutes"}</option>
              <option value={3600}>{zh ? "60 分钟" : "60 minutes"}</option>
            </select>
          </div>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={settings.auto_backup_enabled}
              onChange={(e) => setSettings({ ...settings, auto_backup_enabled: e.target.checked })}
            />
            <span>{zh ? "应用解锁期间自动创建加密备份" : "Create encrypted backups while the app is unlocked"}</span>
          </label>
          <p className="field-hint">
            {zh
              ? "选择 OneDrive、Dropbox 或 NAS 的同步目录可形成异地副本；任务只会在应用打开且已解锁时运行。"
              : "Choose a synced OneDrive, Dropbox, or NAS folder for an off-device copy. Jobs run only while the app is open and unlocked."}
          </p>
          {settings.auto_backup_enabled && (
            <>
              <div className="field">
                <label className="field-label" htmlFor="backup-interval">
                  {zh ? "备份间隔（小时）" : "Backup interval (hours)"}
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
                label={zh ? "备份目录" : "Backup folder"}
                mode="directory"
                value={settings.auto_backup_destination}
                onChange={(auto_backup_destination) => setSettings({ ...settings, auto_backup_destination })}
                placeholder={zh ? "例如 D:\\OneDrive\\VaultBackups" : "For example D:\\OneDrive\\VaultBackups"}
              />
              <div className="button-row">
                <button className="secondary" type="button" onClick={() => void testDestination()} disabled={backupBusy}>
                  {zh ? "测试备份位置" : "Test backup location"}
                </button>
                <button className="secondary" type="button" onClick={() => void retryBackup()} disabled={backupBusy}>
                  {settings.backup_status?.last_error_summary ? (zh ? "立即重试" : "Retry now") : (zh ? "立即备份" : "Back up now")}
                </button>
              </div>
              {destinationResult && <p className="field-hint" role="status">{destinationResult}</p>}
            </>
          )}
          <button className="secondary" type="submit" disabled={saving}>
            {saving ? (zh ? "保存中…" : "Saving…") : (zh ? "保存个人设置" : "Save personal settings")}
          </button>
        </form>
      </section>

      <section className="settings-section" aria-labelledby="transfer-heading">
        <h3 id="transfer-heading" className="section-title">{zh ? "导入与导出" : "Import and export"}</h3>
        <p className="field-hint">
          {zh ? "明文导出仅用于短期迁移，不是备份。JSON 保留本地扩展与附件；CSV 不包含附件。" : "Plaintext export is a short-lived migration file, not a backup. JSON preserves local extensions and attachments; CSV excludes attachments."}
        </p>
        <div className="button-row">
          <button className="secondary" type="button" onClick={() => setPendingExport("json")}>JSON</button>
          <button className="secondary" type="button" onClick={() => setPendingExport("csv")}>CSV</button>
        </div>
        <ImportWizard />
      </section>

      <section className="settings-section" aria-labelledby="recovery-heading">
        <h3 id="recovery-heading" className="section-title">{zh ? "紧急恢复包" : "Emergency recovery kit"}</h3>
        <p className="field-hint">
          {zh
            ? "紧急恢复包用于主密码丢失或迁移恢复；它不同于日常加密备份。请将恢复码离线保存，并与恢复包文件分开。"
            : "An emergency kit is for a lost master password or migration; it is different from an everyday encrypted backup. Keep its offline code separate from the kit file."}
        </p>
        <div className="button-row">
          <button className="secondary" type="button" onClick={generateRecoveryCode}>
            {recoveryCode
              ? (zh ? "重新生成恢复码" : "Generate a new recovery code")
              : (zh ? "创建恢复包" : "Create recovery kit")}
          </button>
          <button className="secondary" type="button" onClick={() => void openRecoveryKitRestore()}>
            {zh ? "从恢复包恢复" : "Restore from recovery kit"}
          </button>
        </div>
        {recoveryCode && (
          <>
            <div className="field">
              <label className="field-label" htmlFor="recovery-code">{zh ? "恢复码（请立即离线记录）" : "Recovery code (record offline now)"}</label>
              <input id="recovery-code" value={recoveryCode} readOnly />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="recovery-confirm">{zh ? "重新输入恢复码以确认" : "Re-enter recovery code to confirm"}</label>
              <input id="recovery-confirm" value={recoveryConfirm} onChange={(e) => setRecoveryConfirm(e.target.value)} autoComplete="off" />
            </div>
            <PathPicker
              id="recovery-destination"
              label={zh ? "恢复包目录（建议 U 盘或其他位置）" : "Recovery-kit folder (prefer USB or another location)"}
              mode="directory"
              value={recoveryDestination}
              onChange={setRecoveryDestination}
            />
            <button className="secondary" type="button" onClick={createRecoveryKit}>
              {zh ? "创建恢复包" : "Create recovery kit"}
            </button>
          </>
        )}
      </section>

      <ConfirmDialog
        open={pendingExport !== null}
        idPrefix="plaintext-export-confirm"
        title={zh ? "导出明文迁移文件？" : "Export a plaintext migration file?"}
        message={zh ? "文件将包含明文密码。请仅短暂保存，导入后立即删除；它不能替代加密备份。" : "The file will contain plaintext passwords. Keep it only briefly and delete it after import; it does not replace an encrypted backup."}
        confirmLabel={zh ? "继续导出" : "Continue export"}
        cancelLabel={zh ? "取消" : "Cancel"}
        variant="danger"
        onConfirm={() => pendingExport && void exportVault(pendingExport)}
        onCancel={() => setPendingExport(null)}
      />

    </>
  );
}
