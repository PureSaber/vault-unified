import { useState } from "react";
import { api, clearToken, setToken } from "../api/client";

interface Props {
  onUnlock: () => void;
}

export default function Unlock({ onUnlock }: Props) {
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");

  async function handleUnlock(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const res = await api.unlock(password, remember);
      setToken(res.token);
      onUnlock();
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleKeyring() {
    setError("");
    try {
      const res = await api.unlockKeyring();
      setToken(res.token);
      onUnlock();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="card" style={{ margin: "80px auto" }}>
      <h2>Unlock Vault</h2>
      <form onSubmit={handleUnlock}>
        <label>Master Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
        <label>
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
          />{" "}
          Remember on this PC
        </label>
        {error && <div className="error">{error}</div>}
        <button className="primary" type="submit">
          Unlock
        </button>
      </form>
      <p style={{ marginTop: 16 }}>
        <button className="secondary" type="button" onClick={handleKeyring}>
          Use saved password
        </button>
      </p>
    </div>
  );
}

export function lockApp() {
  clearToken();
}
