import { useCallback, useEffect, useState } from "react";
import {
  api,
  clearToken,
  type BackupPruneResult,
  type BackupRecord,
  type BackupRestorePreview,
  type BackupSummary,
} from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import PathPicker from "./PathPicker";
import ConfirmDialog from "./ConfirmDialog";

function notifyStatusChanged() {
  window.dispatchEvent(new Event("vault-security-status-changed"));
}

const copy = {
  zh: {
    title: "一次性备份与恢复",
    hint: "在这里立即创建一份加密备份，不会保存这个临时目录，也不会启用上方的自动备份计划。加密备份可用于电脑损坏、文件丢失或误操作后的日常恢复。",
    manageHistory: "管理历史备份",
    hideHistory: "收起历史备份",
    loading: "正在检查备份…",
    destination: "本次备份的文件夹（不启用自动备份）",
    create: "创建一次性加密备份",
    creating: "正在创建…",
    total: "备份总数",
    storage: "占用空间",
    verified: "已验证",
    pinned: "已固定",
    manual: "一次性手动备份",
    atomic: "自动恢复备份",
    unreadable: "当前凭据无法验证",
    pin: "固定",
    unpin: "取消固定",
    restorePassword: "旧备份密码（当前密码可解密时留空）",
    restore: "恢复这个备份",
    previewRestore: "预览恢复影响",
    restoring: "正在恢复…",
    restoreDone: "恢复完成，需要重新解锁。",
    retention: "备份保留策略",
    newest: "保留最近版本数",
    daily: "每日保留天数",
    weekly: "每周保留周数",
    preview: "预览清理",
    previewing: "正在预览…",
    apply: "执行清理",
    applying: "正在清理…",
    applyConfirm: "只删除预览中列出的备份。确认执行？",
    candidates: "可删除",
    reclaim: "预计释放",
    none: "还没有可管理的备份。修改密码库后会产生自动恢复备份，也可以立即创建手动备份。",
    created: "一次性加密备份已创建；自动备份设置没有改变",
    saved: "备份固定状态已更新",
    pruned: "备份清理已完成",
    path: "路径",
    format: "格式",
    modified: "时间",
    defaultDestination: "默认目录",
    verifyLatest: "验证最新备份",
    verifying: "正在验证…",
    verificationPassed: "最新备份已通过认证和解析，当前保险库未被修改。",
    retry: "立即重试",
    restoreFromBackup: "从备份恢复",
  },
  en: {
    title: "One-time backup and restore",
    hint: "Create an encrypted backup now without remembering this temporary folder or enabling the automatic schedule above. Encrypted backups support everyday recovery after computer failure, file loss, or mistakes.",
    manageHistory: "Manage backup history",
    hideHistory: "Collapse backup history",
    loading: "Checking backups…",
    destination: "Folder for this backup (does not enable automatic backups)",
    create: "Create one-time encrypted backup",
    creating: "Creating…",
    total: "Backups",
    storage: "Storage",
    verified: "Verified",
    pinned: "Pinned",
    manual: "One-time manual backup",
    atomic: "Automatic recovery backup",
    unreadable: "Not verified with the current credential",
    pin: "Pin",
    unpin: "Unpin",
    restorePassword: "Old backup password (leave blank when the current credential works)",
    restore: "Restore this backup",
    previewRestore: "Preview restore impact",
    restoring: "Restoring…",
    restoreDone: "Restore completed. Unlock the vault again.",
    retention: "Backup retention policy",
    newest: "Newest versions to keep",
    daily: "Daily retention days",
    weekly: "Weekly retention weeks",
    preview: "Preview cleanup",
    previewing: "Previewing…",
    apply: "Apply cleanup",
    applying: "Cleaning…",
    applyConfirm: "Only backups shown in the preview will be deleted. Continue?",
    candidates: "Candidates",
    reclaim: "Estimated reclaim",
    none: "No manageable backups yet. Editing the vault creates automatic recovery backups, or create a manual backup now.",
    created: "One-time encrypted backup created; automatic-backup settings were not changed",
    saved: "Backup pin state updated",
    pruned: "Backup cleanup completed",
    path: "Path",
    format: "Format",
    modified: "Modified",
    defaultDestination: "Default directory",
    verifyLatest: "Verify latest backup",
    verifying: "Verifying…",
    verificationPassed: "The latest backup passed authentication and parsing. The active vault was not changed.",
    retry: "Retry now",
    restoreFromBackup: "Restore from backup",
  },
} as const;

const defaultPolicy = {
  newest_count: 10,
  daily_days: 30,
  weekly_weeks: 12,
};

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
  }
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
}

