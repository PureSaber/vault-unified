import { useCallback, useEffect, useState } from "react";
import {
  api,
  clearToken,
  type BackupPruneResult,
  type BackupRecord,
  type BackupSummary,
} from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import PathPicker from "./PathPicker";

const copy = {
  zh: {
    title: "备份与恢复",
    hint: "加密备份用于电脑损坏、文件丢失或误操作后的日常恢复。",
    manageHistory: "管理历史备份",
    hideHistory: "收起历史备份",
    loading: "正在检查备份…",
    destination: "手动备份目录（留空使用默认位置）",
    create: "立即创建加密备份",
    creating: "正在创建…",
    total: "备份总数",
    storage: "占用空间",
    verified: "已验证",
    pinned: "已固定",
    manual: "手动备份",
    atomic: "自动恢复备份",
    unreadable: "当前凭据无法验证",
    pin: "固定",
    unpin: "取消固定",
    restorePassword: "旧备份密码（当前密码可解密时留空）",
    restore: "恢复这个备份",
    restoring: "正在恢复…",
    restoreConfirm: "恢复会替换当前密码库，但当前版本会先被原子备份保留。确认继续？",
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
    created: "加密备份已创建",
    saved: "备份固定状态已更新",
    pruned: "备份清理已完成",
    path: "路径",
    format: "格式",
    modified: "时间",
    defaultDestination: "默认目录",
  },
  en: {
    title: "Backup and restore",
    hint: "Encrypted backups support everyday recovery after computer failure, file loss, or mistakes.",
    manageHistory: "Manage backup history",
    hideHistory: "Collapse backup history",
    loading: "Checking backups…",
    destination: "Manual backup directory (leave blank for the default)",
    create: "Create encrypted backup now",
    creating: "Creating…",
    total: "Backups",
    storage: "Storage",
    verified: "Verified",
    pinned: "Pinned",
    manual: "Manual backup",
    atomic: "Automatic recovery backup",
    unreadable: "Not verified with the current credential",
    pin: "Pin",
    unpin: "Unpin",
    restorePassword: "Old backup password (leave blank when the current credential works)",
    restore: "Restore this backup",
    restoring: "Restoring…",
    restoreConfirm: "Restore replaces the active vault, but its current bytes will first be retained as an atomic backup. Continue?",
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
    created: "Encrypted backup created",
    saved: "Backup pin state updated",
    pruned: "Backup cleanup completed",
    path: "Path",
    format: "Format",
    modified: "Modified",
    defaultDestination: "Default directory",
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
    load();
  }, [load]);

  async function createBackup() {
    setBusy("create");
    setError("");
    try {
      const result = await api.createBackup(destination.trim() || undefined);
      setSummary(result);
      setPlan(null);
      showToast(text.created);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
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
    if (!window.confirm(text.applyConfirm)) return;
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

  async function restore(record: BackupRecord) {
    if (!window.confirm(text.restoreConfirm)) return;
    setBusy(`restore:${record.path}`);
    setError("");
    try {
      await api.restoreBackup(record.path, restorePassword, true);
      showToast(text.restoreDone);
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
                    <strong>{text.modified}:</strong> {new Date(record.modified_at).toLocaleString()} · {formatBytes(record.size)} · SHA-256 {record.sha256.slice(0, 12)}…
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
                      onClick={() => restore(record)}
                    >
                      {busy === `restore:${record.path}` ? text.restoring : text.restore}
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
                onClick={applyCleanup}
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
    </section>
  );
}
