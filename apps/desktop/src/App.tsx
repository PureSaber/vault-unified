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

type Page = "list" | "add" | "sync" | "settings" | "conflicts";

const IDLE_MS = 15 * 60 * 1000;
const CONFLICT_POLL_MS = 60_000;

function AppShell() {
  const { t, locale, setLocale } = useI18n();
  const [unlocked, setUnlocked] = useState(hasToken());
  const [page, setPage] = useState<Page>("list");
  const [editEntry, setEditEntry] = useState<Entry | null>(null);
  const [conflictCount, setConflictCount] = useState(0);
  const idleTimer = useRef<number | null>(null);

  const lockToUnlock = useCallback(() => {
    lockApp();
    setUnlocked(false);
    setEditEntry(null);
    setPage("list");
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
      return;
    }
    refreshConflicts();
    const id = window.setInterval(refreshConflicts, CONFLICT_POLL_MS);
    return () => window.clearInterval(id);
  }, [unlocked, refreshConflicts, page]);

  useEffect(() => {
    if (!unlocked) return;

    const resetIdle = () => {
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
      idleTimer.current = window.setTimeout(async () => {
        try {
          await api.lock();
        } catch {
          /* ignore */
        }
        lockToUnlock();
      }, IDLE_MS);
    };

    const events = ["mousemove", "mousedown", "keydown", "touchstart", "scroll"] as const;
    events.forEach((ev) => window.addEventListener(ev, resetIdle, { passive: true }));
    resetIdle();

    return () => {
      events.forEach((ev) => window.removeEventListener(ev, resetIdle));
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
    };
  }, [unlocked, lockToUnlock]);

  async function handleLock() {
    try {
      await api.lock();
    } catch {
      /* ignore */
    }
    lockToUnlock();
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
              onClick={() => {
                if (id === "add") setEditEntry(null);
                setPage(id);
                if (id === "conflicts" || id === "sync") refreshConflicts();
              }}
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
              setPage("add");
            }}
            onOpenConflicts={() => setPage("conflicts")}
          />
        )}
        {page === "add" && (
          <EntryForm
            entry={editEntry}
            onDone={() => {
              setEditEntry(null);
              setPage("list");
            }}
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
