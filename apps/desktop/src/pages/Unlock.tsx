import { useEffect, useState } from "react";
import { api, clearToken, setToken, type VaultInfo } from "../api/client";
import { useI18n } from "../i18n";

interface Props {
  onUnlock: () => void;
}

type SetupMode = "create" | "restore";

const firstRunCopy = {
  zh: {
    loading: "检查本地保险库…",
    missingTitle: "开始使用 Vault Unified",
    missingHint: "未找到本地保险库。请选择创建新的 v3 保险库，或从已有加密备份恢复。",
    createTab: "创建新保险库",
    restoreTab: "从备份恢复",
    confirmPassword: "再次输入主密码",
    create: "创建并解锁",
    creating: "正在创建…",
    createHint: "新保险库默认使用 Argon2id + AES-256-GCM 的 Vault Format v3。不会迁移或覆盖任何已有文件。",
    restorePath: "加密备份文件路径",
    restorePlaceholder: "例如 D:\\Backups\\secrets.vault.bak.1234",
    restore: "验证、恢复并解锁",
    restoring: "正在验证和恢复…",
    restoreHint: "恢复前会完整验证密码和文件结构；目标位置已有保险库时会拒绝覆盖。",
    currentPath: "保险库位置",
    currentFormat: "格式",
    unreadable: "保险库文件无法识别，请先使用恢复工具处理。",
    mismatch: "两次输入的主密码不一致。",
    passwordRequired: "请输入主密码。",
    backupRequired: "请输入备份文件路径。",
  },
  en: {
    loading: "Checking the local vault…",
    missingTitle: "Get started with Vault Unified",
    missingHint: "No local vault was found. Create a new v3 vault or restore an encrypted backup.",
    createTab: "Create new vault",
    restoreTab: "Restore backup",
    confirmPassword: "Confirm master password",
    create: "Create and unlock",
    creating: "Creating…",
    createHint: "New vaults use Vault Format v3 with Argon2id and AES-256-GCM. Existing files are never migrated or overwritten.",
    restorePath: "Encrypted backup file path",
    restorePlaceholder: "e.g. D:\\Backups\\secrets.vault.bak.1234",
    restore: "Validate, restore, and unlock",
    restoring: "Validating and restoring…",
    restoreHint: "The backup password and structure are fully validated first. Restore refuses to overwrite an active vault.",
    currentPath: "Vault path",
    currentFormat: "Format",
    unreadable: "The vault file is unreadable. Use the recovery tools before opening it.",
    mismatch: "The master-password confirmation does not match.",
    passwordRequired: "Enter a master password.",
    backupRequired: "Enter a backup file path.",
  },
} as const;

