import { useState } from "react";

export interface SyncResultData {
  pulled?: Record<string, Record<string, number>>;
  pushed?: Record<string, number>;
  conflicts?: unknown[];
  errors?: string[];
}

function formatPulled(pulled: Record<string, Record<string, number>>) {
  return Object.entries(pulled).map(([source, stats]) => {
    const parts = Object.entries(stats)
      .filter(([, n]) => n > 0)
      .map(([k, n]) => `${k}: ${n}`);
    return { source, detail: parts.length ? parts.join(", ") : "no changes" };
  });
}

function formatPushed(pushed: Record<string, number>) {
  const entries = Object.entries(pushed).filter(([, n]) => n > 0);
  if (!entries.length) return "No entries pushed";
  return entries.map(([k, n]) => `${k}: ${n}`).join(", ");
}

export default function SyncResultSummary({ result }: { result: SyncResultData }) {
  const [showRaw, setShowRaw] = useState(false);
  const pulled = result.pulled ? formatPulled(result.pulled) : [];
  const conflictCount = result.conflicts?.length ?? 0;
  const errorCount = result.errors?.length ?? 0;

  return (
    <div className="sync-summary">
      <dl className="sync-summary-grid">
        <div className="sync-summary-row">
          <dt>Pulled</dt>
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
          <dt>Pushed</dt>
          <dd>{result.pushed ? formatPushed(result.pushed) : "—"}</dd>
        </div>
        <div className="sync-summary-row">
          <dt>Conflicts</dt>
          <dd>
            {conflictCount > 0 ? (
              <span className="sync-warning">{conflictCount} unresolved</span>
            ) : (
              <span className="sync-muted">None</span>
            )}
          </dd>
        </div>
        {errorCount > 0 && (
          <div className="sync-summary-row">
            <dt>Errors</dt>
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
        {showRaw ? "Hide technical details" : "Show technical details"}
      </button>
      {showRaw && (
        <div className="result-panel" aria-label="Raw sync response">
          {JSON.stringify(result, null, 2)}
        </div>
      )}
    </div>
  );
}
