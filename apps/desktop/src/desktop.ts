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
