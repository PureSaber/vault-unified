import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n";

interface Conflict {
  id: string;
  title: string;
  default_choice: string;
  local: Record<string, string>;
  remote: Record<string, string>;
  remote_source: string;
}

const FIELDS = ["title", "username", "password", "url", "notes"] as const;
type Field = (typeof FIELDS)[number];
type Side = "local" | "remote";

interface Props {
  onResolved?: () => void;
}

export default function ConflictModal({ onResolved }: Props) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revealed, setRevealed] = useState<Set<string>>(new Set());
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [picks, setPicks] = useState<Record<string, Record<Field, Side>>>({});

  function defaultPicks(c: Conflict): Record<Field, Side> {
    const preferred: Side = c.default_choice === "remote" ? "remote" : "local";
    return {
      title: preferred,
      username: preferred,
      password: preferred,
      url: preferred,
      notes: preferred,
    };
  }

  async function load() {
    try {
      setError("");
      setLoading(true);
      const data = (await api.listConflicts(true)) as unknown as Conflict[];
      setConflicts(data);
      const next: Record<string, Record<Field, Side>> = {};
      for (const c of data) {
        next[c.id] = defaultPicks(c);
      }
      setPicks(next);
    } catch (err) {
      setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function resolve(id: string, choice: string, merged?: Record<string, unknown>) {
    setResolvingId(id);
    try {
      await api.resolveConflict(id, choice, merged);
      showToast(t("conflicts.resolved", { choice }));
      await load();
      onResolved?.();
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    } finally {
      setResolvingId(null);
    }
  }

  function resolveMerge(c: Conflict) {
    const pick = picks[c.id] || defaultPicks(c);
    const merged: Record<string, unknown> = { ...c.local };
    for (const field of FIELDS) {
      merged[field] = pick[field] === "remote" ? c.remote[field] : c.local[field];
    }
    return resolve(c.id, "merge", merged);
  }

  function toggleReveal(id: string) {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function setFieldPick(conflictId: string, field: Field, side: Side) {
    setPicks((prev) => ({
      ...prev,
      [conflictId]: {
        ...(prev[conflictId] || {
          title: "local",
          username: "local",
          password: "local",
          url: "local",
          notes: "local",
        }),
        [field]: side,
      },
    }));
  }

  function displayValue(key: Field, value: string, showPassword: boolean) {
    if (key === "password" && value && !showPassword) return "••••••••";
    return value || "—";
  }

  if (loading) {
    return <div className="loading-state">{t("conflicts.loading")}</div>;
  }

  if (error) {
    return (
      <div className="error" role="alert">
        {error}
      </div>
    );
  }

  if (!conflicts.length) {
    return (
      <div className="card empty-state">
        <h2 className="empty-state-title">{t("conflicts.title")}</h2>
        <p className="empty-state-hint">{t("conflicts.empty")}</p>
      </div>
    );
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>{t("conflicts.title")}</h2>
      <p className="field-hint" style={{ marginBottom: "var(--space-lg)" }}>
        {t("conflicts.hint")}
      </p>
      {conflicts.map((c) => {
        const showPw = revealed.has(c.id);
        const busy = resolvingId === c.id;
        const pick = picks[c.id] || defaultPicks(c);
        return (
          <article className="card conflict-card" key={c.id}>
            <div className="conflict-header">
              <h3>{c.title}</h3>
              <button
                type="button"
                className="ghost"
                onClick={() => toggleReveal(c.id)}
                aria-pressed={showPw}
                disabled={busy}
              >
                {showPw ? t("conflicts.hidePasswords") : t("conflicts.showPasswords")}
              </button>
            </div>
            <div className="conflict-grid">
              <div
                className={`conflict-panel${c.default_choice === "local" ? " is-primary" : ""}`}
              >
                <h4>
                  {t("conflicts.local")}
                  {c.default_choice === "local" ? t("conflicts.recommended") : ""}
                </h4>
                {FIELDS.map((key) => {
                  const value = c.local[key] || "";
                  const otherVal = c.remote[key] || "";
                  const isDiff = value !== otherVal;
                  return (
                    <div key={key} className={`conflict-field${isDiff ? " is-diff" : ""}`}>
                      <span className="conflict-field-label">{key}</span>
                      <span className="conflict-field-value">
                        {displayValue(key, value, showPw)}
                      </span>
                    </div>
                  );
                })}
              </div>
              <div
                className={`conflict-panel${c.default_choice === "remote" ? " is-primary" : ""}`}
              >
                <h4>
                  {c.remote_source}
                  {c.default_choice === "remote" ? t("conflicts.recommended") : ""}
                </h4>
                {FIELDS.map((key) => {
                  const value = c.remote[key] || "";
                  const otherVal = c.local[key] || "";
                  const isDiff = value !== otherVal;
                  return (
                    <div key={key} className={`conflict-field${isDiff ? " is-diff" : ""}`}>
                      <span className="conflict-field-label">{key}</span>
                      <span className="conflict-field-value">
                        {displayValue(key, value, showPw)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="conflict-field-picks">
              <p className="section-title">{t("conflicts.fieldPick")}</p>
              {FIELDS.map((field) => (
                <div className="conflict-pick-row" key={field}>
                  <span className="conflict-field-label">{field}</span>
                  <div className="conflict-pick-btns">
                    <button
                      type="button"
                      className={pick[field] === "local" ? "primary" : "secondary"}
                      disabled={busy}
                      onClick={() => setFieldPick(c.id, field, "local")}
                    >
                      {t("conflicts.pickLocal")}
                    </button>
                    <button
                      type="button"
                      className={pick[field] === "remote" ? "primary" : "secondary"}
                      disabled={busy}
                      onClick={() => setFieldPick(c.id, field, "remote")}
                    >
                      {t("conflicts.pickRemote")}
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="conflict-actions">
              <button
                type="button"
                className={c.default_choice === "local" ? "primary" : "secondary"}
                disabled={busy}
                onClick={() => resolve(c.id, "local")}
              >
                {busy ? t("conflicts.resolving") : t("conflicts.keepLocal")}
              </button>
              <button
                type="button"
                className={c.default_choice === "remote" ? "primary" : "secondary"}
                disabled={busy}
                onClick={() => resolve(c.id, "remote")}
              >
                {t("conflicts.useRemote")}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => resolveMerge(c)}
              >
                {t("conflicts.resolveMerge")}
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );
}
