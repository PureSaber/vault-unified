import { useTaskLifetime } from "./useTaskLifetime";
import { backupMessages } from "../i18n/backup-messages";
import { useCallback, useEffect, useRef, useState } from "react";
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

export default function BackupCenter({ onDirtyChange, onSavingChange }: { onDirtyChange?: (value: boolean) => void; onSavingChange?: (value: boolean) => void }) {
  const { locale } = useI18n();
  const text = backupMessages[locale];
  const alive = useTaskLifetime();
  const { showToast: publishToast } = useToast();
  const showToast = (message: string, type?: "success" | "error" | "info") => { if (alive.current) publishToast(message, type); };
  const [summary, setSummary] = useState<BackupSummary | null>(null);
  const [destination, setDestination] = useState("");
  const [restorePassword, setRestorePassword] = useState("");
  const [policy, setPolicy] = useState(defaultPolicy);
  const [plan, setPlan] = useState<BackupPruneResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [restorePlan, setRestorePlan] = useState<BackupRestorePreview | null>(null);
  const activeRestoreToken = useRef<string | null>(null);
  useEffect(() => () => { if (activeRestoreToken.current) void api.cancelBackupRestore(activeRestoreToken.current).catch(() => {}); }, []);
  const [confirmCleanup, setConfirmCleanup] = useState(false);

  useEffect(() => { onDirtyChange?.(Boolean(destination || restorePassword || restorePlan || plan) || JSON.stringify(policy) !== JSON.stringify(defaultPolicy)); onSavingChange?.(busy !== null); });
  useEffect(() => () => { onDirtyChange?.(false); onSavingChange?.(false); }, [onDirtyChange, onSavingChange]);
  const load = useCallback(async () => {
    setBusy("load");
    setError("");
    try {
      const next = await api.backups();
      if (alive.current) setSummary(next);
    } catch (err) {
      if (alive.current) setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      if (alive.current) setBusy(null);
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
      if (!alive.current) return;
      setSummary(result);
      setPlan(null);
      showToast(result.warning || text.created, result.warning ? "error" : "info");
      notifyStatusChanged();
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      if (alive.current) setError(message);
      showToast(message, "error");
      notifyStatusChanged();
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function togglePin(record: BackupRecord) {
    setBusy(`pin:${record.path}`);
    setError("");
    try {
      const result = await api.pinBackup(record.path, !record.pinned);
      if (!alive.current) return;
      setSummary(result);
      setPlan(null);
      showToast(text.saved);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      if (alive.current) setError(message);
      showToast(message, "error");
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function previewCleanup() {
    setBusy("preview");
    setError("");
    try {
      const result = await api.pruneBackups(false, policy);
      if (!alive.current) return;
      setPlan(result);
      setSummary(result.summary);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      if (alive.current) setError(message);
      showToast(message, "error");
    } finally {
      if (alive.current) setBusy(null);
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
      if (!alive.current) return;
      setPlan(result);
      setSummary(result.summary);
      showToast(text.pruned);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      if (alive.current) setError(message);
      showToast(message, "error");
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function previewRestore(record: BackupRecord) {
    setBusy(`restore-preview:${record.path}`);
    setError("");
    try {
      const preview = await api.previewBackupRestore(record.path, restorePassword);
      if (!alive.current) { void api.cancelBackupRestore(preview.preview_token).catch(() => {}); return; }
      activeRestoreToken.current = preview.preview_token;
      setRestorePlan(preview);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      if (alive.current) setError(message);
      showToast(message, "error");
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function restore() {
    if (!restorePlan) return;
    const plan = restorePlan;
    activeRestoreToken.current = null;
    setRestorePlan(null);
    setBusy(`restore:${plan.backup.path}`);
    setError("");
    try {
      await api.applyBackupRestore(plan.preview_token, restorePassword, true);
      if (!alive.current) return;
      showToast(text.restoreDone);
      setRestorePassword("");
      clearToken();
      window.location.reload();
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      if (alive.current) setError(message);
      showToast(message, "error");
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function verifyLatest() {
    setBusy("verify");
    setError("");
    try {
      const result = await api.verifyBackup();
      if (!alive.current) return;
      showToast(result.warning || text.verificationPassed, result.warning ? "error" : "info");
      await load();
      notifyStatusChanged();
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      if (alive.current) setError(message);
      showToast(message, "error");
      notifyStatusChanged();
    } finally {
      if (alive.current) setBusy(null);
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
        cancelLabel={text.cancel}
        variant="danger"
        onConfirm={() => void restore()}
        onCancel={() => {
          if (restorePlan) void api.cancelBackupRestore(restorePlan.preview_token).catch(() => undefined);
          activeRestoreToken.current = null;
          setRestorePlan(null);
          setRestorePassword("");
        }}
      />
      <ConfirmDialog
        open={confirmCleanup}
        idPrefix="backup-cleanup-confirm"
        title={text.cleanupTitle}
        message={text.applyConfirm}
        confirmLabel={text.apply}
        cancelLabel={text.cancel}
        variant="danger"
        onConfirm={() => void applyCleanup()}
        onCancel={() => setConfirmCleanup(false)}
      />
    </section>
  );
}
