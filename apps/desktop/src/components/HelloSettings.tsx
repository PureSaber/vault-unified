import { useEffect, useState } from "react";
import { api, type HelloStatus } from "../api/client";
import { helloError } from "../desktop";
import { useI18n } from "../i18n";

export default function HelloSettings() {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const [status, setStatus] = useState<HelloStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void api.helloStatus().then(value => { if (active) setStatus(value); }).catch(reason => { if (active) { setStatus({ supported: false, ready: false, busy: false }); setError(helloError(reason, zh)); } });
    return () => { active = false; };
  }, [zh]);
  async function change() {
    setBusy(true); setError("");
    try {
      if (status?.ready) { await api.disableHello(); setStatus({ ...status, ready: false }); }
      else setStatus(await api.enableHello());
    } catch (reason) { setError(helloError(reason, zh)); }
    finally { setBusy(false); }
  }
  return <section className="settings-section" aria-labelledby="hello-heading">
    <h3 className="section-title" id="hello-heading">Windows Hello</h3>
    <p className="field-hint">{zh ? "用指纹、人脸或 Windows PIN 快速解锁。每次启动先使用主密码，然后在此通过一次 Hello 验证，启用本次运行的快速解锁。" : "Use a fingerprint, face or Windows PIN to unlock. After each launch, use the master password, then verify Hello here once to enable quick unlock for this run."}</p>
    <p role="status">{!status ? (zh ? "正在检查 Windows Hello…" : "Checking Windows Hello…") : status.ready ? (zh ? "本次运行已启用快速解锁。" : "Quick unlock is enabled for this run.") : status.supported ? (zh ? "本次运行尚未启用。" : "Quick unlock is not enabled for this run.") : (zh ? "请先在 Windows 设置 → 账户 → 登录选项中配置 Windows Hello。" : "Set up Windows Hello in Windows Settings → Accounts → Sign-in options.")}</p>
    <button type="button" className="secondary" disabled={busy || !status?.supported || status.busy} onClick={() => void change()}>{busy ? (zh ? "等待 Windows Hello…" : "Waiting for Windows Hello…") : status?.ready ? (zh ? "关闭本次快速解锁" : "Disable quick unlock") : (zh ? "为本次运行启用 Windows Hello" : "Enable Windows Hello for this run")}</button>
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