export default function BackupCenter() {
  const { locale } = useI18n();
  const text = copy[locale];
  const { showToast } = useToast();
  const [summary, setSummary] = useState<BackupSummary | null>(null);
  const [destination, setDestination] = useState("");
  const [restorePassword, setRestorePassword] = useState("");
  const [policy, setPolicy] = useState(defaultPolicy);
  const [plan, setPlan] = useState<BackupPruneResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [restorePlan, setRestorePlan] = useState<BackupRestorePreview | null>(null);
  const [confirmCleanup, setConfirmCleanup] = useState(false);

  const load = useCallback(async () => {
    setBusy("load");
    setError("");
    try {
      setSummary(await api.backups());
    } catch (err) {
      setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    void load();
    window.addEventListener("vault-security-status-changed", load);
    return () => window.removeEventListener("vault-security-status-changed", load);
  }, [load]);

  async function createBackup() {
    setBusy("create");
    setError("");
    try {
      const result = await api.createBackup(destination.trim() || undefined);
      setSummary(result);
      setPlan(null);
      showToast(result.warning || text.created, result.warning ? "error" : "info");
      notifyStatusChanged();
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
      notifyStatusChanged();
    } finally {
      setBusy(null);
    }
  }

  async function togglePin(record: BackupRecord) {
    setBusy(`pin:${record.path}`);
    setError("");
    try {
      const result = await api.pinBackup(record.path, !record.pinned);
      setSummary(result);
      setPlan(null);
      showToast(text.saved);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function previewCleanup() {
    setBusy("preview");
    setError("");
    try {
      const result = await api.pruneBackups(false, policy);
      setPlan(result);
      setSummary(result.summary);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function applyCleanup() {
    if (!plan || !plan.preview_token || plan.delete_count === 0) return;
    setConfirmCleanup(false);
    setBusy("apply");
    setError("");
    try {
      const result = await api.pruneBackups(
        true,
        plan.policy,
        plan.preview_token
      );
      setPlan(result);
      setSummary(result.summary);
      showToast(text.pruned);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function previewRestore(record: BackupRecord) {
    setBusy(`restore-preview:${record.path}`);
    setError("");
    try {
      setRestorePlan(await api.previewBackupRestore(record.path, restorePassword));
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function restore() {
    if (!restorePlan) return;
    const plan = restorePlan;
    setRestorePlan(null);
    setBusy(`restore:${plan.backup.path}`);
    setError("");
    try {
      await api.applyBackupRestore(plan.preview_token, restorePassword, true);
      showToast(text.restoreDone);
      setRestorePassword("");
      clearToken();
      window.location.reload();
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function verifyLatest() {
    setBusy("verify");
    setError("");
    try {
      const result = await api.verifyBackup();
      showToast(result.warning || text.verificationPassed, result.warning ? "error" : "info");
      await load();
      notifyStatusChanged();
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
      notifyStatusChanged();
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="settings-section" aria-labelledby="backup-center-heading">
      <h3 id="backup-center-heading" className="section-title">
        {text.title}
      </h3>
      <p className="field-hint">{text.hint}</p>

      {busy === "load" && !summary ? (
        <div className="loading-state">{text.loading}</div>
      ) : summary ? (
        <>
          <dl className="status-grid">
            <div className="status-row"><dt>{text.total}</dt><dd>{summary.count}</dd></div>
            <div className="status-row"><dt>{text.storage}</dt><dd>{formatBytes(summary.total_bytes)}</dd></div>
          </dl>

          <PathPicker
            id="backup-destination"
            label={text.destination}
            mode="directory"
            value={destination}
            onChange={setDestination}
            placeholder={summary.default_destination}
          />
          <button
            type="button"
            className="primary"
            disabled={busy !== null}
            onClick={createBackup}
          >
            {busy === "create" ? text.creating : text.create}
          </button>
          <div className="button-row">
            <button type="button" className="secondary" disabled={busy !== null || summary.backups.length === 0} onClick={() => void verifyLatest()}>
              {busy === "verify" ? text.verifying : text.verifyLatest}
            </button>
            <button type="button" className="secondary" disabled={busy !== null || summary.backups.length === 0} onClick={() => setShowHistory(true)}>
              {text.restoreFromBackup}
            </button>
            {summary.health.last_error_summary && (
              <button type="button" className="secondary" disabled={busy !== null} onClick={() => void createBackup()}>{text.retry}</button>
            )}
          </div>

          <div className="button-row">
            <button type="button" className="ghost" onClick={() => setShowHistory((value) => !value)} aria-expanded={showHistory}>
              {showHistory ? text.hideHistory : text.manageHistory}
            </button>
          </div>

          {showHistory && (
            <>
              <dl className="status-grid">
                <div className="status-row"><dt>{text.verified}</dt><dd>{summary.verified_count}</dd></div>
                <div className="status-row"><dt>{text.pinned}</dt><dd>{summary.pinned_count}</dd></div>
              </dl>
              <p className="field-hint">
                {text.defaultDestination}: <span className="mono">{summary.default_destination}</span>
              </p>

          <div className="field" style={{ marginTop: "var(--space-xl)" }}>
            <label className="field-label" htmlFor="backup-old-password">
              {text.restorePassword}
            </label>
            <input
              id="backup-old-password"
              type="password"
              value={restorePassword}
              onChange={(event) => setRestorePassword(event.target.value)}
              autoComplete="off"
            />
          </div>

          {summary.backups.length === 0 ? (
            <div className="empty-state card">
              <p className="empty-state-hint">{text.none}</p>
            </div>
          ) : (
            <div style={{ marginTop: "var(--space-lg)" }}>
              {summary.backups.map((record) => (
                <article className="card" key={record.path} style={{ marginTop: "var(--space-md)" }}>
                  <div className="conflict-header">
                    <strong>{record.kind === "manual" ? text.manual : text.atomic}</strong>
                    <div className="entry-chips">
                      <span className="chip">{record.format}</span>
                      <span className="chip">
                        {record.verified ? text.verified : text.unreadable}
                      </span>
                      {record.pinned && <span className="chip">{text.pinned}</span>}
                    </div>
                  </div>
                  <p className="field-hint mono"><strong>{text.path}:</strong> {record.path}</p>
                  <p className="field-hint">
                    <strong>{text.modified}:</strong> {new Date(record.modified_at).toLocaleString()} · {formatBytes(record.size)} · SHA-256 {record.sha256}
                  </p>
                  <div className="button-row">
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy !== null}
                      onClick={() => togglePin(record)}
                    >
                      {record.pinned ? text.unpin : text.pin}
                    </button>
                    <button
                      type="button"
                      className="danger"
                      disabled={busy !== null}
                      onClick={() => void previewRestore(record)}
                    >
                      {busy === `restore-preview:${record.path}` ? text.restoring : text.previewRestore}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}

          <div className="card" style={{ marginTop: "var(--space-xl)" }}>
            <h4>{text.retention}</h4>
            <div className="field">
              <label className="field-label" htmlFor="retention-newest">{text.newest}</label>
              <input
                id="retention-newest"
                type="number"
                min={0}
                max={1000}
                value={policy.newest_count}
                onChange={(event) => {
                  setPolicy({ ...policy, newest_count: Number(event.target.value) || 0 });
                  setPlan(null);
                }}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="retention-daily">{text.daily}</label>
              <input
                id="retention-daily"
                type="number"
                min={0}
                max={3650}
                value={policy.daily_days}
                onChange={(event) => {
                  setPolicy({ ...policy, daily_days: Number(event.target.value) || 0 });
                  setPlan(null);
                }}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="retention-weekly">{text.weekly}</label>
              <input
                id="retention-weekly"
                type="number"
                min={0}
                max={520}
                value={policy.weekly_weeks}
                onChange={(event) => {
                  setPolicy({ ...policy, weekly_weeks: Number(event.target.value) || 0 });
                  setPlan(null);
                }}
              />
            </div>
            <div className="button-row">
              <button
                type="button"
                className="secondary"
                disabled={busy !== null}
                onClick={previewCleanup}
              >
                {busy === "preview" ? text.previewing : text.preview}
              </button>
              <button
                type="button"
                className="danger"
                disabled={
                  busy !== null ||
                  !plan ||
                  !plan.preview_token ||
                  plan.delete_count === 0
                }
                onClick={() => setConfirmCleanup(true)}
              >
                {busy === "apply" ? text.applying : text.apply}
              </button>
            </div>
            {plan && (
              <dl className="status-grid">
                <div className="status-row"><dt>{text.candidates}</dt><dd>{plan.delete_count}</dd></div>
                <div className="status-row"><dt>{text.reclaim}</dt><dd>{formatBytes(plan.reclaim_bytes)}</dd></div>
              </dl>
            )}
          </div>
            </>
          )}
        </>
      ) : null}

      {error && <div className="error" role="alert">{error}</div>}
      <ConfirmDialog
        open={restorePlan !== null}
        idPrefix="backup-restore-confirm"
        title={text.restore}
        message={restorePlan ? `${text.modified}: ${new Date(restorePlan.backup.modified_at).toLocaleString()} · ${text.path}: ${restorePlan.backup.path} · ${text.format}: ${restorePlan.backup.format}. ${restorePlan.impact}` : ""}
        confirmLabel={text.restore}
        cancelLabel={locale === "zh" ? "取消" : "Cancel"}
        variant="danger"
        onConfirm={() => void restore()}
        onCancel={() => {
          if (restorePlan) void api.cancelBackupRestore(restorePlan.preview_token).catch(() => undefined);
          setRestorePlan(null);
          setRestorePassword("");
        }}
      />
      <ConfirmDialog
        open={confirmCleanup}
        idPrefix="backup-cleanup-confirm"
        title={locale === "zh" ? "执行备份清理？" : "Apply backup cleanup?"}
        message={text.applyConfirm}
        confirmLabel={text.apply}
        cancelLabel={locale === "zh" ? "取消" : "Cancel"}
        variant="danger"
        onConfirm={() => void applyCleanup()}
        onCancel={() => setConfirmCleanup(false)}
      />
    </section>
  );
}
