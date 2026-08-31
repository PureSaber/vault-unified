import { useState } from "react";
import { api, type BrowserPairing } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";

export default function ConnectionTools() {
  const { locale } = useI18n();
  const { showToast } = useToast();
  const zh = locale === "zh";
  const [pairing, setPairing] = useState<BrowserPairing | null>(null);
  const [busy, setBusy] = useState(false);
  const [showMobileDetails, setShowMobileDetails] = useState(false);

  async function createPairing() {
    setBusy(true);
    try {
      const result = await api.createBrowserPairing();
      setPairing(result);
      showToast(zh ? "一次性配对码已生成" : "One-time pairing code created");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-section" aria-labelledby="device-connections-heading">
      <h3 id="device-connections-heading" className="section-title">
        {zh ? "浏览器和其他设备" : "Browser and other devices"}
      </h3>
      <div className="connection-card-grid">
        <article className="connection-card">
          <h4>{zh ? "浏览器扩展" : "Browser extension"}</h4>
          <p>{zh ? "在支持的网站上选择账号并填充登录表单。" : "Choose an account to fill a sign-in form on supported sites."}</p>
          <button className="secondary" type="button" onClick={createPairing} disabled={busy}>
            {busy ? (zh ? "正在生成…" : "Creating…") : (zh ? "生成一次性配对码" : "Create one-time pairing code")}
          </button>
          {pairing && (
            <div className="result-panel" aria-live="polite">
              <div>{zh ? "本机地址：" : "Local address: "}{pairing.sidecar_url}</div>
              <div>{zh ? "一次性配对码：" : "One-time pairing code: "}{pairing.pairing_code}</div>
              <div>{zh ? "此代码会自动到期。" : "This code expires automatically."}</div>
            </div>
          )}
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
    </section>
  );
}
