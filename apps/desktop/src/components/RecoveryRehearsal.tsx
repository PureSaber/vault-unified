import { useEffect, useRef, useState } from "react";
import { api, type RecoveryRehearsalResult } from "../api/client";
import { useI18n } from "../i18n";
import PathPicker from "./PathPicker";

export default function RecoveryRehearsal({ suggestedPath = "" }: { suggestedPath?: string }) {
  const { locale } = useI18n(); const zh = locale === "zh";
  const [expanded, setExpanded] = useState(false);
  const [path, setPath] = useState(suggestedPath);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RecoveryRehearsalResult | null>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  useEffect(() => { generation.current++; setPath(suggestedPath); setResult(null); setBusy(false); }, [suggestedPath]);
  function close() { generation.current++; setExpanded(false); setBusy(false); setCode(""); setResult(null); setError(""); }
  async function rehearse(event: React.FormEvent) {
    event.preventDefault();
    if (!path.trim() || !code || busy) return;
    const stamp = ++generation.current;
    setBusy(true); setError(""); setResult(null);
    try {
      const verified = await api.rehearseRecoveryKit(path, code);
      if (stamp === generation.current) { setResult(verified); setCode(""); }
    } catch { if (stamp === generation.current) setError(zh ? "演练未通过，请检查文件和恢复码后重试。" : "Rehearsal failed. Check the file and recovery code, then retry."); }
    finally { if (stamp === generation.current) setBusy(false); }
  }
  return <section className="settings-section" aria-labelledby="migration-heading">
    <h4 id="migration-heading">{zh ? "换电脑与恢复演练" : "Move computers and rehearse recovery"}</h4>
    {!expanded ? <button type="button" className="secondary" onClick={() => setExpanded(true)}>{zh ? "打开换机向导" : "Open migration guide"}</button> : <>
      <ol>
        <li>{zh ? "在旧电脑用上方的“创建恢复包”保存加密文件，并单独记录恢复码。修改数据后应重新创建最新的包。" : "On the old computer, use Create recovery kit above to save the encrypted file and record its code separately. Create a fresh kit after changing data."}</li>
        <li>{zh ? "重新输入你记录的恢复码，执行下方演练。它会在独立临时目录实际恢复、重新打开并核对完整数据，随后删除临时副本。" : "Re-enter the code you recorded and rehearse below. Recovery actually writes and reopens an isolated encrypted vault, compares all data, then removes the temporary copy."}</li>
        <li>{zh ? "将加密包带到新电脑，安装相同或更新版本，在启动页选择“从另一台电脑迁入”，输入恢复码并设置新的主密码。确认账号和附件后再处理旧电脑。" : "Move the encrypted kit to the new computer. Install the same or a newer version, choose Bring a vault from another computer on startup, enter the code and set a new master password. Check accounts and attachments before retiring the old computer."}</li>
      </ol>
      <p className="field-hint">{zh ? "浏览器授权、Windows Hello 和本机连接设置需要在新电脑重新配置。演练不会修改当前密码库，也不会启用同步。" : "Set up browser authorization, Windows Hello and local connection settings again on the new computer. Rehearsal leaves the current vault unchanged and does not enable sync."}</p>
      <form onSubmit={event => void rehearse(event)}>
        <fieldset className="recovery-rehearsal-fields" disabled={busy}>
          <PathPicker id="rehearsal-kit" label={zh ? "用于演练的加密包" : "Encrypted kit to rehearse"} mode="file" value={path} onChange={value => { setPath(value); setResult(null); }} extensions={["vault"]} required />
          <div className="field"><label className="field-label" htmlFor="rehearsal-code">{zh ? "演练恢复码" : "Recovery code for rehearsal"}</label>
          <input id="rehearsal-code" type="password" autoComplete="off" value={code} onChange={event => { setCode(event.target.value); setResult(null); }} required /></div>
          <button type="submit" className="secondary" disabled={!path.trim() || !code}>{busy ? (zh ? "正在隔离恢复…" : "Restoring in isolation…") : (zh ? "开始恢复演练" : "Rehearse recovery")}</button>
        </fieldset>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {result && <div role="status">
        <p>{zh ? "演练通过：完整数据一致，临时副本已删除。" : "Rehearsal passed: all data matched and the temporary copy was removed."}</p>
        <dl className="status-grid">
          {([ [zh ? "条目" : "Entries", result.counts.entries], [zh ? "正常 / 归档 / 回收站" : "Active / archived / trash", `${result.counts.active} / ${result.counts.archived} / ${result.counts.trash}`], [zh ? "附件" : "Attachments", result.counts.attachments], [zh ? "历史版本" : "History versions", result.counts.history], [zh ? "验证码条目" : "Authenticator entries", result.counts.totp] ] as const).map(([label, value]) => <div className="status-row" key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
        <p className="field-hint">{zh ? "演练对应所选文件当时的内容。新电脑完成恢复后，请打开常用账号、附件并验证验证码。" : "This result covers the selected file at the time of rehearsal. After recovery on the new computer, open common logins and attachments and verify authenticator codes."}</p>
      </div>}
      <button type="button" className="secondary" onClick={close}>{zh ? "关闭换机向导" : "Close migration guide"}</button>
    </>}
  </section>;
}
