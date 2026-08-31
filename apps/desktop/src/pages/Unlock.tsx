import { useEffect, useState } from "react";
import { api, clearToken, setToken, type RecoveryKitPreview, type StartupRestorePreview, type VaultInfo } from "../api/client";
import { useI18n } from "../i18n";
import PathPicker from "../components/PathPicker";
import ConfirmDialog from "../components/ConfirmDialog";

interface Props {
  onUnlock: () => void;
}

type SetupMode = "create" | "restore";

const firstRunCopy = {
  zh: {
    loading: "检查本地保险库…",
    missingTitle: "开始使用 Vault Unified",
    missingHint: "你可以创建新的密码库，或从已有的加密备份恢复。",
    createTab: "创建新保险库",
    restoreTab: "从备份恢复",
    confirmPassword: "再次输入主密码",
    create: "创建并解锁",
    creating: "正在创建…",
    createHint: "密码会在这台设备上加密保存。创建过程不会覆盖已有文件。",
    technicalDetails: "技术细节",
    hideTechnicalDetails: "隐藏技术细节",
    technicalCreate: "新密码库使用 Vault Format v3、Argon2id 和 AES-256-GCM。",
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
    recovery: "使用紧急恢复包",
    recoveryTitle: "从紧急恢复包恢复",
    recoveryHint: "这会用恢复包内容替换当前保险库，并自动保留替换前的加密副本。恢复码不会上传或保存。",
    recoveryKitPath: "恢复包文件路径",
    recoveryCode: "恢复码",
    newPassword: "新的主密码",
    recover: "恢复并解锁",
    recovering: "正在验证和恢复…",
    back: "返回",
    recoveryRequired: "请填写恢复包、恢复码和新的主密码。",
  },
  en: {
    loading: "Checking the local vault…",
    missingTitle: "Get started with Vault Unified",
    missingHint: "Create a new password vault or restore an existing encrypted backup.",
    createTab: "Create new vault",
    restoreTab: "Restore backup",
    confirmPassword: "Confirm master password",
    create: "Create and unlock",
    creating: "Creating…",
    createHint: "Passwords are stored encrypted on this device. Creation never overwrites an existing file.",
    technicalDetails: "Technical details",
    hideTechnicalDetails: "Hide technical details",
    technicalCreate: "New vaults use Vault Format v3, Argon2id, and AES-256-GCM.",
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
    recovery: "Use emergency recovery kit",
    recoveryTitle: "Recover from an emergency kit",
    recoveryHint: "This replaces the current vault with the kit contents and retains an encrypted pre-recovery copy. The recovery code is neither uploaded nor saved.",
    recoveryKitPath: "Recovery-kit file path",
    recoveryCode: "Recovery code",
    newPassword: "New master password",
    recover: "Recover and unlock",
    recovering: "Validating and recovering…",
    back: "Back",
    recoveryRequired: "Enter the recovery kit, recovery code, and a new master password.",
  },
} as const;

