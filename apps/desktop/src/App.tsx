import { useCallback, useEffect, useRef, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import {
  api,
  clearToken,
  Entry,
  hasToken,
  setUnauthorizedHandler,
  type BackupSummary,
} from "./api/client";
import { maintenanceMessage } from "./i18n/errors";
import { backupHealth, withStoredBackupStatus } from "./components/backup-health";
import { I18nProvider, useI18n } from "./i18n";
import { ToastProvider } from "./components/Toast";
import SkipLink from "./components/SkipLink";
import Unlock, { lockApp } from "./pages/Unlock";
import VaultList from "./pages/VaultList";
import EntryForm from "./pages/EntryForm";
import Settings from "./pages/Settings";
import ConflictModal from "./pages/ConflictModal";
import Connections from "./pages/Connections";
import SecurityRecovery from "./pages/SecurityRecovery";
import { useToast } from "./components/Toast";
import ConfirmDialog from "./components/ConfirmDialog";
import ImportWizard from "./components/ImportWizard";
import QuickSearch from "./components/QuickSearch";
import PersonalSyncRunner from "./components/PersonalSyncRunner";
import PasskeyRequests from "./components/PasskeyRequests";
import HelloOffer from "./components/HelloOffer";
import BrowserConnectRequests from "./components/BrowserConnectRequests";
import Sharing from "./pages/Sharing";
import ItemDetail from "./components/ItemDetail";
import Icon from "./components/Icon";
import { AppearanceProvider } from "./components/Appearance";
import { cancelHello, desktopReady, desktopStatus, exitDesktop, saveDesktopPreferences, type DesktopStatus } from "./desktop";

type TopPage = "passwords" | "security" | "connections" | "sharing" | "settings";
type Page = TopPage | "details" | "editor" | "conflicts" | "import";
type PendingAction =
  | { kind: "navigate"; page: Page; entry?: Entry }
  | { kind: "lock" }
  | { kind: "close" };

const DEFAULT_IDLE_SECONDS = 15 * 60;
const CONFLICT_POLL_MS = 60_000;
const MAINTENANCE_POLL_MS = 60_000;

function AppShell() {
  const { t, locale } = useI18n();
  const { showToast } = useToast();
  const [unlocked, setUnlocked] = useState(hasToken());
  const [page, setPage] = useState<Page>("passwords");
  const [editEntry, setEditEntry] = useState<Entry | null>(null);
  const [shareEntryId, setShareEntryId] = useState("");
  const [conflictCount, setConflictCount] = useState(0);
  const [backupSummary, setBackupSummary] = useState<BackupSummary | null>(null);
  const [lockAfterSeconds, setLockAfterSeconds] = useState(DEFAULT_IDLE_SECONDS);
  const [editorDirty, setEditorDirty] = useState(false);
  const [editorSaving, setEditorSaving] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [idleCountdown, setIdleCountdown] = useState<number | null>(null);
  const [quickSearch, setQuickSearch] = useState(false);
  const [passkeyPending, setPasskeyPending] = useState(false);
  const [helloOffer, setHelloOffer] = useState(false);
  const closeHelloOffer = useCallback(() => setHelloOffer(false), []);
  const [connectPending, setConnectPending] = useState(false);
  const [desktop, setDesktop] = useState<DesktopStatus | null>(null);
  const pendingQuickSearch = useRef(false);
  const nativeHandlers = useRef({ search: () => {}, lock: () => {}, exit: () => {} });
  const updateCheckStarted = useRef(false);
  const idleTimer = useRef<number | null>(null);
  const idleWarningTimer = useRef<number | null>(null);
  const idleCountdownTimer = useRef<number | null>(null);
  const deliveredMaintenanceNotices = useRef(new Set<string>());
  // Read the language at notice time; changing it must not re-run maintenance
  // (trash purge and scheduled-backup checks).
  const localeRef = useRef(locale);
  localeRef.current = locale;

  const lockToUnlock = useCallback(() => {
    cancelHello();
    if (isTauri()) void api.cancelAutoType().catch(() => {});
    lockApp();
    setUnlocked(false);
    setEditEntry(null);
    setPage("passwords");
    setEditorDirty(false);
    setEditorSaving(false);
    setPendingAction(null);
    setIdleCountdown(null);
    setQuickSearch(false);
    setPasskeyPending(false);
    setHelloOffer(false);
    setBackupSummary(null);
    setShareEntryId("");
    window.dispatchEvent(new Event("vault-ui-locked"));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      lockToUnlock();
    });
    return () => setUnauthorizedHandler(null);
  }, [lockToUnlock]);

  useEffect(() => {
    if (!hasToken()) return;
    let cancelled = false;
    api
      .authStatus()
      .then((s) => {
        if (cancelled) return;
        if (!s.unlocked) {
          clearToken();
          setUnlocked(false);
        } else {
          setUnlocked(true);
        }
      })
      .catch(() => {
        if (cancelled) return;
        clearToken();
        setUnlocked(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshConflicts = useCallback(async () => {
    if (!hasToken() || !unlocked) return;
    try {
      const list = await api.listConflicts(false);
      setConflictCount(list.length);
    } catch {
      /* ignore */
    }
  }, [unlocked]);

  useEffect(() => {
    if (!unlocked) {
      setConflictCount(0);
      setLockAfterSeconds(DEFAULT_IDLE_SECONDS);
      deliveredMaintenanceNotices.current.clear();
      return;
    }
    refreshConflicts();
    const id = window.setInterval(refreshConflicts, CONFLICT_POLL_MS);
    return () => window.clearInterval(id);
  }, [unlocked, refreshConflicts, page]);

  useEffect(() => {
    if (!unlocked) return;
    let cancelled = false;
    let sequence = 0;
    const load = () => {
      const request = ++sequence;
      // The summary's last_success_at falls back to any verified file, including
      // per-write atomic copies; the stored status records only real backups.
      void Promise.all([api.backups(), api.getPersonalSettings()])
        .then(([summary, settings]) => { if (!cancelled && request === sequence) setBackupSummary(withStoredBackupStatus(summary, settings)); })
        .catch(() => { if (!cancelled && request === sequence) setBackupSummary(null); });
    };
    load();
    window.addEventListener("vault-security-status-changed", load);
    return () => { cancelled = true; window.removeEventListener("vault-security-status-changed", load); };
  }, [unlocked]);

  useEffect(() => {
    if (!unlocked) return;
    let cancelled = false;
    api.getPersonalSettings()
      .then((settings) => {
        if (!cancelled) setLockAfterSeconds(settings.lock_after_seconds);
      })
      .catch(() => {
        // The secure default remains active if personal settings cannot load.
      });
    return () => {
      cancelled = true;
    };
  }, [unlocked]);

  useEffect(() => {
    if (!unlocked) return;
    const onSettingsChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ lock_after_seconds?: number }>).detail;
      if (detail && Number.isFinite(detail.lock_after_seconds)) {
        setLockAfterSeconds(Number(detail.lock_after_seconds));
      }
    };
    window.addEventListener("vault-personal-settings-changed", onSettingsChanged);
    return () => window.removeEventListener("vault-personal-settings-changed", onSettingsChanged);
  }, [unlocked]);

  useEffect(() => {
    if (!unlocked) return;
    let cancelled = false;
    const runMaintenance = async () => {
      try {
        const result = await api.runMaintenance();
        if (cancelled) return;
        setLockAfterSeconds(result.settings.lock_after_seconds);
        const conflicts = Number(result.components.conflicts || "0");
        if (Number.isFinite(conflicts)) setConflictCount(conflicts);
        if (result.notices.some(notice => notice.code.startsWith("scheduled-backup"))) window.dispatchEvent(new Event("vault-security-status-changed"));
        for (const notice of result.notices) {
          if (notice.code.startsWith("sync-pending:")) continue;
          if (deliveredMaintenanceNotices.current.has(notice.code)) continue;
          deliveredMaintenanceNotices.current.add(notice.code);
          showToast(maintenanceMessage(notice.code, notice.message, localeRef.current), notice.level === "error" ? "error" : "info");
        }
      } catch {
        // Maintenance is best-effort; ordinary vault use must remain available.
      }
    };
    void runMaintenance();
    const id = window.setInterval(() => void runMaintenance(), MAINTENANCE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [unlocked, showToast]);

  const performLock = useCallback(async () => {
    try {
      await api.lock();
    } catch {
      /* ignore */
    }
    lockToUnlock();
  }, [lockToUnlock]);

  useEffect(() => {
    if (!desktop || updateCheckStarted.current) return;
    updateCheckStarted.current = true;
    if (desktop.preferences.check_updates) {
      void api.checkDesktopUpdate().then(value => {
        if (value) showToast(locale === "zh" ? `发现 ${value.version} 版，可在设置中查看更新。` : `Version ${value.version} is available in Settings.`, "info");
      }).catch(() => { /* Optional startup checks retry through the explicit Settings action. */ });
    }
  }, [desktop, locale, showToast]);

  useEffect(() => {
    if (!unlocked) return;

    const clearIdleTimers = () => {
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
      if (idleWarningTimer.current) window.clearTimeout(idleWarningTimer.current);
      if (idleCountdownTimer.current) window.clearInterval(idleCountdownTimer.current);
      idleTimer.current = null;
      idleWarningTimer.current = null;
      idleCountdownTimer.current = null;
    };

    const resetIdle = () => {
      clearIdleTimers();
      setIdleCountdown(null);
      const deadline = Date.now() + lockAfterSeconds * 1000;
      if (editorDirty) {
        const warningSeconds = Math.min(15, Math.max(5, lockAfterSeconds - 1));
        idleWarningTimer.current = window.setTimeout(() => {
          const updateCountdown = () => {
            setIdleCountdown(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
          };
          updateCountdown();
          idleCountdownTimer.current = window.setInterval(updateCountdown, 250);
        }, Math.max(0, lockAfterSeconds - warningSeconds) * 1000);
      }
      idleTimer.current = window.setTimeout(() => void performLock(), lockAfterSeconds * 1000);
    };

    const events = ["mousemove", "mousedown", "keydown", "touchstart", "scroll"] as const;
    events.forEach((eventName) => window.addEventListener(eventName, resetIdle, { passive: true }));
    resetIdle();

    return () => {
      events.forEach((eventName) => window.removeEventListener(eventName, resetIdle));
      clearIdleTimers();
    };
  }, [unlocked, lockAfterSeconds, editorDirty, performLock]);

  useEffect(() => {
    if (!editorDirty && !editorSaving) return;
    const guardReload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guardReload);
    return () => window.removeEventListener("beforeunload", guardReload);
  }, [editorDirty, editorSaving]);

  useEffect(() => {
    let cancelled = false;
    void desktopStatus().then(async value => {
      if (!value || cancelled) return;
      if (value.preferences.locale !== locale) {
        try { value = await saveDesktopPreferences({ ...value.preferences, locale }); } catch { /* Keep available controls when preferences cannot be saved. */ }
      }
      if (!cancelled) setDesktop(value);
    });
    return () => { cancelled = true; };
  }, [locale]);

  useEffect(() => {
    if (!isTauri()) return;
    let active = true;
    const stops: (() => void)[] = [];
    const subscribe = async (event: string, handler: () => void) => {
      const stop = await listen(event, handler);
      if (active) stops.push(stop); else stop();
    };
    void Promise.all([
      subscribe("desktop-quick-search", () => nativeHandlers.current.search()),
      subscribe("desktop-lock-requested", () => nativeHandlers.current.lock()),
      subscribe("desktop-exit-requested", () => nativeHandlers.current.exit()),
      subscribe("desktop-hidden", () => setQuickSearch(false)),
      subscribe("desktop-system-locked", () => { pendingQuickSearch.current = false; lockToUnlock(); }),
    ]).then(async () => { if (active && await desktopReady()) nativeHandlers.current.search(); }).catch(() => { /* Browser preview has no native event runtime. */ });
    return () => { active = false; stops.forEach(stop => stop()); };
  }, []);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key.toLowerCase() === "k" && !event.altKey && !event.metaKey && unlocked) {
        event.preventDefault();
        if (!pendingAction) setQuickSearch(value => !value);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [unlocked, pendingAction]);

  useEffect(() => {
    if (unlocked && pendingQuickSearch.current) { pendingQuickSearch.current = false; setQuickSearch(true); }
  }, [unlocked]);

  function requestNavigation(target: Page, force = false, entry?: Entry) {
    if (editorSaving && !force) {
      showToast(locale === "zh" ? "正在保存，请等待完成" : "Save in progress; please wait", "info");
      return;
    }
    if (editorDirty && !force) {
      setPendingAction({ kind: "navigate", page: target, entry });
      return;
    }
    setEditorDirty(false);
    setEditEntry(entry || null);
    setPage(target);
    if (target === "conflicts" || target === "connections") void refreshConflicts();
  }

  function handleLock() {
    setQuickSearch(false);
    if (editorSaving) {
      showToast(locale === "zh" ? "正在保存，请等待完成" : "Save in progress; please wait", "info");
      return;
    }
    if (editorDirty) {
      setPendingAction({ kind: "lock" });
      return;
    }
    void performLock();
  }

  function requestExit() {
    setQuickSearch(false);
    if (editorSaving) { showToast(locale === "zh" ? "正在保存，请等待完成后再退出" : "Save in progress; wait before quitting", "info"); return; }
    if (editorDirty) { setPendingAction({ kind: "close" }); return; }
    void exitDesktop().catch(() => showToast(locale === "zh" ? "退出失败，请重试" : "Could not quit. Try again.", "error"));
  }

  nativeHandlers.current = {
    search: () => { if (!unlocked) pendingQuickSearch.current = true; else if (!pendingAction && !connectPending) setQuickSearch(true); },
    lock: handleLock,
    exit: requestExit,
  };

  function openEntry(entry: Entry, mode: "details" | "editor" = "details") {
    setQuickSearch(false);
    requestNavigation(mode, false, entry);
  }

  function openSearchEntry(entry: Entry) { openEntry(entry); }

  function finishEditor(saved?: boolean) {
    if (saved) {
      window.dispatchEvent(new Event("vault-entries-changed"));
      setEditorSaving(false);
    }
    requestNavigation(editEntry ? "details" : "passwords", Boolean(saved), editEntry || undefined);
  }

  async function confirmDiscard() {
    const action = pendingAction;
    if (action?.kind === "close") {
      try {
        await exitDesktop();
      } catch {
        showToast(
          locale === "zh" ? "客户端未能关闭，草稿仍保留在当前窗口中" : "The app could not close; the draft remains in this window",
          "error",
        );
      }
      return;
    }
    setPendingAction(null);
    setEditorDirty(false);
    setEditEntry(null);
    if (action?.kind === "lock") {
      void performLock();
    } else if (action?.kind === "navigate") {
      setEditEntry(action.entry || null);
      setPage(action.page);
      if (action.page === "conflicts" || action.page === "connections") void refreshConflicts();
    }
  }

  const navItems: { id: TopPage; label: string }[] = [
    { id: "passwords", label: t("nav.passwords") },
    { id: "security", label: t("nav.securityRecovery") },
    { id: "connections", label: t("nav.connections") },
    { id: "sharing", label: locale === "zh" ? "分享" : "Sharing" },
    { id: "settings", label: t("nav.settings") },
  ];

  const activePage = ["editor", "details", "import", "conflicts"].includes(page) ? "passwords" : page;

  if (!unlocked) {
    return (
      <div className="app">
        <Unlock onUnlock={method => { setUnlocked(true); setHelloOffer(method === "master"); }} />
      </div>
    );
  }

  return (
    <div className="app app-workbench">
      <SkipLink />
      <header className="header">
        <h1><span className="brand-icon"><Icon name="vault" /></span><span>{t("app.title")}</span></h1>
        <nav className="nav" aria-label={t("nav.main")}>
          {navItems.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              className={activePage === id ? "active" : ""}
              onClick={() => { setShareEntryId(""); requestNavigation(id); }}
              aria-current={activePage === id ? "page" : undefined}
            >
              <Icon name={id} /><span>{label}</span>
            </button>
          ))}
          <button type="button" onClick={() => setQuickSearch(true)} title="Ctrl+K"><Icon name="search" /><span>{locale === "zh" ? "快捷搜索" : "Quick search"}</span><kbd aria-hidden="true">Ctrl K</kbd></button>
          <button type="button" className="nav-lock" onClick={handleLock}>
            <Icon name="lock" /><span>{t("nav.lockNow")}</span>
          </button>
        </nav>
      </header>
      <main className={`main ${["passwords", "details", "editor"].includes(page) ? "main-passwords" : ""}`} id="main-content">
        {["passwords", "details", "editor"].includes(page) && (
          <>
            {conflictCount > 0 && (
              <div className="context-notice context-notice-warning" role="status">
                <span>{t("conflicts.contextNotice", { count: conflictCount })}</span>
                <button type="button" className="secondary" onClick={() => requestNavigation("conflicts")}>
                  {t("conflicts.review")}
                </button>
              </div>
            )}
            {backupSummary && !backupHealth(backupSummary).hasBackup && (
              <div className="context-notice context-notice-warning" role="status">
                <span>{backupHealth(backupSummary).configured
                  ? (locale === "zh" ? "自动备份已开启，尚未完成第一次成功备份。" : "Automatic backup is on; the first successful backup is still needed.")
                  : t("security.noBackupReminder")}</span>
                <button type="button" className="secondary" onClick={() => requestNavigation("security")}>
                  {t("security.setBackup")}
                </button>
              </div>
            )}
            <div className={`password-workspace ${page === "editor" ? "workspace-editing" : ""} ${editEntry ? "has-selection" : ""}`}>
              <section className="list-pane" aria-label={locale === "zh" ? "密码列表" : "Password list"}>
                <VaultList
                  selectedId={editEntry?.id}
                  active={page !== "editor"}
                  onAdd={() => requestNavigation("editor")}
                  onImport={() => requestNavigation("import")}
                  onOpen={entry => openEntry(entry)}
                  onEdit={entry => openEntry(entry, "editor")}
                />
              </section>
              <section className="detail-pane">
                {page === "editor" ? <EntryForm entry={editEntry} onDirtyChange={setEditorDirty} onSavingChange={setEditorSaving} onDone={finishEditor} />
                  : editEntry ? <ItemDetail key={editEntry.id} entry={editEntry} onEdit={entry => openEntry(entry, "editor")} onBack={() => requestNavigation("passwords")}
                    onShare={entry => { setShareEntryId(entry.id); requestNavigation("sharing"); }} />
                  : <div className="detail-empty"><span className="detail-empty-icon"><Icon name="vault" size={36} /></span><h2>{locale === "zh" ? "你的账号，井然有序" : "Your accounts, in one place"}</h2><p>{locale === "zh" ? "选择一个账号，查看详情并复制所需内容。" : "Select an account to view its details and copy what you need."}</p><span className="field-hint">{locale === "zh" ? "使用 Ctrl+K 快速查找" : "Use Ctrl+K to find an account quickly"}</span></div>}
              </section>
            </div>
          </>
        )}
        <PasskeyRequests onPendingChange={setPasskeyPending} />
        <BrowserConnectRequests paused={passkeyPending} onPendingChange={setConnectPending} />
        <PersonalSyncRunner paused={editorSaving || passkeyPending || ["editor", "import", "connections", "conflicts", "sharing"].includes(page)} onOpen={() => requestNavigation("connections")} />
        {page === "import" && (
          <div className="card">
            <button type="button" className="ghost page-back" onClick={() => requestNavigation("passwords")}>
              {locale === "zh" ? "返回密码" : "Back to passwords"}
            </button>
            <h2>{locale === "zh" ? "从浏览器导入" : "Import from browser"}</h2>
            <ImportWizard initialSource="chrome" onDone={() => requestNavigation("passwords")} />
          </div>
        )}
        {page === "security" && <SecurityRecovery onOpen={entry => openEntry(entry, "editor")} />}
        {page === "connections" && (
          <Connections
            conflictCount={conflictCount}
            onOpenConflicts={() => setPage("conflicts")}
            onSyncDone={refreshConflicts}
          />
        )}
        {page === "settings" && <Settings desktop={desktop} onDesktopChange={setDesktop} onExit={requestExit} onBusy={setEditorSaving} />}
        {page === "sharing" && <Sharing initialEntryId={shareEntryId} onDirtyChange={setEditorDirty} onSavingChange={setEditorSaving} />}
        {page === "conflicts" && (
          <>
            <button type="button" className="ghost page-back" onClick={() => setPage("passwords")}>
              {t("conflicts.backToPasswords")}
            </button>
            <ConflictModal onResolved={refreshConflicts} />
          </>
        )}
      </main>
      {quickSearch && <QuickSearch onClose={() => setQuickSearch(false)} onOpen={openSearchEntry} />}
      {helloOffer && <HelloOffer active={!quickSearch && !passkeyPending && !connectPending && !pendingAction && idleCountdown === null} onDone={closeHelloOffer} />}
      {idleCountdown !== null && editorDirty && (
        <div className="idle-lock-warning" role="alert" aria-live="assertive">
          {locale === "zh"
            ? `为保护未保存的密码草稿，应用将在 ${idleCountdown} 秒后锁定并清除草稿。继续操作可重置计时。`
            : `To protect this unsaved password draft, the app will lock and clear it in ${idleCountdown} seconds. Continue working to reset the timer.`}
        </div>
      )}
      <ConfirmDialog
        open={pendingAction !== null}
        idPrefix="unsaved-draft-confirm"
        title={pendingAction?.kind === "close"
          ? (locale === "zh" ? "放弃更改并关闭？" : "Discard changes and close?")
          : (locale === "zh" ? "放弃未保存的更改？" : "Discard unsaved changes?")}
        message={locale === "zh" ? "未保存的字段、附件更改和历史恢复草稿都会被清除，保险库不会发生写入。" : "Unsaved fields, attachment changes, and history restore drafts will be cleared without writing to the vault."}
        confirmLabel={pendingAction?.kind === "close"
          ? (locale === "zh" ? "放弃并关闭" : "Discard and close")
          : (locale === "zh" ? "放弃更改" : "Discard changes")}
        cancelLabel={locale === "zh" ? "继续编辑" : "Keep editing"}
        variant="danger"
        onConfirm={() => void confirmDiscard()}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <AppearanceProvider><ToastProvider>
        <AppShell />
      </ToastProvider></AppearanceProvider>
    </I18nProvider>
  );
}
