import { useState } from "react";
import { api, Entry, hasToken } from "./api/client";
import { ToastProvider } from "./components/Toast";
import SkipLink from "./components/SkipLink";
import Unlock, { lockApp } from "./pages/Unlock";
import VaultList from "./pages/VaultList";
import EntryForm from "./pages/EntryForm";
import SyncPanel from "./pages/SyncPanel";
import Settings from "./pages/Settings";
import ConflictModal from "./pages/ConflictModal";

type Page = "list" | "add" | "sync" | "settings" | "conflicts";

const NAV: { id: Page; label: string }[] = [
  { id: "list", label: "Vault" },
  { id: "add", label: "Add" },
  { id: "sync", label: "Sync" },
  { id: "conflicts", label: "Conflicts" },
  { id: "settings", label: "Settings" },
];

function AppShell() {
  const [unlocked, setUnlocked] = useState(hasToken());
  const [page, setPage] = useState<Page>("list");
  const [editEntry, setEditEntry] = useState<Entry | null>(null);

  async function handleLock() {
    try {
      await api.lock();
    } catch {
      /* ignore */
    }
    lockApp();
    setUnlocked(false);
  }

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
        <h1>Vault Unified</h1>
        <nav className="nav" aria-label="Main navigation">
          {NAV.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              className={page === id ? "active" : ""}
              onClick={() => {
                if (id === "add") setEditEntry(null);
                setPage(id);
              }}
              aria-current={page === id ? "page" : undefined}
            >
              {label}
            </button>
          ))}
          <button type="button" className="nav-lock" onClick={handleLock}>
            Lock
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
        {page === "sync" && <SyncPanel />}
        {page === "settings" && <Settings />}
        {page === "conflicts" && <ConflictModal />}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AppShell />
    </ToastProvider>
  );
}
