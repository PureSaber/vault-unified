import TaskNavigation from "../components/TaskNavigation";
import DiscardChanges from "../components/DiscardChanges";
import { useCallback, useEffect, useState, useRef } from "react";
import { api, type BackupSummary, type PersonalSettings, type Entry } from "../api/client";
import BackupCenter from "../components/BackupCenter";
import PersonalCenter from "../components/PersonalCenter";
import PayloadUpgrade from "../components/PayloadUpgrade";
import { useI18n } from "../i18n";
import PasswordHealth from "../components/PasswordHealth";
import { backupHealth, withStoredBackupStatus } from "../components/backup-health";

const SECURITY_STATUS_EVENT = "vault-security-status-changed";

export function notifySecurityStatusChanged() {
  window.dispatchEvent(new Event(SECURITY_STATUS_EVENT));
}

function displayTime(value: string, locale: string, fallback: string) {
  if (!value) return fallback;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? fallback : parsed.toLocaleString(locale === "zh" ? "zh-CN" : "en-US");
}

export default function SecurityRecovery({ onOpen, onDirtyChange, onSavingChange, task, onTaskChange: setTask }: {
  task: string; onTaskChange: (value: string) => void;
  onOpen: (entry: Entry) => void; onDirtyChange: (value: boolean) => void; onSavingChange: (value: boolean) => void;
}) {
  const [pendingTask, setPendingTask] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onSavingChange(busy); }, [busy, onSavingChange]);
  useEffect(() => () => { onDirtyChange(false); onSavingChange(false); }, [onDirtyChange, onSavingChange]);
  const navigate = (next: string) => {
    if (next === task || busy) return;
    if (dirty) { setPendingTask(next); return; }
    setTask(next);
  };
  useEffect(() => { content.current?.focus(); }, [task]);
  const { locale, t } = useI18n();
  const zh = locale === "zh";
  const [settings, setSettings] = useState<PersonalSettings | null>(null);
  const [backups, setBackups] = useState<BackupSummary | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [nextSettings, nextBackups] = await Promise.all([
        api.getPersonalSettings(),
        api.backups(),
      ]);
      setSettings(nextSettings);
      setBackups(withStoredBackupStatus(nextBackups, nextSettings));
    } catch {
      setError(t("SecurityRecovery.securityAndBackupStatusCouldNotBe"));
    }
  }, [zh]);

  useEffect(() => {
    void load();
    window.addEventListener(SECURITY_STATUS_EVENT, load);
    return () => window.removeEventListener(SECURITY_STATUS_EVENT, load);
  }, [load]);

  const health = backups?.health;
  const noValue = t("SecurityRecovery.notSet");
  const never = t("SecurityRecovery.noBackupYet");
  const verification = health?.last_verification_status === "passed"
    ? (t("SecurityRecovery.passed"))
    : health?.last_verification_status === "failed"
      ? (t("SecurityRecovery.failed"))
      : (t("SecurityRecovery.notVerified"));

  return (
    <div className="card">
      <h2>{t("SecurityRecovery.securityRecovery")}</h2>
      <p className="page-lead">
        {t("SecurityRecovery.reviewProtectionStatusFirstThenChangeSettings")}
      </p>
      <TaskNavigation label={t("SecurityRecovery.securityAndRecoverySections")} current={task} busy={busy} onChange={navigate}
        items={[
          { id: "overview", label: t("SecurityRecovery.overview") },
          { id: "health", label: t("SecurityRecovery.passwordCheck") },
          { id: "protection", label: t("SecurityRecovery.automaticProtection") },
          { id: "backups", label: t("SecurityRecovery.backups") },
          { id: "recovery", label: t("SecurityRecovery.recovery") },
          { id: "transfer", label: t("SecurityRecovery.importAndExport") },
        ]} />
      <div ref={content} className="task-content" tabIndex={-1}>
      {task === "overview" && <>
      <section className={`security-summary card ${backups ? backupHealth(backups).failed ? "security-error" : backupHealth(backups).hasBackup ? "security-ready" : "security-warning" : ""}`} aria-labelledby="security-status-heading">
        <h3 id="security-status-heading" className="section-title">{t("SecurityRecovery.currentProtectionStatus")}</h3>
        <dl className="status-grid security-status-grid">
          <div className="status-row"><dt>{t("SecurityRecovery.vault")}</dt><dd>{t("SecurityRecovery.encrypted")}</dd></div>
          <div className="status-row"><dt>{t("SecurityRecovery.autoLock")}</dt><dd>{settings ? `${Math.round(settings.lock_after_seconds / 60)} ${t("SecurityRecovery.minutes")}` : "…"}</dd></div>
          <div className="status-row"><dt>{t("SecurityRecovery.lastSuccessfulBackup")}</dt><dd>{displayTime(backups ? backupHealth(backups).lastSuccess : "", locale, never)}</dd></div>
          <div className="status-row"><dt>{t("SecurityRecovery.automaticBackupLocation")}</dt><dd className="path-break">{health?.backup_location || noValue}</dd></div>
          <div className={`status-row${health?.last_error_summary ? " status-row-danger" : ""}`}><dt>{t("SecurityRecovery.latestBackupError")}</dt><dd>{health?.last_error_summary || (t("SecurityRecovery.none"))}</dd></div>
          <div className="status-row"><dt>{t("SecurityRecovery.nextAutomaticBackup")}</dt><dd>{health?.auto_backup_enabled ? `${displayTime(health.next_eligible_at, locale, t("SecurityRecovery.asSoonAsTheAppIsUnlocked"))} · ${t("SecurityRecovery.runsOnlyWhileUnlocked")}` : (t("SecurityRecovery.notEnabled"))}</dd></div>
          <div className="status-row"><dt>{t("SecurityRecovery.latestBackupVerification")}</dt><dd>{verification}{health?.last_verification_at ? ` · ${displayTime(health.last_verification_at, locale, "")}` : ""}</dd></div>
          <div className="status-row"><dt>{t("SecurityRecovery.recoveryKit")}</dt><dd>{health?.recovery_kit_created_at ? `${t("SecurityRecovery.created")} · ${displayTime(health.recovery_kit_created_at, locale, "")}` : (t("SecurityRecovery.notCreated"))}</dd></div>
        </dl>
        {backups && !backupHealth(backups).hasBackup && <p role="status">{t("SecurityRecovery.noBackupHasBeenCreatedByYou")}</p>}
        {error && <div className="error" role="alert">{error}</div>}
        <button type="button" className="secondary" onClick={() => void load()}>{t("SecurityRecovery.refreshStatus")}</button>
      </section>
      <PayloadUpgrade onDirtyChange={setDirty} onSavingChange={setBusy} />
      </>}
      {task === "health" && <PasswordHealth onOpen={onOpen} />}
      {["protection", "recovery", "transfer"].includes(task) && <PersonalCenter key={task} section={task} onDirtyChange={setDirty} onSavingChange={setBusy} />}
      {task === "backups" && <BackupCenter onDirtyChange={setDirty} onSavingChange={setBusy} />}
      </div>
      <DiscardChanges open={pendingTask !== null} onCancel={() => setPendingTask(null)} onConfirm={() => {
        if (pendingTask) { setDirty(false); setTask(pendingTask); setPendingTask(null); }
      }} />
    </div>
  );
}
