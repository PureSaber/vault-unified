import { useEffect, useState } from "react";
import { api, clearToken, setToken } from "../api/client";
import { useI18n } from "../i18n";

interface Props {
  onUnlock: () => void;
}

export default function Unlock({ onUnlock }: Props) {
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasKeyring, setHasKeyring] = useState(false);
  const [keyringChecked, setKeyringChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .checkKeyring()
      .then((res) => {
        if (!cancelled) {
          setHasKeyring(!!res.has_saved_password);
          setKeyringChecked(true);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setKeyringChecked(true);
          const msg = String(err);
          setError(
            msg.includes("Failed to fetch") || msg.includes("NetworkError")
              ? t("unlock.apiUnreachable")
              : msg
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

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
        msg.includes("Failed to fetch") || msg.includes("NetworkError")
          ? t("unlock.apiUnreachable")
          : msg.replace(/^Error:\s*/, "")
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
      const msg = String(err);
      setError(
        msg.includes("Failed to fetch") || msg.includes("NetworkError")
          ? t("unlock.apiUnreachable")
          : msg.replace(/^Error:\s*/, "")
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="unlock-shell">
      <div className="unlock-card card">
        <h1>{t("app.title")}</h1>
        <p className="unlock-subtitle">{t("unlock.subtitle")}</p>
        <form onSubmit={handleUnlock} noValidate>
          <div className="field">
            <label className="field-label" htmlFor="master-password">
              {t("unlock.password")}
            </label>
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
            <span>{t("unlock.remember")}</span>
          </label>
          {error && (
            <div id="unlock-error" className="error" role="alert">
              {error}
            </div>
          )}
          <div className="button-row">
            <button className="primary" type="submit" disabled={loading}>
              {loading ? t("unlock.unlocking") : t("unlock.submit")}
            </button>
            {keyringChecked && hasKeyring && (
              <button
                className="secondary"
                type="button"
                onClick={handleKeyring}
                disabled={loading}
              >
                {t("unlock.useSaved")}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

export function lockApp() {
  clearToken();
}
