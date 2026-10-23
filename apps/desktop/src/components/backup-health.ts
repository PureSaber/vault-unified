import type { BackupSummary } from "../api/client";

/** Only backups the user starts or schedules record `last_success_at`. Atomic
 * write copies and the automatic safety copies made before imports, updates and
 * sync joins (kind `manual`, default folder) protect operations, not the loss
 * of this vault or device, so they do not count. */
export function backupHealth(summary: BackupSummary) {
  const lastSuccess = summary.health.last_success_at || "";
  return {
    hasBackup: Boolean(lastSuccess),
    configured: Boolean(summary.health.auto_backup_enabled && summary.health.backup_location),
    failed: Boolean(summary.health.last_error_summary),
    lastSuccess,
  };
}
