import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useToast } from "../components/Toast";

interface SyncResult {
  pulled?: Record<string, unknown>;
  pushed?: Record<string, unknown>;
  conflicts?: unknown[];
}

export default function SyncPanel() {
  const { showToast } = useToast();
  const [status, setStatus] = useState<Record<string, string>>({});
  const [result, setResult] = useState<SyncResult | null>(null);
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
      setResult(res as SyncResult);
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
      setResult(res as SyncResult);
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
        Pull from Proton Pass and Bitwarden, push local changes, and detect conflicts.
      </p>

      <p className="section-title">Connection status</p>
      <dl className="status-grid">
        {Object.entries(status).map(([key, value]) => (
          <div className="status-row" key={key}>
            <dt>{key.replace(/_/g, " ")}</dt>
            <dd>{value}</dd>
          </div>
        ))}
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
          <div className="result-panel">{JSON.stringify(result, null, 2)}</div>
        </div>
      )}
    </div>
  );
}
