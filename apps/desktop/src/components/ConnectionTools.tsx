import { open as openExternal } from "@tauri-apps/plugin-shell";
import { useEffect, useState } from "react";
import { api, type BrowserPairing, type BrowserDevice } from "../api/client";
import ConfirmDialog from "./ConfirmDialog";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";

/** The extension's fixed ID (manifest `key`); see docs/browser-connection-approval.md. */
export const EXTENSION_ORIGIN = "chrome-extension://llgobjolacibpkimbfgighcmblbnalpb";

export default function ConnectionTools() {
  const { locale } = useI18n();
  const { showToast } = useToast();
  const zh = locale === "zh";
  const [pairing, setPairing] = useState<BrowserPairing | null>(null);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const [busy, setBusy] = useState(false);
  const [showMobileDetails, setShowMobileDetails] = useState(false);
  const [devices, setDevices] = useState<BrowserDevice[]>([]);
  const [deviceStorageAvailable, setDeviceStorageAvailable] = useState(true);
  const [revokeTarget, setRevokeTarget] = useState<BrowserDevice | null>(null);

  async function refreshDevices() {
    try {
      const result = await api.browserDevices();
      setDevices(result.devices);
      setDeviceStorageAvailable(result.available);
    } catch { setDeviceStorageAvailable(false); }
  }
  useEffect(() => { void refreshDevices(); }, []);

  async function revokeDevice() {
    if (!revokeTarget) return;
    setBusy(true);
    try {
      await api.revokeBrowserDevice(revokeTarget.id);
      setRevokeTarget(null);
      await refreshDevices();
      showToast(zh ? "设备授权已撤销" : "Device authorization revoked");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally { setBusy(false); }
  }

  async function createPairing() {
    setBusy(true);
    try {
      const result = await api.createBrowserPairing();
      setPairing(result);
      setRemainingSeconds(result.expires_in_seconds);
      showToast(zh ? "一次性配对码已生成" : "One-time pairing code created");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!pairing) return;
    const expiresAt = Date.now() + pairing.expires_in_seconds * 1000;
    const timer = window.setInterval(() => {
      const next = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
      setRemainingSeconds(next);
      if (next === 0) setPairing(null);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [pairing]);

  async function copyText(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      showToast(zh ? `${label}已复制` : `${label} copied`);
    } catch {
      showToast(zh ? "无法复制，请手动选择文本。" : "Could not copy. Select the text manually.", "error");
    }
  }

  async function cancelPairing() {
    setBusy(true);
    try {
      await api.cancelBrowserPairing();
      setPairing(null);
      setRemainingSeconds(0);
      showToast(zh ? "配对已取消" : "Pairing cancelled");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally {
      setBusy(false);
    }
  }

  async function openInstallGuide() {
    try {
      await openExternal("https://github.com/PureSaber/vault-unified/blob/main/docs/browser-extension-install.md");
    } catch {
      showToast(zh ? "无法打开安装说明，请前往项目的最新发布页面。" : "Could not open the guide. Open the latest project release instead.", "error");
    }
  }

  const countdown = `${Math.floor(remainingSeconds / 60)}:${String(remainingSeconds % 60).padStart(2, "0")}`;

  return (
    <section className="settings-section" aria-labelledby="device-connections-heading">
      <h3 id="device-connections-heading" className="section-title">
        {zh ? "浏览器和其他设备" : "Browser and other devices"}
      </h3>
      <div className="connection-card-grid">
        <article className="connection-card">
          <h4>{zh ? "浏览器扩展" : "Browser extension"}</h4>
          <p>{zh ? "在支持的网站上填充账号，读取或手动输入密码，核对后保存或更新。" : "Fill accounts on supported sites, then review and save new or updated passwords."}</p>
          <p className="field-hint">
            {zh
              ? "在扩展中点击“连接到 Vault Unified”，然后在这里选择浏览器显示的代码即可，无需复制。下面的一次性配对码是备用方式。"
              : "In the extension, click Connect to Vault Unified, then choose the code the browser shows here. Nothing needs copying. The one-time pairing code below is the recovery option."}
          </p>
          <p className="field-hint">
            {zh
              ? "配对时可授权浏览器在重启后恢复连接。保险库仍需在桌面端解锁；锁定后不能读取或保存密码。你可以在下方随时撤销设备授权。"
              : "Authorize a browser when pairing to reconnect after restarting. Unlock the vault on the desktop first; locked vaults cannot read or save passwords. Revoke device authorization below at any time."}
          </p>
          <p className="field-hint">
            {zh
              ? "下载扩展 ZIP，解压后在 Chrome/Edge 的开发者模式中加载该目录。"
              : "Download the extension ZIP, extract it, then load that folder in Chrome/Edge Developer mode."}
          </p>
          <div className="button-row">
            <button className="secondary" type="button" onClick={() => void openInstallGuide()}>
              {zh ? "打开扩展安装说明" : "Open extension install guide"}
            </button>
            <button className="secondary" type="button" onClick={() => void createPairing()} disabled={busy}>
              {busy
                ? (zh ? "正在生成…" : "Creating…")
                : pairing
                  ? (zh ? "重新生成" : "Generate again")
                  : (zh ? "生成一次性配对码" : "Create one-time pairing code")}
            </button>
            {!pairing && <button className="secondary" type="button" onClick={() => void cancelPairing()} disabled={busy}>
              {zh ? "断开临时浏览器连接" : "Disconnect temporary browser session"}
            </button>}
          </div>
          {pairing && (
            <div className="result-panel" aria-live="polite">
              <div className="path-break">{zh ? "本机地址：" : "Local address: "}{pairing.sidecar_url}</div>
              <div className="path-break">{zh ? "一次性配对码：" : "One-time pairing code: "}{pairing.pairing_code}</div>
              <div>{zh ? `到期倒计时：${countdown}` : `Expires in: ${countdown}`}</div>
              <div className="button-row">
                <button className="secondary" type="button" onClick={() => void copyText(pairing.sidecar_url, zh ? "本机地址" : "Local address")}>
                  {zh ? "复制本机地址" : "Copy local address"}
                </button>
                <button className="secondary" type="button" onClick={() => void copyText(pairing.pairing_code, zh ? "配对码" : "Pairing code")}>
                  {zh ? "复制一次性配对码" : "Copy one-time pairing code"}
                </button>
                <button className="danger" type="button" onClick={() => void cancelPairing()} disabled={busy}>
                  {zh ? "取消配对" : "Cancel pairing"}
                </button>
              </div>
            </div>
          )}
          <h4>{zh ? "已授权浏览器" : "Authorized browsers"}</h4>
          {!deviceStorageAvailable && <p role="status">{zh ? "设备授权存储不可用，请检查 Windows 凭据管理器。临时配对仍可使用。" : "Device authorization storage is unavailable. Check Windows Credential Manager. Session-only pairing remains available."}</p>}
          {deviceStorageAvailable && devices.length === 0 && <p>{zh ? "还没有长期授权的浏览器。" : "No persistently authorized browsers yet."}</p>}
          <ul>{devices.map((device) => <li key={device.id}>
            <strong>{device.name}</strong>
            <span> · {new Date(device.created_at).toLocaleDateString(zh ? "zh-CN" : "en-US")}</span>
            {device.origin !== EXTENSION_ORIGIN && <p className="field-hint">
              <strong>{zh ? "旧扩展标识" : "Previous extension ID"}</strong>
              {zh ? "：此授权属于扩展更新前的标识，已无法使用，也不能从浏览器中撤销。请在这里撤销。" : ": this authorization belongs to the extension's earlier ID. It can no longer be used or revoked from the browser; revoke it here."}
            </p>}
            <details><summary>{zh ? "设备详情" : "Device details"}</summary><p className="path-break">{device.origin}</p></details>
            <button className="danger" type="button" disabled={busy} onClick={() => setRevokeTarget(device)}>
              {zh ? `撤销 ${device.name}` : `Revoke ${device.name}`}
            </button>
          </li>)}</ul>
          <button className="secondary" type="button" disabled={busy} onClick={() => void refreshDevices()}>{zh ? "刷新设备列表" : "Refresh devices"}</button>
        </article>
        <article className="connection-card">
          <h4>{zh ? "在手机上使用" : "Use on a phone"}</h4>
          <p>{zh ? "可选：连接外部密码服务后，使用该服务的官方手机应用。" : "Optional: connect an external password service, then use its official phone app."}</p>
          <button className="ghost" type="button" onClick={() => setShowMobileDetails((value) => !value)} aria-expanded={showMobileDetails}>
            {showMobileDetails ? (zh ? "隐藏技术细节" : "Hide technical details") : (zh ? "技术细节" : "Technical details")}
          </button>
          {showMobileDetails && (
            <p className="field-hint">
              {zh
                ? "桌面应用只接受这台电脑上的连接，不会为手机开放局域网端口。本地附件、历史和自定义字段继续保留在这台设备。"
                : "The desktop app accepts connections only from this computer and does not open a LAN port for phones. Local attachments, history, and custom fields stay on this device."}
            </p>
          )}
        </article>
      </div>
      <ConfirmDialog open={revokeTarget !== null} title={zh ? "撤销浏览器授权？" : "Revoke browser authorization?"}
        message={zh ? `撤销后，${revokeTarget?.name || "此浏览器"} 需要重新配对才能访问此保险库。` : `After revocation, ${revokeTarget?.name || "this browser"} must pair again to access this vault.`}
        confirmLabel={zh ? "撤销授权" : "Revoke authorization"} variant="danger"
        onConfirm={() => void revokeDevice()} onCancel={() => setRevokeTarget(null)} />
    </section>
  );
}
