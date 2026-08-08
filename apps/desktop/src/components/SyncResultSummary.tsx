import { useState } from "react";
import { useI18n } from "../i18n";

export interface SyncResultData {
  pulled?: Record<string, Record<string, number>>;
  pushed?: Record<string, number>;
  conflicts?: unknown[];
  errors?: string[];
}

function formatPulled(
  pulled: Record<string, Record<string, number>>,
  noChanges: string
) {
  return Object.entries(pulled).map(([source, stats]) => {
    const parts = Object.entries(stats)
      .filter(([, n]) => n > 0)
      .map(([k, n]) => `${k}: ${n}`);
    return { source, detail: parts.length ? parts.join(", ") : noChanges };
  });
}

function formatPushed(pushed: Record<string, number>, noPush: string) {
  const entries = Object.entries(pushed).filter(([, n]) => n > 0);
  if (!entries.length) return noPush;
  return entries.map(([k, n]) => `${k}: ${n}`).join(", ");
}

export default function SyncResultSummary({ result }: { result: SyncResultData }) {
  const { t } = useI18n();
  const [showRaw, setShowRaw] = useState(false);
  const pulled = result.pulled
    ? formatPulled(result.pulled, t("syncSummary.noChanges"))
    : [];
  const conflictCount = result.conflicts?.length ?? 0;
  const errorCount = result.errors?.length ?? 0;

  return (
    <div className="sync-summary">
      <dl className="sync-summary-grid">
        <div className="sync-summary-row">
          <dt>{t("syncSummary.pulled")}</dt>
          <dd>
            {pulled.length === 0 ? (
              <span className="sync-muted">—</span>
            ) : (
              <ul className="sync-summary-list">
                {pulled.map(({ source, detail }) => (
                  <li key={source}>
                    <strong>{source}</strong>: {detail}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
        <div className="sync-summary-row">
          <dt>{t("syncSummary.pushed")}</dt>
          <dd>
            {result.pushed
              ? formatPushed(result.pushed, t("syncSummary.noPush"))
              : "—"}
          </dd>
        </div>
        <div className="sync-summary-row">
          <dt>{t("syncSummary.conflicts")}</dt>
          <dd>
            {conflictCount > 0 ? (
              <span className="sync-warning">
                {t("syncSummary.unresolved", { count: conflictCount })}
              </span>
            ) : (
              <span className="sync-muted">{t("syncSummary.none")}</span>
            )}
          </dd>
        </div>
        {errorCount > 0 && (
          <div className="sync-summary-row">
            <dt>{t("syncSummary.errors")}</dt>
            <dd className="sync-error">{result.errors!.join("; ")}</dd>
          </div>
        )}
      </dl>

      <button
        type="button"
        className="ghost sync-raw-toggle"
        onClick={() => setShowRaw((v) => !v)}
        aria-expanded={showRaw}
      >
        {showRaw ? t("syncSummary.hideRaw") : t("syncSummary.showRaw")}
      </button>
      {showRaw && (
        <div className="result-panel" aria-label={t("syncSummary.rawAria")}>
          {JSON.stringify(result, null, 2)}
        </div>
      )}
    </div>
  );
}
