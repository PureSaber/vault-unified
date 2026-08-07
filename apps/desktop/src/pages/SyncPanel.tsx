import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import SyncResultSummary, { type SyncResultData } from "../components/SyncResultSummary";

export default function SyncPanel() {
  const { showToast } = useToast();
  const [status, setStatus] = useState<Record<string, string>>({});
  const [result, setResult] = useState<SyncResultData | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadStatus() {
    try {
      const res = await api.status();
      setStatus(res.components);
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  async function runSync() {
    setError("");
    setBusy(true);
    try {
      const res = await api.sync();
      setResult(res as SyncResultData);
      showToast("Sync completed");
      loadStatus();
    } catch (err) {
      const msg = String(err);
      setError(msg);
      showToast(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  async function runPush() {
    setError("");
    setBusy(true);
    try {
      const res = await api.push();
      setResult(res as SyncResultData);
      showToast("Push completed");
      loadStatus();
    } catch (err) {
      const msg = String(err);
      setError(msg);
      showToast(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>Sync</h2>
      <p className="field-hint" style={{ marginBottom: "var(--space-xl)" }}>
        Pull from and push to enabled external sources. Configure which sources are active in
        Settings.
      </p>

      <p className="section-title">Connection status</p>
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

      <div className="button-row">
        <button className="primary" type="button" onClick={runSync} disabled={busy}>
          {busy ? "Running…" : "Bidirectional sync"}
        </button>
        <button className="secondary" type="button" onClick={runPush} disabled={busy}>
          Push dirty entries
        </button>
      </div>

      {error && <div className="error" role="alert">{error}</div>}

      {result && (
        <div style={{ marginTop: "var(--space-xl)" }}>
          <p className="section-title">Last operation</p>
          <SyncResultSummary result={result} />
        </div>
      )}
    </div>
  );
}
