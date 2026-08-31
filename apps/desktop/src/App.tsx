import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  clearToken,
  Entry,
  hasToken,
  setUnauthorizedHandler,
} from "./api/client";
import { I18nProvider, useI18n } from "./i18n";
import { ToastProvider } from "./components/Toast";
import SkipLink from "./components/SkipLink";
import Unlock, { lockApp } from "./pages/Unlock";
import VaultList from "./pages/VaultList";
import EntryForm from "./pages/EntryForm";
import SyncPanel from "./pages/SyncPanel";
import Settings from "./pages/Settings";
import ConflictModal from "./pages/ConflictModal";
import { useToast } from "./components/Toast";
import ConfirmDialog from "./components/ConfirmDialog";

type Page = "list" | "add" | "sync" | "settings" | "conflicts";
type PendingAction = { kind: "navigate"; page: Page } | { kind: "lock" };

const DEFAULT_IDLE_SECONDS = 15 * 60;
const CONFLICT_POLL_MS = 60_000;
const MAINTENANCE_POLL_MS = 60_000;

function AppShell() {
  const { t, locale, setLocale } = useI18n();
  const { showToast } = useToast();
  const [unlocked, setUnlocked] = useState(hasToken());
  const [page, setPage] = useState<Page>("list");
  const [editEntry, setEditEntry] = useState<Entry | null>(null);
  const [conflictCount, setConflictCount] = useState(0);
  const [lockAfterSeconds, setLockAfterSeconds] = useState(DEFAULT_IDLE_SECONDS);
  const [editorDirty, setEditorDirty] = useState(false);
  const [editorSaving, setEditorSaving] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [idleCountdown, setIdleCountdown] = useState<number | null>(null);
  const idleTimer = useRef<number | null>(null);
  const idleWarningTimer = useRef<number | null>(null);
  const idleCountdownTimer = useRef<number | null>(null);
  const deliveredMaintenanceNotices = useRef(new Set<string>());

  const lockToUnlock = useCallback(() => {
    lockApp();
    setUnlocked(false);
    setEditEntry(null);
    setPage("list");
    setEditorDirty(false);
    setEditorSaving(false);
    setPendingAction(null);
    setIdleCountdown(null);
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
    let cancelled = false;
    const runMaintenance = async () => {
      try {
        const result = await api.runMaintenance();
        if (cancelled) return;
        setLockAfterSeconds(result.settings.lock_after_seconds);
        const conflicts = Number(result.components.conflicts || "0");
        if (Number.isFinite(conflicts)) setConflictCount(conflicts);
        for (const notice of result.notices) {
          if (deliveredMaintenanceNotices.current.has(notice.code)) continue;
          deliveredMaintenanceNotices.current.add(notice.code);
          showToast(notice.message, notice.level === "error" ? "error" : "info");
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

  function requestNavigation(target: Page, force = false) {
    if (editorSaving && !force) {
      showToast(locale === "zh" ? "正在保存，请等待完成" : "Save in progress; please wait", "info");
      return;
    }
    if (editorDirty && !force) {
      setPendingAction({ kind: "navigate", page: target });
      return;
    }
    setEditorDirty(false);
    setEditEntry(null);
    setPage(target);
    if (target === "conflicts" || target === "sync") void refreshConflicts();
  }

  function handleLock() {
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

  function confirmDiscard() {
    const action = pendingAction;
    setPendingAction(null);
    setEditorDirty(false);
    setEditEntry(null);
    if (action?.kind === "lock") {
      void performLock();
    } else if (action?.kind === "navigate") {
      setPage(action.page);
      if (action.page === "conflicts" || action.page === "sync") void refreshConflicts();
    }
  }

  const navItems: { id: Page; label: string }[] = [
    { id: "list", label: t("nav.vault") },
    { id: "add", label: t("nav.add") },
    { id: "sync", label: t("nav.sync") },
    { id: "conflicts", label: t("nav.conflicts") },
    { id: "settings", label: t("nav.settings") },
  ];

  if (!unlocked) {
    return (
      <div className="app">
        <Unlock onUnlock={() => setUnlocked(true)} />
      </div>
    );
  }

  return (
    <div className="app">
      <SkipLink />
      <header className="header">
        <h1>{t("app.title")}</h1>
        <div className="header-locale" role="group" aria-label={t("lang.label")}>
          <button
            type="button"
            className={locale === "zh" ? "active" : ""}
            onClick={() => setLocale("zh")}
            aria-pressed={locale === "zh"}
          >
            {t("lang.zh")}
          </button>
          <button
            type="button"
            className={locale === "en" ? "active" : ""}
            onClick={() => setLocale("en")}
            aria-pressed={locale === "en"}
          >
            {t("lang.en")}
          </button>
        </div>
        <nav className="nav" aria-label={t("nav.main")}>
          {navItems.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              className={page === id ? "active" : ""}
              onClick={() => requestNavigation(id)}
              aria-current={page === id ? "page" : undefined}
            >
              {label}
              {id === "conflicts" && conflictCount > 0 && (
                <span className="nav-badge" title={t("nav.conflictBadge", { count: conflictCount })}>
                  {conflictCount}
                </span>
              )}
            </button>
          ))}
          <button type="button" className="nav-lock" onClick={handleLock}>
            {t("nav.lock")}
          </button>
        </nav>
      </header>
      <main className="main" id="main-content">
        {page === "list" && (
          <VaultList
            onEdit={(e) => {
              setEditEntry(e);
              setEditorDirty(false);
              setPage("add");
            }}
            onOpenConflicts={() => setPage("conflicts")}
          />
        )}
        {page === "add" && (
          <EntryForm
            entry={editEntry}
            onDirtyChange={setEditorDirty}
            onSavingChange={setEditorSaving}
            onDone={(saved) => requestNavigation("list", Boolean(saved))}
          />
        )}
        {page === "sync" && (
          <SyncPanel
            onOpenConflicts={() => {
              refreshConflicts();
              setPage("conflicts");
            }}
            onSyncDone={refreshConflicts}
          />
        )}
        {page === "settings" && <Settings />}
        {page === "conflicts" && (
          <ConflictModal onResolved={refreshConflicts} />
        )}
      </main>
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
        title={locale === "zh" ? "放弃未保存的更改？" : "Discard unsaved changes?"}
        message={locale === "zh" ? "未保存的字段、附件更改和历史恢复草稿都会被清除，保险库不会发生写入。" : "Unsaved fields, attachment changes, and history restore drafts will be cleared without writing to the vault."}
        confirmLabel={locale === "zh" ? "放弃更改" : "Discard changes"}
        cancelLabel={locale === "zh" ? "继续编辑" : "Keep editing"}
        variant="danger"
        onConfirm={confirmDiscard}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <ToastProvider>
        <AppShell />
      </ToastProvider>
    </I18nProvider>
  );
}
