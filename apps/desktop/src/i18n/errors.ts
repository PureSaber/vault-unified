import { ApiError } from "../api/client";
import type { Locale } from "./index";

/** Preserve distinct recovery/conflict errors; do not collapse every 4xx result. */
export function authenticationError(error: unknown, locale: Locale): string {
  const zh = locale === "zh";
  const text = String(error).replace(/^Error:\s*/, "");
  if (/Failed to fetch|NetworkError|Load failed/.test(text)) {
    return zh ? "无法连接后台服务，请重试或重新打开应用。" : "Could not connect to the local service. Retry or reopen the app.";
  }
  if (error instanceof ApiError && error.status === 401 && error.path === "/auth/unlock") {
    return zh ? "主密码不正确，或这个保险库文件无法打开。请检查后重试。" : "The master password is incorrect, or this vault could not be opened. Check and try again.";
  }
  const known: Record<string, [string, string]> = {
    "Invalid password or vault": ["主密码不正确，或这个保险库文件无法打开。", "The master password is incorrect, or this vault could not be opened."],
    "Master password confirmation does not match": ["两次输入的主密码不一致。", "The master-password confirmation does not match."],
  };
  return known[text]?.[zh ? 0 : 1] ?? text;
}

export function maintenanceMessage(code: string, fallback: string, locale: Locale): string {
  const [kind, count] = code.split(":");
  const zh = locale === "zh";
  const messages: Record<string, [string, string]> = {
    "trash-cleanup-failed": ["回收站清理未完成，请重新打开保险库后重试。", "Trash cleanup failed. Reopen the vault and retry."],
    "scheduled-backup": ["已完成自动加密备份，可在安全与恢复中查看。", "Automatic encrypted backup completed. View it in Security & recovery."],
    "scheduled-backup-status-error": ["加密备份已创建，但计划状态未能保存。请在安全与恢复中检查。", "An encrypted backup was created, but its schedule status could not be saved. Check Security & recovery."],
    "scheduled-backup-error": ["自动备份未完成，请在安全与恢复中检查备份位置。", "Automatic backup failed. Check the destination in Security & recovery."],
    "sync-conflicts": [`有 ${count} 处同步冲突需要处理。`, `${count} synchronization conflicts need review.`],
  };
  return messages[kind]?.[zh ? 0 : 1] ?? fallback;
}
