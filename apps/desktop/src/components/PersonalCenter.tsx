import { useEffect, useState } from "react";
import { api, BrowserPairing, Integration, PersonalSettings } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import ImportWizard from "./ImportWizard";

const defaults: PersonalSettings = {
  lock_after_seconds: 15 * 60,
  auto_backup_enabled: false,
  auto_backup_interval_hours: 24,
  auto_backup_destination: "",
  last_auto_backup_at: "",
};

function downloadText(filename: string, mimeType: string, content: string) {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function PersonalCenter() {
  const { locale } = useI18n();
  const { showToast } = useToast();
  const zh = locale === "zh";
  const [settings, setSettings] = useState<PersonalSettings>(defaults);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [recoveryCode, setRecoveryCode] = useState("");
  const [recoveryConfirm, setRecoveryConfirm] = useState("");
  const [recoveryDestination, setRecoveryDestination] = useState("");
  const [browserPairing, setBrowserPairing] = useState<BrowserPairing | null>(null);

  useEffect(() => {
    Promise.all([api.getPersonalSettings(), api.integrations()])
      .then(([personal, sources]) => {
        setSettings(personal);
        setIntegrations(sources);
      })
      .catch((error) => showToast(String(error).replace(/^Error:\s*/, ""), "error"))
      .finally(() => setLoading(false));
  }, [showToast]);

  async function saveSettings(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const saved = await api.savePersonalSettings(settings);
      setSettings(saved);
      showToast(zh ? "个人安全设置已保存" : "Personal security settings saved");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally {
      setSaving(false);
    }
  }

  async function exportVault(format: "json" | "csv") {
    const confirmed = window.confirm(
      zh
        ? "导出将创建包含明文密码的文件。请仅短暂保存，并在导入后删除。是否继续？"
        : "Export creates a plaintext file containing passwords. Store it briefly and delete it after import. Continue?"
    );
    if (!confirmed) return;
    try {
      const result = await api.exportTransfer(format);
      downloadText(result.filename, result.mime_type, result.content);
      showToast(zh ? "明文导出已下载；请在使用后删除该文件" : "Plaintext export downloaded; delete it after use");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function generateRecoveryCode() {
    try {
      const result = await api.newRecoveryCode();
      setRecoveryCode(result.recovery_code);
      setRecoveryConfirm("");
      showToast(zh ? "恢复码只会显示在此处；请离线保存" : "The recovery code is shown only here; save it offline");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function createRecoveryKit() {
    if (!recoveryCode || recoveryCode !== recoveryConfirm) {
      showToast(zh ? "请准确重新输入恢复码后再创建" : "Re-enter the recovery code exactly before creating the kit", "error");
      return;
    }
    try {
      const result = await api.createRecoveryKit(recoveryCode, recoveryDestination);
      showToast(zh ? `恢复包已创建：${result.path}` : `Recovery kit created: ${result.path}`);
      setRecoveryCode("");
      setRecoveryConfirm("");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function createBrowserPairing() {
    try {
      const pairing = await api.createBrowserPairing();
      setBrowserPairing(pairing);
      showToast(zh ? "浏览器配对码已生成，5 分钟后失效" : "Browser pairing code created; it expires in five minutes");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    }
  }

  if (loading) return <div className="loading-state">{zh ? "加载个人设置…" : "Loading personal settings…"}</div>;

  return (
    <>
      <section className="settings-section" aria-labelledby="personal-security-heading">
        <h3 id="personal-security-heading" className="section-title">
          {zh ? "个人安全与自动备份" : "Personal security and scheduled backups"}
        </h3>
        <form onSubmit={saveSettings}>
          <div className="field">
            <label className="field-label" htmlFor="lock-after">
              {zh ? "自动锁定时间" : "Auto-lock after"}
            </label>
            <select
              id="lock-after"
              value={settings.lock_after_seconds}
              onChange={(e) => setSettings({ ...settings, lock_after_seconds: Number(e.target.value) })}
            >
              <option value={60}>{zh ? "1 分钟" : "1 minute"}</option>
              <option value={300}>{zh ? "5 分钟" : "5 minutes"}</option>
              <option value={900}>{zh ? "15 分钟" : "15 minutes"}</option>
              <option value={1800}>{zh ? "30 分钟" : "30 minutes"}</option>
              <option value={3600}>{zh ? "60 分钟" : "60 minutes"}</option>
            </select>
          </div>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={settings.auto_backup_enabled}
              onChange={(e) => setSettings({ ...settings, auto_backup_enabled: e.target.checked })}
            />
            <span>{zh ? "应用解锁期间自动创建加密备份" : "Create encrypted backups while the app is unlocked"}</span>
          </label>
          <p className="field-hint">
            {zh
              ? "选择 OneDrive、Dropbox 或 NAS 的同步目录可形成异地副本；任务只会在应用打开且已解锁时运行。"
              : "Choose a synced OneDrive, Dropbox, or NAS folder for an off-device copy. Jobs run only while the app is open and unlocked."}
          </p>
          {settings.auto_backup_enabled && (
            <>
              <div className="field">
                <label className="field-label" htmlFor="backup-interval">
                  {zh ? "备份间隔（小时）" : "Backup interval (hours)"}
                </label>
                <input
                  id="backup-interval"
                  type="number"
                  min={1}
                  max={720}
                  value={settings.auto_backup_interval_hours}
                  onChange={(e) =>
                    setSettings({ ...settings, auto_backup_interval_hours: Math.max(1, Math.min(720, Number(e.target.value) || 1)) })
                  }
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="auto-backup-destination">
                  {zh ? "备份目录" : "Backup folder"}
                </label>
                <input
                  id="auto-backup-destination"
                  value={settings.auto_backup_destination}
                  onChange={(e) => setSettings({ ...settings, auto_backup_destination: e.target.value })}
                  placeholder={zh ? "例如 D:\\OneDrive\\VaultBackups" : "For example D:\\OneDrive\\VaultBackups"}
                />
              </div>
            </>
          )}
          <button className="secondary" type="submit" disabled={saving}>
            {saving ? (zh ? "保存中…" : "Saving…") : (zh ? "保存个人设置" : "Save personal settings")}
          </button>
        </form>
      </section>

      <section className="settings-section" aria-labelledby="transfer-heading">
        <h3 id="transfer-heading" className="section-title">{zh ? "导入与导出" : "Import and export"}</h3>
        <p className="field-hint">
          {zh ? "JSON 保留本地扩展与附件；CSV 适合迁移账号字段，但不包含附件。" : "JSON preserves local extensions and attachments. CSV is for account-field migration and excludes attachments."}
        </p>
        <div className="button-row">
          <button className="secondary" type="button" onClick={() => exportVault("json")}>JSON</button>
          <button className="secondary" type="button" onClick={() => exportVault("csv")}>CSV</button>
        </div>
        <ImportWizard />
      </section>

      <section className="settings-section" aria-labelledby="browser-heading">
        <h3 id="browser-heading" className="section-title">{zh ? "Chromium 浏览器填充" : "Chromium browser fill"}</h3>
        <p className="field-hint">
          {zh
            ? "扩展只在你点击其弹窗中的条目后填充；它不会获得桌面端启动密钥，也不会在保险库锁定后继续工作。"
            : "The extension fills only after you click an entry in its popup. It never receives the desktop bootstrap secret and stops working when the vault locks."}
        </p>
        <button className="secondary" type="button" onClick={createBrowserPairing}>
          {zh ? "生成一次性配对码" : "Create one-time pairing code"}
        </button>
        {browserPairing && (
          <div className="result-panel" aria-live="polite">
            <div>{zh ? "扩展目录：apps/browser-extension（在 Chrome/Edge 的开发者模式中“加载已解压的扩展程序”）" : "Extension folder: apps/browser-extension (use Load unpacked in Chrome/Edge developer mode)"}</div>
            <div>{zh ? "本机地址：" : "Local address: "}{browserPairing.sidecar_url}</div>
            <div>{zh ? "一次性配对码：" : "One-time pairing code: "}{browserPairing.pairing_code}</div>
          </div>
        )}
      </section>

      <section className="settings-section" aria-labelledby="mobile-heading">
        <h3 id="mobile-heading" className="section-title">{zh ? "移动端使用边界" : "Mobile-use boundary"}</h3>
        <p className="field-hint">
          {zh
            ? "桌面端 API 只绑定本机回环地址，不会为了手机访问而开放局域网端口。当前可安全使用方式是选择已连接的 Bitwarden 或 Proton Pass 作为同步目标，并使用其官方移动端；本地专属附件、历史和自定义字段仍保留在加密桌面库中。"
            : "The desktop API stays bound to loopback; it never opens a LAN port for a phone. Today’s safe mobile path is a connected Bitwarden or Proton Pass target and that provider’s official mobile app; desktop-only attachments, history, and custom fields remain in the encrypted local vault."}
        </p>
      </section>

      <section className="settings-section" aria-labelledby="recovery-heading">
        <h3 id="recovery-heading" className="section-title">{zh ? "紧急恢复包" : "Emergency recovery kit"}</h3>
        <p className="field-hint">
          {zh
            ? "恢复包使用独立的高熵恢复码加密。请将恢复码离线保存，并与恢复包文件放在不同位置。"
            : "A kit is encrypted with a separate high-entropy recovery code. Save the code offline and keep it separate from the kit file."}
        </p>
        <div className="button-row">
          <button className="secondary" type="button" onClick={generateRecoveryCode}>
            {zh ? "生成恢复码" : "Generate recovery code"}
          </button>
        </div>
        {recoveryCode && (
          <>
            <div className="field">
              <label className="field-label" htmlFor="recovery-code">{zh ? "恢复码（请立即离线记录）" : "Recovery code (record offline now)"}</label>
              <input id="recovery-code" value={recoveryCode} readOnly />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="recovery-confirm">{zh ? "重新输入恢复码以确认" : "Re-enter recovery code to confirm"}</label>
              <input id="recovery-confirm" value={recoveryConfirm} onChange={(e) => setRecoveryConfirm(e.target.value)} autoComplete="off" />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="recovery-destination">{zh ? "恢复包目录（建议 U 盘或其他位置）" : "Recovery-kit folder (prefer USB or another location)"}</label>
              <input id="recovery-destination" value={recoveryDestination} onChange={(e) => setRecoveryDestination(e.target.value)} />
            </div>
            <button className="secondary" type="button" onClick={createRecoveryKit}>
              {zh ? "创建恢复包" : "Create recovery kit"}
            </button>
          </>
        )}
      </section>

      <section className="settings-section" aria-labelledby="onboarding-heading">
        <h3 id="onboarding-heading" className="section-title">{zh ? "连接引导" : "Connection checklist"}</h3>
        <p className="field-hint">
          {zh ? "先安装官方 CLI，再在下方的连接管理器中保存凭据并执行测试。" : "Install the official CLI first, then save credentials and run a test in the connection manager below."}
        </p>
        <ul className="backup-list">
          {integrations.map((item) => (
            <li key={item.source}>
              <strong>{item.label}</strong>
              {": "}
              {item.cli_installed ? (item.configured ? (zh ? "已连接" : "connected") : (zh ? "CLI 已安装，待配置" : "CLI installed; needs setup")) : (zh ? "需要安装官方 CLI" : "official CLI required")}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
