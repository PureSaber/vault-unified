import type { BackupSummary, PersonalSettings } from "../api/client";

/** `GET /backups` reports `last_success_at` from the stored status or, when none
 * is stored, from the newest verified file — which includes the atomic copy
 * made by every vault write. Only backups the user starts or schedules write
 * the stored status (`/personal/settings`), so the UI must use that value.
 * Automatic safety copies before imports, updates and sync joins never count. */
export function withStoredBackupStatus(summary: BackupSummary, settings: PersonalSettings): BackupSummary {
  return { ...summary, health: { ...summary.health, last_success_at: settings.backup_status?.last_success_at || "" } };
}

export function backupHealth(summary: BackupSummary) {
  const lastSuccess = summary.health.last_success_at || "";
  return {
    hasBackup: Boolean(lastSuccess),
    configured: Boolean(summary.health.auto_backup_enabled && summary.health.backup_location),
    failed: Boolean(summary.health.last_error_summary),
    lastSuccess,
  };
}
