import { invoke, isTauri } from "@tauri-apps/api/core";

export interface DesktopPreferences { close_to_tray: boolean; shortcut: string; locale: "en" | "zh" }
export interface DesktopStatus { preferences: DesktopPreferences; tray_available: boolean; shortcut_registered: boolean }
export async function desktopStatus(): Promise<DesktopStatus | null> {
  if (!isTauri()) return null;
  try { return await invoke<DesktopStatus>("get_desktop_status"); }
  catch { return null; }
}
export const saveDesktopPreferences = (preferences: DesktopPreferences) => invoke<DesktopStatus>("set_desktop_preferences", { preferences });
export const desktopReady = () => invoke<boolean>("desktop_ready");
export const exitDesktop = () => invoke("exit_desktop");
export function cancelHello() { if (isTauri()) void invoke("cancel_windows_hello").catch(() => {}); }
export function helloError(reason: unknown, zh: boolean): string {
  const key = String(reason);
  if (key.includes("hello_cancelled")) return zh ? "已取消 Windows Hello 验证。" : "Windows Hello verification was cancelled.";
  if (key.includes("hello_needs_master")) return zh ? "请先使用主密码解锁，再启用本次快速解锁。" : "Unlock with the master password before enabling quick unlock for this run.";
  if (key.includes("hello_busy")) return zh ? "请完成或取消当前 Windows Hello 验证。" : "Complete or cancel the current Windows Hello prompt.";
  return zh ? "Windows Hello 暂不可用。请使用主密码，并检查 Windows 登录选项。" : "Windows Hello is unavailable. Use the master password and check Windows sign-in options.";
}
