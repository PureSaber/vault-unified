import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useToast } from "../components/Toast";

interface Conflict {
  id: string;
  title: string;
  default_choice: string;
  local: Record<string, string>;
  remote: Record<string, string>;
  remote_source: string;
}

const FIELDS = ["title", "username", "password", "url", "notes"] as const;

function FieldRows(
  data: Record<string, string>,
  other: Record<string, string>,
  maskPassword = false
) {
  return FIELDS.map((key) => {
    const value = data[key] || "";
    const otherVal = other[key] || "";
    const isDiff = value !== otherVal;
    const display =
      key === "password" && !maskPassword && value
        ? value
        : key === "password" && value
          ? "••••••••"
          : value || "—";
    return (
      <div
        key={key}
        className={`conflict-field${isDiff ? " is-diff" : ""}`}
      >
        <span className="conflict-field-label">{key}</span>
        <span className="conflict-field-value">{display}</span>
      </div>
    );
  });
}

export default function ConflictModal() {
  const { showToast } = useToast();
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  async function load() {
    try {
      setError("");
      const data = await api.conflicts();
      setConflicts(data as unknown as Conflict[]);
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function resolve(id: string, choice: string) {
    try {
      await api.resolveConflict(id, choice);
      showToast(`Conflict resolved (${choice})`);
      load();
    } catch (err) {
      showToast(String(err), "error");
    }
  }

  function toggleReveal(id: string) {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (error) {
    return <div className="error" role="alert">{error}</div>;
  }

  if (!conflicts.length) {
    return (
      <div className="card empty-state">
        No conflicts. All entries are in sync with your primary source.
      </div>
    );
  }

  return (
    <div>
      <p className="field-hint" style={{ marginBottom: "var(--space-lg)" }}>
        Highlighted fields differ between local and remote. Default choice follows your primary source.
      </p>
      {conflicts.map((c) => (
        <article className="card conflict-card" key={c.id}>
          <div className="conflict-header">
            <h3>{c.title}</h3>
            <button
              type="button"
              className="ghost"
              onClick={() => toggleReveal(c.id)}
              aria-pressed={revealed.has(c.id)}
            >
              {revealed.has(c.id) ? "Hide passwords" : "Show passwords"}
            </button>
          </div>
          <div className="conflict-grid">
            <div
              className={`conflict-panel${c.default_choice === "local" ? " is-primary" : ""}`}
            >
              <h4>Local vault{c.default_choice === "local" ? " (recommended)" : ""}</h4>
              {FieldRows(c.local, c.remote, !revealed.has(c.id))}
            </div>
            <div
              className={`conflict-panel${c.default_choice === "remote" ? " is-primary" : ""}`}
            >
              <h4>
                {c.remote_source}
                {c.default_choice === "remote" ? " (recommended)" : ""}
              </h4>
              {FieldRows(c.remote, c.local, !revealed.has(c.id))}
            </div>
          </div>
          <div className="conflict-actions">
            <button
              type="button"
              className={c.default_choice === "local" ? "primary" : "secondary"}
              onClick={() => resolve(c.id, "local")}
            >
              Keep local
            </button>
            <button
              type="button"
              className={c.default_choice === "remote" ? "primary" : "secondary"}
              onClick={() => resolve(c.id, "remote")}
            >
              Keep remote
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}