export default function Unlock({ onUnlock }: Props) {
  const { t, locale } = useI18n();
  const zh = locale === "zh";
  const copy = firstRunCopy[locale];
  const [info, setInfo] = useState<VaultInfo | null>(null);
  const [mode, setMode] = useState<SetupMode>("create");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [backupPath, setBackupPath] = useState("");
  const [showRecovery, setShowRecovery] = useState(false);
  const [recoveryKitPath, setRecoveryKitPath] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [newRecoveryPassword, setNewRecoveryPassword] = useState("");
  const [confirmRecoveryPassword, setConfirmRecoveryPassword] = useState("");
  const [restorePreview, setRestorePreview] = useState<StartupRestorePreview | null>(null);
  const [recoveryPreview, setRecoveryPreview] = useState<RecoveryKitPreview | null>(null);
  const [showTechnical, setShowTechnical] = useState(false);
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
      setRestorePreview(await api.previewVaultRestore(backupPath.trim(), password, remember));
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setLoading(false);
    }
  }

  async function applyRestore() {
    if (!restorePreview) return;
    const preview = restorePreview;
    setRestorePreview(null);
    setLoading(true);
    try {
      await api.applyVaultRestore(preview.preview_token, password, remember);
      clearToken();
      window.location.reload();
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

  async function handleRecovery(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!recoveryKitPath.trim() || !recoveryCode || !newRecoveryPassword) {
      setError(copy.recoveryRequired);
      return;
    }
    if (newRecoveryPassword !== confirmRecoveryPassword) {
      setError(copy.mismatch);
      return;
    }
    setLoading(true);
    try {
      setRecoveryPreview(await api.previewRecoveryKit(recoveryKitPath.trim(), recoveryCode));
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setLoading(false);
    }
  }

  async function applyRecovery() {
    if (!recoveryPreview) return;
    const preview = recoveryPreview;
    setRecoveryPreview(null);
    setLoading(true);
    try {
      await api.applyRecoveryKit(
        preview.preview_token,
        recoveryCode,
        newRecoveryPassword,
        confirmRecoveryPassword,
      );
      clearToken();
      window.location.reload();
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

        <button
          type="button"
          className="ghost"
          onClick={() => setShowTechnical((value) => !value)}
          aria-expanded={showTechnical}
        >
          {showTechnical ? copy.hideTechnicalDetails : copy.technicalDetails}
        </button>

        {info && showTechnical && (
          <div className="field-hint" style={{ marginBottom: "var(--space-lg)" }}>
            <div><strong>{copy.currentFormat}:</strong> {info.format}</div>
            <div className="mono"><strong>{copy.currentPath}:</strong> {info.path}</div>
            {vaultMissing && <div>{copy.technicalCreate}</div>}
          </div>
        )}

        {!showRecovery && !vaultMissing && (
          <div className="button-row" style={{ marginBottom: "var(--space-lg)" }}>
            <button type="button" className="secondary" onClick={() => { setShowRecovery(true); setError(""); }}>
              {copy.recovery}
            </button>
          </div>
        )}

        {showRecovery ? (
          <form onSubmit={handleRecovery} noValidate>
            <h2>{copy.recoveryTitle}</h2>
            <p className="field-hint">{copy.recoveryHint}</p>
            <PathPicker
              id="recovery-kit-path"
              label={copy.recoveryKitPath}
              mode="file"
              value={recoveryKitPath}
              onChange={setRecoveryKitPath}
              extensions={["vault"]}
              required
            />
            <div className="field">
              <label className="field-label" htmlFor="emergency-recovery-code">{copy.recoveryCode}</label>
              <input id="emergency-recovery-code" type="password" value={recoveryCode} onChange={(e) => setRecoveryCode(e.target.value)} autoComplete="off" required />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="new-recovery-password">{copy.newPassword}</label>
              <input id="new-recovery-password" type="password" value={newRecoveryPassword} onChange={(e) => setNewRecoveryPassword(e.target.value)} autoComplete="new-password" required />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="confirm-recovery-password">{copy.confirmPassword}</label>
              <input id="confirm-recovery-password" type="password" value={confirmRecoveryPassword} onChange={(e) => setConfirmRecoveryPassword(e.target.value)} autoComplete="new-password" required />
            </div>
            {error && <div className="error" role="alert">{error}</div>}
            <div className="button-row">
              <button className="primary" type="submit" disabled={loading}>
                {loading ? copy.recovering : copy.recover}
              </button>
              <button className="secondary" type="button" disabled={loading} onClick={() => { setShowRecovery(false); setError(""); }}>
                {copy.back}
              </button>
            </div>
          </form>
        ) : vaultUnreadable ? (
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
                <PathPicker
                  id="backup-path"
                  label={copy.restorePath}
                  mode="file"
                  value={backupPath}
                  onChange={setBackupPath}
                  placeholder={copy.restorePlaceholder}
                  required
                />
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
            <div className="button-row">
              <button type="button" className="ghost" onClick={() => { setShowRecovery(true); setError(""); }}>
                {copy.recovery}
              </button>
            </div>
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
      <ConfirmDialog
        open={restorePreview !== null}
        idPrefix="startup-restore-confirm"
        title={copy.restoreTab}
        message={restorePreview ? `${new Date(restorePreview.backup.modified_at).toLocaleString()} · ${restorePreview.backup.path} · ${(restorePreview.backup.size / 1024).toFixed(1)} KiB. ${restorePreview.impact}` : ""}
        confirmLabel={copy.restore}
        cancelLabel={zh ? "取消" : "Cancel"}
        variant="danger"
        onConfirm={() => void applyRestore()}
        onCancel={() => {
          if (restorePreview) void api.cancelVaultRestore(restorePreview.preview_token).catch(() => undefined);
          setRestorePreview(null);
          setPassword("");
        }}
      />
      <ConfirmDialog
        open={recoveryPreview !== null}
        idPrefix="recovery-kit-confirm"
        title={copy.recoveryTitle}
        message={recoveryPreview ? `${new Date(recoveryPreview.kit.modified_at).toLocaleString()} · ${recoveryPreview.kit.path} · ${recoveryPreview.kit.entry_count} ${zh ? "个条目" : "entries"}. ${recoveryPreview.impact}` : ""}
        confirmLabel={copy.recover}
        cancelLabel={zh ? "取消" : "Cancel"}
        variant="danger"
        onConfirm={() => void applyRecovery()}
        onCancel={() => {
          if (recoveryPreview) void api.cancelRecoveryKit(recoveryPreview.preview_token).catch(() => undefined);
          setRecoveryPreview(null);
          setRecoveryCode("");
          setNewRecoveryPassword("");
          setConfirmRecoveryPassword("");
        }}
      />
    </div>
  );
}

export function lockApp() {
  clearToken();
}
