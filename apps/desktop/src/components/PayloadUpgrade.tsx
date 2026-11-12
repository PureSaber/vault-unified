import { useTaskLifetime } from "./useTaskLifetime";
import { useEffect, useRef, useState } from "react";
import { api, clearToken } from "../api/client";
import { useI18n } from "../i18n";
import ConfirmDialog from "./ConfirmDialog";

export default function PayloadUpgrade({ onDirtyChange, onSavingChange }: { onDirtyChange?: (value: boolean) => void; onSavingChange?: (value: boolean) => void }) {
  const alive = useTaskLifetime();
  const activePreview = useRef<string | null>(null);
  useEffect(() => () => { if (activePreview.current) void api.cancelPayloadUpgrade(activePreview.current).catch(() => {}); }, []);
  const { locale, t } = useI18n();
  const zh = locale === "zh";
  const [version, setVersion] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ preview_token: string; entry_count: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { onDirtyChange?.(Boolean(preview)); onSavingChange?.(busy); });
  useEffect(() => () => { onDirtyChange?.(false); onSavingChange?.(false); }, [onDirtyChange, onSavingChange]);
  useEffect(() => { void api.payloadFormat().then(data => { if (alive.current) setVersion(data.version); }).catch(() => setError(t("PayloadUpgrade.couldNotReadTheVaultFormat"))); }, [zh]);

  async function prepare() {
    setBusy(true); setError("");
    try {
      const next = await api.previewPayloadUpgrade();
      if (!alive.current) { void api.cancelPayloadUpgrade(next.preview_token).catch(() => {}); return; }
      activePreview.current = next.preview_token; setPreview(next);
    }
    catch { setError(t("PayloadUpgrade.couldNotPrepareTheUpgradeRefreshAnd")); }
    finally { if (alive.current) setBusy(false); }
  }
  async function apply() {
    if (!preview || busy) return;
    const token = preview.preview_token;
    activePreview.current = null;
    setPreview(null); setBusy(true); setError("");
    try {
      await api.applyPayloadUpgrade(token);
      if (!alive.current) return;
      clearToken(); window.location.reload();
    } catch {
      setError(t("PayloadUpgrade.upgradeDidNotCompleteUnlockAgainTo"));
    } finally { if (alive.current) setBusy(false); }
  }
  function cancel() {
    if (preview) void api.cancelPayloadUpgrade(preview.preview_token).catch(() => {});
    activePreview.current = null;
    setPreview(null);
  }
  return <section className="card" aria-labelledby="payload-format-heading">
    <h3 id="payload-format-heading">{t("PayloadUpgrade.personalVaultDataFormat")}</h3>
    {version === 3 ? <p>{t("PayloadUpgrade.personalVaultDataFormatIsEnabled")}</p> : <>
      <p>{t("PayloadUpgrade.prepareTheDataFormatForOrganizationGenerated")}</p>
      <p>{t("PayloadUpgrade.theUpgradedVaultRequiresANewerClient")}</p>
      <button type="button" disabled={busy || version === null} onClick={() => void prepare()}>{busy ? (t("PayloadUpgrade.working")) : (t("PayloadUpgrade.reviewUpgrade"))}</button>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
    <ConfirmDialog open={preview !== null} idPrefix="payload-upgrade" title={t("PayloadUpgrade.upgradeVaultFormat")}
      message={t("PayloadUpgrade.keepAllEntriesAttachmentsAndHistoryCreate", { value1: preview?.entry_count ?? 0 })}
      confirmLabel={t("PayloadUpgrade.backUpAndUpgrade")} onConfirm={() => void apply()} onCancel={cancel} />
  </section>;
}
