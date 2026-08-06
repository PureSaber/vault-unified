import { useState } from "react";
import { api, clearToken, setToken } from "../api/client";

interface Props {
  onUnlock: () => void;
}

export default function Unlock({ onUnlock }: Props) {
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleUnlock(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.unlock(password, remember);
      setToken(res.token);
      onUnlock();
    } catch (err) {
      const msg = String(err);
      setError(
        msg.includes("Failed to fetch")
          ? "Cannot reach vault API. Ensure the app started the Python service (port 8765)."
          : msg
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleKeyring() {
    setError("");
    setLoading(true);
    try {
      const res = await api.unlockKeyring();
      setToken(res.token);
      onUnlock();
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="unlock-shell">
      <div className="unlock-card card">
        <h1>Vault Unified</h1>
        <p className="unlock-subtitle">Enter your master password to unlock the encrypted vault.</p>
        <form onSubmit={handleUnlock} noValidate>
          <div className="field">
            <label className="field-label" htmlFor="master-password">Master password</label>
            <input
              id="master-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              autoComplete="current-password"
              required
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "unlock-error" : undefined}
            />
          </div>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            <span>Remember on this PC (Windows Credential Manager)</span>
          </label>
          {error && (
            <div id="unlock-error" className="error" role="alert">
              {error}
            </div>
          )}
          <div className="button-row">
            <button className="primary" type="submit" disabled={loading}>
              {loading ? "Unlocking…" : "Unlock"}
            </button>
            <button
              className="secondary"
              type="button"
              onClick={handleKeyring}
              disabled={loading}
            >
              Use saved password
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function lockApp() {
  clearToken();
}
