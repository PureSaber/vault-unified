import { useEffect, useRef, useState } from "react";
import { api, type RecoveryRehearsalResult } from "../api/client";
import { useI18n } from "../i18n";
import PathPicker from "./PathPicker";

export default function RecoveryRehearsal({ suggestedPath = "", onDirtyChange, onSavingChange }: { suggestedPath?: string; onDirtyChange?: (value: boolean) => void; onSavingChange?: (value: boolean) => void }) {
  const { locale, t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [path, setPath] = useState(suggestedPath);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RecoveryRehearsalResult | null>(null);
  useEffect(() => { onDirtyChange?.(Boolean(code)); onSavingChange?.(busy); });
  useEffect(() => () => { onDirtyChange?.(false); onSavingChange?.(false); }, [onDirtyChange, onSavingChange]);
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
    } catch { if (stamp === generation.current) setError(t("RecoveryRehearsal.rehearsalFailedCheckTheFileAndRecovery")); }
    finally { if (stamp === generation.current) setBusy(false); }
  }
  return <section className="settings-section" aria-labelledby="migration-heading">
    <h4 id="migration-heading">{t("RecoveryRehearsal.moveComputersAndRehearseRecovery")}</h4>
    {!expanded ? <button type="button" className="secondary" onClick={() => setExpanded(true)}>{t("RecoveryRehearsal.openMigrationGuide")}</button> : <>
      <ol>
        <li>{t("RecoveryRehearsal.onTheOldComputerUseCreateRecovery")}</li>
        <li>{t("RecoveryRehearsal.reEnterTheCodeYouRecordedAnd")}</li>
        <li>{t("RecoveryRehearsal.moveTheEncryptedKitToTheNew")}</li>
      </ol>
      <p className="field-hint">{t("RecoveryRehearsal.setUpBrowserAuthorizationWindowsHelloAnd")}</p>
      <form onSubmit={event => void rehearse(event)}>
        <fieldset className="recovery-rehearsal-fields" disabled={busy}>
          <PathPicker id="rehearsal-kit" label={t("RecoveryRehearsal.encryptedKitToRehearse")} mode="file" value={path} onChange={value => { setPath(value); setResult(null); }} extensions={["vault"]} required />
          <div className="field"><label className="field-label" htmlFor="rehearsal-code">{t("RecoveryRehearsal.recoveryCodeForRehearsal")}</label>
          <input id="rehearsal-code" type="password" autoComplete="off" value={code} onChange={event => { setCode(event.target.value); setResult(null); }} required /></div>
          <button type="submit" className="secondary" disabled={!path.trim() || !code}>{busy ? (t("RecoveryRehearsal.restoringInIsolation")) : (t("RecoveryRehearsal.rehearseRecovery"))}</button>
        </fieldset>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {result && <div role="status">
        <p>{t("RecoveryRehearsal.rehearsalPassedAllDataMatchedAndThe")}</p>
        <dl className="status-grid">
          {([ [t("RecoveryRehearsal.entries"), result.counts.entries], [t("RecoveryRehearsal.activeArchivedTrash"), `${result.counts.active} / ${result.counts.archived} / ${result.counts.trash}`], [t("RecoveryRehearsal.attachments"), result.counts.attachments], [t("RecoveryRehearsal.historyVersions"), result.counts.history], [t("RecoveryRehearsal.authenticatorEntries"), result.counts.totp] ] as const).map(([label, value]) => <div className="status-row" key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
        <p className="field-hint">{t("RecoveryRehearsal.thisResultCoversTheSelectedFileAt")}</p>
      </div>}
      <button type="button" className="secondary" onClick={close}>{t("RecoveryRehearsal.closeMigrationGuide")}</button>
    </>}
  </section>;
}
