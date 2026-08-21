import { useEffect, useMemo, useRef, useState } from "react";
import { api, Entry } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "../components/Toast";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ConfirmDialog from "../components/ConfirmDialog";

interface Props {
  onEdit: (entry: Entry) => void;
  onOpenConflicts?: () => void;
}

function maskPassword(hasPassword: boolean) {
  return hasPassword ? "••••••••" : "—";
}

function syncBadgeClass(status: string) {
  if (status === "clean") return "badge badge-sync-clean";
  if (status === "conflict") return "badge badge-sync-conflict conflict-chip";
  if (status === "dirty" || status === "deleted_pending") return "badge badge-sync-dirty";
  return "badge";
}

export default function VaultList({ onEdit, onOpenConflicts }: Props) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revealedPasswords, setRevealedPasswords] = useState<Record<string, string>>({});
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string } | null>(
    null
  );
  const debounceRef = useRef<number | null>(null);

  async function load(q?: string) {
    try {
      setError("");
      setLoading(true);
      setEntries(await api.listEntries(q));
    } catch (err) {
      setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      setLoading(false);
    }
  }

  const initialLoad = useRef(true);

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (initialLoad.current) {
      initialLoad.current = false;
      return;
    }
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      load(query.trim() || undefined);
    }, 300);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => {
      const hay = [e.title, e.username, e.url, ...(e.tags || [])]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [entries, query]);

  async function toggleReveal(id: string) {
    if (revealedPasswords[id] != null) {
      setRevealedPasswords((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      return;
    }
    try {
      const entry = await api.getEntry(id, true);
      setRevealedPasswords((prev) => ({ ...prev, [id]: entry.password || "" }));
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
      load(query.trim() || undefined);
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  return (
    <div>
      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("list.deleteTitle")}
        message={
          pendingDelete
            ? t("list.deleteMessage", { title: pendingDelete.title })
            : ""
        }
        confirmLabel={t("list.delete")}
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
      <div className="list-toolbar">
        <input
          id="vault-search"
          placeholder={t("list.searchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(query.trim() || undefined)}
          aria-label={t("list.searchAria")}
        />
        <button
          className="secondary"
          type="button"
          onClick={() => load(query.trim() || undefined)}
        >
          {t("list.search")}
        </button>
      </div>

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      {loading && !error ? (
        <LoadingSkeleton />
      ) : filtered.length === 0 && !error ? (
        <div className="empty-state card">
          <p className="empty-state-title">{t("list.emptyTitle")}</p>
          <p className="empty-state-hint">{t("list.emptyHint")}</p>
        </div>
      ) : (
        <ul className="entry-list" aria-label={t("list.entriesAria")}>
          {filtered.map((e) => {
            const revealed = revealedPasswords[e.id] != null;
            const linked = Object.keys(e.linked_sources || {});
            return (
              <li className="entry-row" key={e.id}>
                <div className="entry-main">
                  <p className="entry-title">{e.title}</p>
                  <div className="entry-meta">
                    <span className="entry-username">
                      {e.username || t("list.noUsername")}
                    </span>
                    <span className="entry-password-preview" aria-label={t("list.passwordAria")}>
                      {revealed
                        ? revealedPasswords[e.id] || "—"
                        : maskPassword(e.has_password)}
                    </span>
                    <span className="badge badge-source">{e.source}</span>
                    {e.sync_status === "conflict" && onOpenConflicts ? (
                      <button
                        type="button"
                        className={`${syncBadgeClass(e.sync_status)} conflict-chip-btn`}
                        onClick={onOpenConflicts}
                      >
                        {t("list.conflictChip")}
                      </button>
                    ) : (
                      <span className={syncBadgeClass(e.sync_status)}>{e.sync_status}</span>
                    )}
                  </div>
                  {(e.tags?.length > 0 || linked.length > 0) && (
                    <div className="entry-chips">
                      {e.tags?.map((tag) => (
                        <span className="chip" key={`tag-${tag}`} title={t("list.tags")}>
                          {tag}
                        </span>
                      ))}
                      {linked.map((src) => (
                        <span className="chip chip-linked" key={`link-${src}`} title={t("list.linked")}>
                          {src}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="entry-actions">
                  <button
                    type="button"
                    className="ghost icon-btn"
                    onClick={() => toggleReveal(e.id)}
                    aria-label={revealed ? t("list.hidePassword") : t("list.showPassword")}
                    aria-pressed={revealed}
                  >
                    {revealed ? t("list.hide") : t("list.show")}
                  </button>
                  <button type="button" className="secondary" onClick={() => handleCopy(e.id)}>
                    {t("list.copyPass")}
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => handleCopyUsername(e.id)}
                  >
                    {t("list.copyUser")}
                  </button>
                  <button type="button" className="secondary" onClick={() => onEdit(e)}>
                    {t("list.edit")}
                  </button>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => setPendingDelete({ id: e.id, title: e.title })}
                  >
                    {t("list.delete")}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