export default function Unlock({ onUnlock }: Props) {
  const { t, locale } = useI18n();
  const copy = firstRunCopy[locale];
  const [info, setInfo] = useState<VaultInfo | null>(null);
  const [mode, setMode] = useState<SetupMode>("create");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [backupPath, setBackupPath] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasKeyring, setHasKeyring] = useState(false);
  const [keyringChecked, setKeyringChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .vaultInfo()
      .then(async (vaultInfo) => {
        if (cancelled) return;
        setInfo(vaultInfo);
        if (!vaultInfo.exists) {
          setKeyringChecked(true);
          return;
        }
        try {
          const res = await api.checkKeyring();
          if (!cancelled) setHasKeyring(!!res.has_saved_password);
        } finally {
          if (!cancelled) setKeyringChecked(true);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setKeyringChecked(true);
        const msg = String(err);
        setError(
          msg.includes("Failed to fetch") || msg.includes("NetworkError")
            ? t("unlock.apiUnreachable")
            : msg.replace(/^Error:\s*/, "")
        );
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  function normalizeError(err: unknown) {
    const msg = String(err);
    return msg.includes("Failed to fetch") || msg.includes("NetworkError")
      ? t("unlock.apiUnreachable")
      : msg.replace(/^Error:\s*/, "");
  }

  function finish(token: string) {
    setToken(token);
    onUnlock();
  }

  async function handleUnlock(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.unlock(password, remember);
      finish(res.token);
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!password) {
      setError(copy.passwordRequired);
      return;
    }
    if (password !== confirmPassword) {
      setError(copy.mismatch);
      return;
    }
    setLoading(true);
    try {
      const res = await api.createVault(password, confirmPassword, remember);
      finish(res.token);
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleRestore(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!backupPath.trim()) {
      setError(copy.backupRequired);
      return;
    }
    if (!password) {
      setError(copy.passwordRequired);
      return;
    }
    setLoading(true);
    try {
      const res = await api.restoreVault(backupPath.trim(), password, remember);
      finish(res.token);
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleKeyring() {
    setError("");
    setLoading(true);
    try {
      const res = await api.unlockKeyring();
      finish(res.token);
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setLoading(false);
    }
  }

  if (!info && !error) {
    return (
      <div className="unlock-shell">
        <div className="unlock-card card">
          <h1>{t("app.title")}</h1>
          <p className="unlock-subtitle">{copy.loading}</p>
        </div>
      </div>
    );
  }

  const vaultMissing = info?.exists === false;
  const vaultUnreadable = info?.format === "unreadable";

  return (
    <div className="unlock-shell">
      <div className="unlock-card card">
        <h1>{vaultMissing ? copy.missingTitle : t("app.title")}</h1>
        <p className="unlock-subtitle">
          {vaultMissing ? copy.missingHint : t("unlock.subtitle")}
        </p>

        {info && (
          <div className="field-hint" style={{ marginBottom: "var(--space-lg)" }}>
            <div><strong>{copy.currentFormat}:</strong> {info.format}</div>
            <div className="mono"><strong>{copy.currentPath}:</strong> {info.path}</div>
          </div>
        )}

        {vaultUnreadable ? (
          <div className="error" role="alert">
            {copy.unreadable}
          </div>
        ) : vaultMissing ? (
          <>
            <div className="button-row" role="group" aria-label={copy.missingTitle}>
              <button
                type="button"
                className={mode === "create" ? "primary" : "secondary"}
                onClick={() => {
                  setMode("create");
                  setError("");
                  setPassword("");
                }}
              >
                {copy.createTab}
              </button>
              <button
                type="button"
                className={mode === "restore" ? "primary" : "secondary"}
                onClick={() => {
                  setMode("restore");
                  setError("");
                  setPassword("");
                }}
              >
                {copy.restoreTab}
              </button>
            </div>

            {mode === "create" ? (
              <form onSubmit={handleCreate} noValidate>
                <div className="field">
                  <label className="field-label" htmlFor="create-master-password">
                    {t("unlock.password")}
                  </label>
                  <input
                    id="create-master-password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoFocus
                    autoComplete="new-password"
                    required
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="confirm-master-password">
                    {copy.confirmPassword}
                  </label>
                  <input
                    id="confirm-master-password"
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    autoComplete="new-password"
                    required
                  />
                </div>
                <p className="field-hint">{copy.createHint}</p>
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                  />
                  <span>{t("unlock.remember")}</span>
                </label>
                <p className="unlock-remember-hint">{t("unlock.rememberHint")}</p>
                {error && <div className="error" role="alert">{error}</div>}
                <div className="button-row">
                  <button className="primary" type="submit" disabled={loading}>
                    {loading ? copy.creating : copy.create}
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleRestore} noValidate>
                <div className="field">
                  <label className="field-label" htmlFor="backup-path">
                    {copy.restorePath}
                  </label>
                  <input
                    id="backup-path"
                    value={backupPath}
                    onChange={(e) => setBackupPath(e.target.value)}
                    placeholder={copy.restorePlaceholder}
                    autoFocus
                    autoComplete="off"
                    required
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="restore-master-password">
                    {t("unlock.password")}
                  </label>
                  <input
                    id="restore-master-password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="current-password"
                    required
                  />
                </div>
                <p className="field-hint">{copy.restoreHint}</p>
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                  />
                  <span>{t("unlock.remember")}</span>
                </label>
                <p className="unlock-remember-hint">{t("unlock.rememberHint")}</p>
                {error && <div className="error" role="alert">{error}</div>}
                <div className="button-row">
                  <button className="primary" type="submit" disabled={loading}>
                    {loading ? copy.restoring : copy.restore}
                  </button>
                </div>
              </form>
            )}
          </>
        ) : (
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
            <p className="unlock-remember-hint">{t("unlock.rememberHint")}</p>
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
        )}
      </div>
    </div>
  );
}

export function lockApp() {
  clearToken();
}
