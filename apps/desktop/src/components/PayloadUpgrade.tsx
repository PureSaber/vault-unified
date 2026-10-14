import { useEffect, useState } from "react";
import { api, clearToken } from "../api/client";
import { useI18n } from "../i18n";
import ConfirmDialog from "./ConfirmDialog";

export default function PayloadUpgrade() {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const [version, setVersion] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ preview_token: string; entry_count: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { void api.payloadFormat().then(data => setVersion(data.version)).catch(() => setError(zh ? "无法读取密码库格式。" : "Could not read the vault format.")); }, [zh]);

  async function prepare() {
    setBusy(true); setError("");
    try { setPreview(await api.previewPayloadUpgrade()); }
    catch { setError(zh ? "无法准备升级，请刷新后重试。" : "Could not prepare the upgrade. Refresh and try again."); }
    finally { setBusy(false); }
  }
  async function apply() {
    if (!preview || busy) return;
    const token = preview.preview_token;
    setPreview(null); setBusy(true); setError("");
    try {
      await api.applyPayloadUpgrade(token);
      clearToken(); window.location.reload();
    } catch {
      setError(zh ? "升级未完成，请重新解锁后检查格式与备份。" : "Upgrade did not complete. Unlock again to check the format and backups.");
    } finally { setBusy(false); }
  }
  function cancel() {
    if (preview) void api.cancelPayloadUpgrade(preview.preview_token).catch(() => {});
    setPreview(null);
  }
  return <section className="card" aria-labelledby="payload-format-heading">
    <h3 id="payload-format-heading">{zh ? "个人版数据格式" : "Personal vault data format"}</h3>
    {version === 3 ? <p>{zh ? "已启用个人版数据格式。" : "Personal vault data format is enabled."}</p> : <>
      <p>{zh ? "升级为账号整理、生成历史和多电脑同步准备数据结构。升级前自动保存并保留一份加密备份，完成后重新解锁。" : "Prepare the data format for organization, generated-password history and multi-computer sync. An encrypted backup is saved and retained first; unlock again after upgrading."}</p>
      <p>{zh ? "升级后的密码库需要新版客户端；旧版客户端可打开升级前备份。备份可在下方备份列表中找到。" : "The upgraded vault requires a newer client. Older clients can open the pre-upgrade backup, available in the backup list below."}</p>
      <button type="button" disabled={busy || version === null} onClick={() => void prepare()}>{busy ? (zh ? "正在处理…" : "Working…") : (zh ? "查看升级" : "Review upgrade")}</button>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
    <ConfirmDialog open={preview !== null} idPrefix="payload-upgrade" title={zh ? "升级密码库格式" : "Upgrade vault format"}
      message={zh ? `将保留全部 ${preview?.entry_count ?? 0} 个条目及附件、历史记录。先创建保留的加密备份，再升级并锁定密码库。` : `Keep all ${preview?.entry_count ?? 0} entries, attachments and history. Create a retained encrypted backup, then upgrade and lock the vault.`}
      confirmLabel={zh ? "备份并升级" : "Back up and upgrade"} onConfirm={() => void apply()} onCancel={cancel} />
  </section>;
}
