import { useCallback, useEffect, useState } from "react";
import { api, type BackupSummary, type PersonalSettings } from "../api/client";
import BackupCenter from "../components/BackupCenter";
import PersonalCenter from "../components/PersonalCenter";
import { useI18n } from "../i18n";

const SECURITY_STATUS_EVENT = "vault-security-status-changed";

export function notifySecurityStatusChanged() {
  window.dispatchEvent(new Event(SECURITY_STATUS_EVENT));
}

function displayTime(value: string, locale: string, fallback: string) {
  if (!value) return fallback;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? fallback : parsed.toLocaleString(locale === "zh" ? "zh-CN" : "en-US");
}

export default function SecurityRecovery() {
  const { locale } = useI18n();
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
      setBackups(nextBackups);
    } catch {
      setError(zh ? "无法读取安全与备份状态，请重试。" : "Security and backup status could not be loaded. Try again.");
    }
  }, [zh]);

  useEffect(() => {
    void load();
    window.addEventListener(SECURITY_STATUS_EVENT, load);
    return () => window.removeEventListener(SECURITY_STATUS_EVENT, load);
  }, [load]);

  const health = backups?.health;
  const noValue = zh ? "尚未设置" : "Not set";
  const never = zh ? "尚未备份" : "No backup yet";
  const verification = health?.last_verification_status === "passed"
    ? (zh ? "通过" : "Passed")
    : health?.last_verification_status === "failed"
      ? (zh ? "失败" : "Failed")
      : (zh ? "未验证" : "Not verified");

  return (
    <div className="card">
      <h2>{zh ? "安全与恢复" : "Security & recovery"}</h2>
      <p className="page-lead">
        {zh ? "先查看保护状态，再按需要调整设置或执行恢复。" : "Review protection status first, then change settings or start a recovery only when needed."}
      </p>
      <section className="security-summary card" aria-labelledby="security-status-heading">
        <h3 id="security-status-heading" className="section-title">{zh ? "当前保护状态" : "Current protection status"}</h3>
        <dl className="status-grid security-status-grid">
          <div className="status-row"><dt>{zh ? "保险库" : "Vault"}</dt><dd>{zh ? "已加密" : "Encrypted"}</dd></div>
          <div className="status-row"><dt>{zh ? "自动锁定" : "Auto-lock"}</dt><dd>{settings ? `${Math.round(settings.lock_after_seconds / 60)} ${zh ? "分钟" : "minutes"}` : "…"}</dd></div>
          <div className="status-row"><dt>{zh ? "最近一次成功备份" : "Last successful backup"}</dt><dd>{displayTime(health?.last_success_at || "", locale, never)}</dd></div>
          <div className="status-row"><dt>{zh ? "备份位置" : "Backup location"}</dt><dd className="path-break">{health?.backup_location || noValue}</dd></div>
          <div className={`status-row${health?.last_error_summary ? " status-row-danger" : ""}`}><dt>{zh ? "最近一次备份错误" : "Latest backup error"}</dt><dd>{health?.last_error_summary || (zh ? "没有" : "None")}</dd></div>
          <div className="status-row"><dt>{zh ? "下次预计备份" : "Next eligible backup"}</dt><dd>{health?.auto_backup_enabled ? `${displayTime(health.next_eligible_at, locale, zh ? "应用解锁后尽快执行" : "As soon as the app is unlocked")} · ${zh ? "仅在应用解锁时执行" : "runs only while unlocked"}` : (zh ? "未启用" : "Not enabled")}</dd></div>
          <div className="status-row"><dt>{zh ? "最新备份验证" : "Latest backup verification"}</dt><dd>{verification}{health?.last_verification_at ? ` · ${displayTime(health.last_verification_at, locale, "")}` : ""}</dd></div>
          <div className="status-row"><dt>{zh ? "恢复包" : "Recovery kit"}</dt><dd>{health?.recovery_kit_created_at ? `${zh ? "已创建" : "Created"} · ${displayTime(health.recovery_kit_created_at, locale, "")}` : (zh ? "尚未创建" : "Not created")}</dd></div>
        </dl>
        {error && <div className="error" role="alert">{error}</div>}
        <button type="button" className="secondary" onClick={() => void load()}>{zh ? "刷新状态" : "Refresh status"}</button>
      </section>
      <PersonalCenter />
      <BackupCenter />
    </div>
  );
}
