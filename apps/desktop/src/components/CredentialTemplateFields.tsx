import { api, type Entry, type TemplateData } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import PasswordField from "./PasswordField";

interface Props { type: Entry["entry_type"]; value: TemplateData; onChange: (value: TemplateData) => void; saved?: Entry | null }

export default function CredentialTemplateFields({ type, value, onChange, saved }: Props) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const { showToast } = useToast();
  const codes = value.recovery_codes || [];
  function setField(key: keyof TemplateData, text: string) { onChange({ ...value, [key]: text }); }
  async function copyCode(id: string) {
    if (!saved) return;
    try { await api.copyRecoveryCode(saved.id, id); showToast(zh ? "恢复码已复制，45 秒后清除剪贴板" : "Recovery code copied; clipboard clears in 45 seconds"); }
    catch (error) { showToast(String(error).replace(/^Error:\s*/, ""), "error"); }
  }
  return <section className="settings-section" aria-label={zh ? "凭据详情" : "Credential details"}>
    {(type === "software_license" || value.registered_to) && <div className="field">
      <label className="field-label" htmlFor="license-owner">{zh ? "登记人或邮箱" : "Registered name or email"}</label>
      <input id="license-owner" autoComplete="off" value={value.registered_to || ""} maxLength={500} onChange={event => setField("registered_to", event.target.value)} />
    </div>}
    {(type === "api_credential" || value.environment || value.scopes) && <>
      <div className="field"><label className="field-label" htmlFor="credential-environment">{zh ? "环境" : "Environment"}</label><input id="credential-environment" value={value.environment || ""} maxLength={128} placeholder={zh ? "例如：开发、测试、生产" : "For example: development, staging, production"} onChange={event => setField("environment", event.target.value)} /></div>
      <div className="field"><label className="field-label" htmlFor="credential-scopes">{zh ? "权限范围" : "Scopes"}</label><textarea id="credential-scopes" value={value.scopes || ""} maxLength={4096} onChange={event => setField("scopes", event.target.value)} /></div>
    </>}
    {(type === "software_license" || type === "api_credential" || value.expires_on) && <div className="field">
      <label className="field-label" htmlFor="credential-expiry">{zh ? "到期日（可选）" : "Expiry date (optional)"}</label>
      <input id="credential-expiry" type="date" value={value.expires_on || ""} onChange={event => setField("expires_on", event.target.value)} />
    </div>}
    {(type === "recovery_code" || codes.length > 0) && <>
      <p className="field-hint">{zh ? "逐条保存恢复码。使用后勾选“已使用”并保存；复制不会自动改变使用状态。" : "Store each recovery code separately. After use, mark it used and save. Copying does not change its status."}</p>
      {codes.map((code, index) => <div key={code.id} className="card recovery-code-row">
        <PasswordField id={`recovery-code-${code.id}`} label={`${zh ? "恢复码" : "Recovery code"} ${index + 1}`} value={code.value} required onChange={text => onChange({ ...value, recovery_codes: codes.map(item => item.id === code.id ? { ...item, value: text } : item) })} />
        <div className="button-row">
          <label className="checkbox-field"><input type="checkbox" checked={Boolean(code.used_at)} onChange={event => onChange({ ...value, recovery_codes: codes.map(item => item.id === code.id ? { ...item, used_at: event.target.checked ? new Date().toISOString() : "" } : item) })} /><span>{zh ? "已使用" : "Used"}</span></label>
          {code.used_at && <span className="field-hint">{new Date(code.used_at).toLocaleString(locale)}</span>}
          <button type="button" className="secondary" disabled={Boolean(code.used_at) || !saved?.template_data?.recovery_codes?.some(item => item.id === code.id && item.value === code.value && !item.used_at)} onClick={() => void copyCode(code.id)}>{zh ? "复制恢复码" : "Copy recovery code"}</button>
          <button type="button" className="secondary" onClick={() => onChange({ ...value, recovery_codes: codes.filter(item => item.id !== code.id) })}>{zh ? "从草稿移除" : "Remove from draft"}</button>
        </div>
      </div>)}
      <button type="button" className="secondary" disabled={codes.length >= 100} onClick={() => onChange({ ...value, recovery_codes: [...codes, { id: crypto.randomUUID(), value: "", used_at: "" }] })}>{zh ? "添加恢复码" : "Add recovery code"}</button>
      <p className="field-hint">{zh ? "新添或修改的恢复码保存后可复制。" : "Save newly added or edited recovery codes before copying."}</p>
    </>}
  </section>;
}
