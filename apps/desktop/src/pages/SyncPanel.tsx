import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import SyncResultSummary, { type SyncResultData } from "../components/SyncResultSummary";
import LoadingSkeleton from "../components/LoadingSkeleton";
import { useI18n } from "../i18n";

const PULL_SOURCES = ["proton_pass", "bitwarden", "keepassxc", "gopass"] as const;

interface Props {
  onOpenConflicts?: () => void;
  onSyncDone?: () => void;
}

export default function SyncPanel({ onOpenConflicts, onSyncDone }: Props) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [status, setStatus] = useState<Record<string, string>>({});
  const [statusLoading, setStatusLoading] = useState(true);
  const [result, setResult] = useState<SyncResultData | null>(null);
  const [error, setError] = useState("");
  const [syncBusy, setSyncBusy] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);
  const [pullBusy, setPullBusy] = useState<string | null>(null);

  async function loadStatus() {
    try {
      setStatusLoading(true);
      const res = await api.status();
      setStatus(res.components);
      setError("");
    } catch (err) {
      setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      setStatusLoading(false);
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  const conflictCount = result?.conflicts?.length ?? 0;
  const anyBusy = syncBusy || pushBusy || pullBusy != null;

  async function runSync() {
    setError("");
    setSyncBusy(true);
    try {
      const res = (await api.sync()) as SyncResultData;
      setResult(res);
      showToast(t("sync.completed"));
      loadStatus();
      onSyncDone?.();
    } catch (err) {
      const msg = String(err).replace(/^Error:\s*/, "");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setSyncBusy(false);
    }
  }

  async function runPush() {
    setError("");
    setPushBusy(true);
    try {
      const res = (await api.push()) as SyncResultData;
      setResult(res);
      showToast(t("sync.pushCompleted"));
      loadStatus();
      onSyncDone?.();
    } catch (err) {
      const msg = String(err).replace(/^Error:\s*/, "");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setPushBusy(false);
    }
  }

  async function runPull(source: string) {
    setError("");
    setPullBusy(source);
    try {
      const res = (await api.pullSource(source)) as SyncResultData;
      setResult({ pulled: { [source]: res as unknown as Record<string, number> } });
      showToast(t("sync.pullCompleted"));
      loadStatus();
      onSyncDone?.();
    } catch (err) {
      const msg = String(err).replace(/^Error:\s*/, "");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setPullBusy(null);
    }
  }

  return (
    <div className="card">
      <h2>{t("sync.title")}</h2>
      <p className="field-hint" style={{ marginBottom: "var(--space-xl)" }}>
        {t("sync.hint")}
      </p>

      <p className="section-title">{t("sync.connectionStatus")}</p>
      {statusLoading ? (
        <LoadingSkeleton rows={3} />
      ) : (
        <dl className="status-grid">
          {Object.entries(status).map(([key, value]) => {
            const disabled = value.includes("(disabled)");
            return (
              <div className={`status-row${disabled ? " status-row-disabled" : ""}`} key={key}>
                <dt>{key.replace(/_/g, " ")}</dt>
                <dd>{value}</dd>
              </div>
            );
          })}
        </dl>
      )}

      <div className="button-row">
        <button className="primary" type="button" onClick={runSync} disabled={anyBusy}>
          {syncBusy ? t("sync.syncing") : t("sync.bidirectional")}
        </button>
        <button className="secondary" type="button" onClick={runPush} disabled={anyBusy}>
          {pushBusy ? t("sync.pushing") : t("sync.pushDirty")}
        </button>
      </div>

      <p className="section-title" style={{ marginTop: "var(--space-xl)" }}>
        {t("sync.perSource")}
      </p>
      <div className="button-row" style={{ marginTop: 0 }}>
        {PULL_SOURCES.map((source) => {
          const statusVal = status[source] || "";
          const disabled = anyBusy || statusVal.includes("(disabled)");
          return (
            <button
              key={source}
              type="button"
              className="secondary"
              disabled={disabled}
              onClick={() => runPull(source)}
              title={t("sync.pullSource", { source })}
            >
              {pullBusy === source ? t("sync.pulling") : `${t("sync.pull")} ${source}`}
            </button>
          );
        })}
      </div>

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      {result && (
        <div style={{ marginTop: "var(--space-xl)" }}>
          <p className="section-title">{t("sync.lastOp")}</p>
          <SyncResultSummary result={result} />
          {conflictCount > 0 && onOpenConflicts && (
            <div className="button-row">
              <button type="button" className="primary" onClick={onOpenConflicts}>
                {t("sync.viewConflicts", { count: conflictCount })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
