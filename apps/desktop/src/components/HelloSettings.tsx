import SettingsCard from "./SettingsCard";
import { useEffect, useState } from "react";
import { api, type HelloStatus } from "../api/client";
import { helloError } from "../desktop";
import { useI18n } from "../i18n";
import { HELLO_PROMPT_EVENT, helloPromptEnabled, setHelloPromptEnabled } from "./hello-prompt";

export default function HelloSettings({ onBusy }: { onBusy?: (value: boolean) => void }) {
  const { locale, t } = useI18n();
  const zh = locale === "zh";
  const [status, setStatus] = useState<HelloStatus | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { onBusy?.(busy); return () => onBusy?.(false); }, [busy, onBusy]);
  const [error, setError] = useState("");
  const [offer, setOffer] = useState(helloPromptEnabled);
  useEffect(() => {
    const changed = () => setOffer(helloPromptEnabled());
    window.addEventListener(HELLO_PROMPT_EVENT, changed);
    return () => window.removeEventListener(HELLO_PROMPT_EVENT, changed);
  }, []);
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
  return <SettingsCard id="hello-heading" title="Windows Hello" mode="immediate">
    <p className="field-hint">{t("HelloSettings.useAFingerprintFaceOrWindowsPIN")}</p>
    <p role="status">{!status ? (t("HelloSettings.checkingWindowsHello")) : status.ready ? (t("HelloSettings.quickUnlockIsEnabledForThisRun")) : status.supported ? (t("HelloSettings.quickUnlockIsNotEnabledForThis")) : (t("HelloSettings.setUpWindowsHelloInWindowsSettings"))}</p>
    <button type="button" className="secondary" disabled={busy || !status?.supported || status.busy} onClick={() => void change()}>{busy ? (t("HelloSettings.waitingForWindowsHello")) : status?.ready ? (t("HelloSettings.disableQuickUnlock")) : (t("HelloSettings.enableWindowsHelloForThisRun"))}</button>
    {error && <p className="error" role="alert">{error}</p>}
    {status?.supported && <label className="checkbox-field"><input type="checkbox" checked={offer} onChange={event => setHelloPromptEnabled(event.target.checked)} /><span>{t("HelloSettings.afterIUnlockWithTheMasterPassword")}</span></label>}
  </SettingsCard>;
}
