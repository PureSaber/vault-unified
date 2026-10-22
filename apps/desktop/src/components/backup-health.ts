import type { BackupSummary } from "../api/client";

/** Internal atomic copies protect writes, not loss of the vault/device. */
export function backupHealth(summary: BackupSummary) {
  const recoveryBackups = summary.backups.filter(record => record.kind !== "local_atomic" && record.verified);
  return {
    hasBackup: recoveryBackups.length > 0,
    configured: Boolean(summary.health.auto_backup_enabled && summary.health.backup_location),
    failed: Boolean(summary.health.last_error_summary),
    lastSuccess: recoveryBackups.map(record => record.modified_at).sort().reverse()[0] || "",
  };
}
