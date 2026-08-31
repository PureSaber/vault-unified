import { useEffect, useMemo, useRef, useState } from "react";
import { api, Entry } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "../components/Toast";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ConfirmDialog from "../components/ConfirmDialog";

interface Props {
  onAdd: () => void;
  onEdit: (entry: Entry) => void;
}

function maskPassword(hasPassword: boolean) {
  return hasPassword ? "••••••••" : "—";
}

export default function VaultList({ onAdd, onEdit }: Props) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revealedPasswords, setRevealedPasswords] = useState<Record<string, string>>({});
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string } | null>(null);
  const debounceRef = useRef<number | null>(null);
  const requestSequence = useRef(0);
  const revealTimers = useRef(new Map<string, number>());

  async function load(q?: string) {
    const sequence = ++requestSequence.current;
    try {
      setError("");
      setLoading(true);
      const nextEntries = await api.listEntries(q);
      if (sequence !== requestSequence.current) return;
      setEntries(nextEntries);
    } catch (err) {
      if (sequence !== requestSequence.current) return;
      setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }

  function hideAllPasswords() {
    for (const timer of revealTimers.current.values()) window.clearTimeout(timer);
    revealTimers.current.clear();
    setRevealedPasswords({});
  }

  useEffect(() => {
    void load();
  }, []);

  const initialSearch = useRef(true);
  useEffect(() => {
    if (initialSearch.current) {
      initialSearch.current = false;
      return;
    }
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      void load(query.trim() || undefined);
    }, 250);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query]);

  useEffect(() => {
    const handleBlur = () => hideAllPasswords();
    const handleVisibility = () => {
      if (document.visibilityState !== "visible") hideAllPasswords();
    };
    window.addEventListener("blur", handleBlur);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("blur", handleBlur);
      document.removeEventListener("visibilitychange", handleVisibility);
      for (const timer of revealTimers.current.values()) window.clearTimeout(timer);
      revealTimers.current.clear();
    };
  }, []);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return entries;
    return entries.filter((entry) =>
      [entry.title, entry.username, entry.url, ...(entry.tags || [])]
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    );
  }, [entries, query]);

  async function toggleReveal(id: string) {
    if (revealedPasswords[id] != null) {
      hideAllPasswords();
      return;
    }
    try {
      const entry = await api.getEntry(id, true);
      hideAllPasswords();
      setRevealedPasswords({ [id]: entry.password || "" });
      const timer = window.setTimeout(() => {
        setRevealedPasswords((previous) => {
          const next = { ...previous };
          delete next[id];
          return next;
        });
        revealTimers.current.delete(id);
      }, 30_000);
      revealTimers.current.set(id, timer);
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function handleCopy(id: string) {
    try {
      await api.copy(id);
      showToast(t("list.copiedPass"));
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function handleCopyUsername(id: string) {
    try {
      await api.copy(id, "username");
      showToast(t("list.copiedUser"));
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const { id } = pendingDelete;
    setPendingDelete(null);
    try {
      await api.deleteEntry(id);
      showToast(t("list.deleted"));
      void load(query.trim() || undefined);
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  return (
    <div>
      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("list.deleteTitle")}
        message={pendingDelete ? t("list.deleteMessage", { title: pendingDelete.title }) : ""}
        confirmLabel={t("list.delete")}
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      <div className="page-heading-row">
        <div>
          <h2>{t("list.title")}</h2>
          <p className="field-hint">{t("list.subtitle")}</p>
        </div>
        <button className="primary" type="button" onClick={onAdd}>
          {t("list.addPassword")}
        </button>
      </div>

      <div className="list-toolbar">
        <input
          id="vault-search"
          placeholder={t("list.searchPlaceholder")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label={t("list.searchAria")}
        />
      </div>

      {error && <div className="error" role="alert">{error}</div>}

      {loading && !error ? (
        <LoadingSkeleton />
      ) : filtered.length === 0 && !error ? (
        <div className="empty-state card">
          <p className="empty-state-title">{query ? t("list.noResults") : t("list.emptyTitle")}</p>
          <p className="empty-state-hint">{query ? t("list.noResultsHint") : t("list.emptyHint")}</p>
          {!query && (
            <button className="primary" type="button" onClick={onAdd}>
              {t("list.addFirstPassword")}
            </button>
          )}
        </div>
      ) : (
        <ul className="entry-list" aria-label={t("list.entriesAria")}>
          {filtered.map((entry) => {
            const revealed = revealedPasswords[entry.id] != null;
            return (
              <li className="entry-row" key={entry.id}>
                <button
                  type="button"
                  className="entry-open"
                  onClick={() => onEdit(entry)}
                  aria-label={t("list.openEntry", { title: entry.title })}
                >
                  <span className="entry-title">{entry.title}</span>
                  <span className="entry-meta">
                    <span className="entry-username">{entry.username || t("list.noUsername")}</span>
                    <span className="entry-password-preview" aria-label={t("list.passwordAria")}>
                      {revealed ? revealedPasswords[entry.id] || "—" : maskPassword(entry.has_password)}
                    </span>
                    {entry.sync_status === "dirty" && (
                      <span className="badge badge-sync-dirty">{t("list.waitingSync")}</span>
                    )}
                    {entry.sync_status === "conflict" && (
                      <span className="badge badge-sync-conflict">{t("list.changedBothPlaces")}</span>
                    )}
                  </span>
                  {entry.tags?.length > 0 && (
                    <span className="entry-chips">
                      {entry.tags.map((tag) => <span className="chip" key={`tag-${tag}`}>{tag}</span>)}
                    </span>
                  )}
                </button>
                <div className="entry-actions">
                  <button type="button" className="primary" onClick={() => handleCopy(entry.id)}>
                    {t("list.copyPass")}
                  </button>
                  <details className="entry-more">
                    <summary>{t("list.moreActions")}</summary>
                    <div className="entry-more-menu">
                      <button type="button" className="ghost" onClick={() => toggleReveal(entry.id)}>
                        {revealed ? t("list.hidePassword") : t("list.showPassword")}
                      </button>
                      <button type="button" className="ghost" onClick={() => handleCopyUsername(entry.id)}>
                        {t("list.copyUser")}
                      </button>
                      <button type="button" className="ghost" onClick={() => onEdit(entry)}>
                        {t("list.edit")}
                      </button>
                      <button
                        type="button"
                        className="danger"
                        onClick={() => setPendingDelete({ id: entry.id, title: entry.title })}
                      >
                        {t("list.delete")}
                      </button>
                    </div>
                  </details>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
