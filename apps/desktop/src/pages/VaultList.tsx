import { useEffect, useState } from "react";
import { api, Entry } from "../api/client";
import { useToast } from "../components/Toast";

interface Props {
  onEdit: (entry: Entry) => void;
}

function maskPassword(value: string) {
  if (!value) return "—";
  return "••••••••";
}

function syncBadgeClass(status: string) {
  if (status === "clean") return "badge badge-sync-clean";
  if (status === "conflict") return "badge badge-sync-conflict";
  if (status === "dirty" || status === "deleted_pending") return "badge badge-sync-dirty";
  return "badge";
}

export default function VaultList({ onEdit }: Props) {
  const { showToast } = useToast();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  async function load(q?: string) {
    try {
      setError("");
      setEntries(await api.listEntries(q));
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    load();
  }, []);

  function toggleReveal(id: string) {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleCopy(id: string) {
    try {
      await api.copy(id);
      showToast("Password copied to clipboard");
    } catch (err) {
      showToast(String(err), "error");
    }
  }

  async function handleCopyUsername(id: string) {
    try {
      await api.copy(id, "username");
      showToast("Username copied to clipboard");
    } catch (err) {
      showToast(String(err), "error");
    }
  }

  async function handleDelete(id: string, title: string) {
    if (!window.confirm(`Delete "${title}"? This cannot be undone from the vault UI.`)) return;
    try {
      await api.deleteEntry(id);
      showToast("Entry deleted");
      load(query);
    } catch (err) {
      showToast(String(err), "error");
    }
  }

  return (
    <div>
      <div className="list-toolbar">
        <input
          id="vault-search"
          placeholder="Search by title, username, or URL…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(query)}
          aria-label="Search vault"
        />
        <button className="secondary" type="button" onClick={() => load(query)}>
          Search
        </button>
      </div>

      {error && <div className="error" role="alert">{error}</div>}

      {entries.length === 0 && !error ? (
        <div className="empty-state card">No entries found. Add a credential or sync from an external source.</div>
      ) : (
        <ul className="entry-list" aria-label="Vault entries">
          {entries.map((e) => (
            <li className="entry-row" key={e.id}>
              <div className="entry-main">
                <p className="entry-title">{e.title}</p>
                <div className="entry-meta">
                  <span className="entry-username">{e.username || "No username"}</span>
                  <span className="entry-password-preview" aria-label="Password">
                    {revealed.has(e.id) ? e.password || "—" : maskPassword(e.password)}
                  </span>
                  <span className="badge badge-source">{e.source}</span>
                  <span className={syncBadgeClass(e.sync_status)}>{e.sync_status}</span>
                </div>
              </div>
              <div className="entry-actions">
                <button
                  type="button"
                  className="ghost icon-btn"
                  onClick={() => toggleReveal(e.id)}
                  aria-label={revealed.has(e.id) ? "Hide password" : "Show password"}
                  aria-pressed={revealed.has(e.id)}
                >
                  {revealed.has(e.id) ? "Hide" : "Show"}
                </button>
                <button type="button" className="secondary" onClick={() => handleCopy(e.id)}>
                  Copy pass
                </button>
                <button type="button" className="ghost" onClick={() => handleCopyUsername(e.id)}>
                  Copy user
                </button>
                <button type="button" className="secondary" onClick={() => onEdit(e)}>
                  Edit
                </button>
                <button
                  type="button"
                  className="danger"
                  onClick={() => handleDelete(e.id, e.title)}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
