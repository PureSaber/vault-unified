import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { api } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import ConfirmDialog from "./ConfirmDialog";
import type { DesktopPreferences } from "../desktop";

export default function DesktopUpdates({ preferences, onPreferences, onBusy }: { preferences: DesktopPreferences; onPreferences: (value: DesktopPreferences) => Promise<void>; onBusy: (value: boolean) => void }) {
  const { locale } = useI18n(), { showToast } = useToast(); const zh = locale === "zh";
  const text = (en: string, cn: string) => zh ? cn : en;
  const [update, setUpdate] = useState<{ version: string; notes: string } | null>(null);
  const [busy, setBusy] = useState(false), [checking, setChecking] = useState(false), [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState(""), [progress, setProgress] = useState<{ downloaded: number; total: number | null; stage: string } | null>(null);
  useEffect(() => { onBusy(busy); return () => onBusy(false); }, [busy, onBusy]);
  useEffect(() => { let active = true; void api.updateStatus().then(value => { if (active) setUpdate(value); }).catch(() => {}); return () => { active = false; }; }, []);
  useEffect(() => {
    let active = true; let stop: (() => void) | undefined;
    void listen<{ downloaded: number; total: number | null; stage: string }>("desktop-update-progress", event => { if (active) setProgress(event.payload); }).then(value => { if (active) stop = value; else value(); });
    return () => { active = false; stop?.(); };
  }, []);
  async function check() {
    setChecking(true); setMessage(""); setUpdate(null);
    try { const value = await api.checkDesktopUpdate(); setUpdate(value); if (!value) setMessage(text("This version is up to date.", "当前已是最新版本。")); }
    catch { setMessage(text("Could not check for updates. Try again when connected.", "暂时无法检查更新，联网后可重试。")); }
    finally { setChecking(false); }
  }
  async function install() {
    if (!update) return; setConfirm(false); setBusy(true); setMessage("");
    try { await api.installDesktopUpdate(update.version); }
    catch (reason) {
      const value = String(reason);
      const message = value.includes("backup") ? text("Unlock again and retry. Installation stops if the encrypted backup cannot be saved.", "请重新解锁后重试。加密备份未成功保存时，安装不会继续。") : value.includes("install_failed") ? text("The installer could not start. Your vault and pre-update backup are retained; reopen the app and try again.", "安装程序未能启动。密码库和更新前备份已保留，可重新打开应用后重试。") : text("The update could not be verified or downloaded. Your installed version is unchanged; check again to retry.", "更新下载或签名验证未通过，当前安装版本保持不变，可重新检查后重试。");
      setMessage(message); showToast(message, "error"); setUpdate(null);
    } finally { setBusy(false); setProgress(null); }
  }
  return <section className="settings-section" aria-labelledby="desktop-updates-heading">
    <h3 id="desktop-updates-heading">{text("Application updates", "应用更新")}</h3>
    <label className="checkbox-field"><input type="checkbox" checked={Boolean(preferences.check_updates)} disabled={busy || checking} onChange={event => void onPreferences({ ...preferences, check_updates: event.target.checked })}/><span>{text("Check for updates when the app starts", "启动应用时检查更新")}</span></label>
    <p className="field-hint">{text("Checks contact the project's GitHub releases. Installation always needs your confirmation and verifies the update signature. An encrypted vault backup is retained before installation.", "检查更新会连接项目的 GitHub 发布页。安装前需要确认并验证更新签名，同时保留一份加密密码库备份。")}</p>
    <button type="button" className="secondary" disabled={busy || checking} onClick={() => void check()}>{checking ? text("Checking…", "正在检查…") : text("Check for updates", "检查更新")}</button>
    {update && <div className="nested-panel"><h4>{text("Available version", "可用版本")} {update.version}</h4><p style={{ whiteSpace: "pre-wrap" }}>{update.notes}</p><button className="primary" type="button" disabled={busy || checking} onClick={() => setConfirm(true)}>{text("Review update", "查看更新确认")}</button></div>}
    {message && <p role="status">{message}</p>}
    {busy && <p role="status">{progress?.stage === "preparing" ? text("Creating encrypted backup…", "正在创建加密备份…") : progress?.stage === "installing" ? text("Starting installer…", "正在启动安装程序…") : text("Downloading and verifying…", "正在下载并验证…")} {progress?.stage === "downloading" && `${Math.round(progress.downloaded / 1048576)} MB${progress.total ? ` / ${Math.round(progress.total / 1048576)} MB` : ""}`}</p>}
    <ConfirmDialog open={confirm} idPrefix="desktop-update" title={text("Install update", "安装更新")} message={text(`Download version ${update?.version}, verify its signature, back up the vault and restart to install. Use the matching extension version from the release kit.`, `下载 ${update?.version} 版、验证签名并备份密码库，然后重新启动安装。请同时使用安装套件中的配套扩展版本。`)} onCancel={() => setConfirm(false)} onConfirm={() => void install()} />
  </section>;
}
