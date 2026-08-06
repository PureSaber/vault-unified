import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function SyncPanel() {
  const [status, setStatus] = useState<Record<string, string>>({});
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  async function loadStatus() {
    const res = await api.status();
    setStatus(res.components);
  }

  useEffect(() => {
    loadStatus();
  }, []);

  async function runSync() {
    setError("");
    try {
      const res = await api.sync();
      setResult(JSON.stringify(res, null, 2));
      loadStatus();
    } catch (err) {
      setError(String(err));
    }
  }

  async function runPush() {
    setError("");
    try {
      const res = await api.push();
      setResult(JSON.stringify(res, null, 2));
      loadStatus();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="card">
      <h2>Sync</h2>
      <div style={{ marginBottom: 16 }}>
        {Object.entries(status).map(([k, v]) => (
          <div key={k}>
            <strong>{k}</strong>: {v}
          </div>
        ))}
      </div>
      <button className="primary" onClick={runSync}>
        Bidirectional Sync
      </button>
      <button className="secondary" onClick={runPush} style={{ marginLeft: 8 }}>
        Push Dirty
      </button>
      {error && <div className="error">{error}</div>}
      {result && (
        <pre style={{ marginTop: 16, background: "#0f1419", padding: 12, borderRadius: 8 }}>
          {result}
        </pre>
      )}
    </div>
  );
}
