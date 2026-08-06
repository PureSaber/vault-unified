import { useEffect, useState } from "react";
import { api } from "../api/client";

interface Conflict {
  id: string;
  title: string;
  default_choice: string;
  local: Record<string, string>;
  remote: Record<string, string>;
  remote_source: string;
}

export default function ConflictModal() {
  const [conflicts, setConflicts] = useState<Conflict[]>([]);

  async function load() {
    const data = await api.conflicts();
    setConflicts(data as Conflict[]);
  }

  useEffect(() => {
    load();
  }, []);

  async function resolve(id: string, choice: string) {
    await api.resolveConflict(id, choice);
    load();
  }

  if (!conflicts.length) {
    return <div className="card">No conflicts.</div>;
  }

  return (
    <div>
      {conflicts.map((c) => (
        <div className="card" key={c.id} style={{ marginBottom: 16 }}>
          <h3>{c.title}</h3>
          <div className="conflict-grid">
            <div className="conflict-panel">
              <h4>Local</h4>
              <pre>{JSON.stringify(c.local, null, 2)}</pre>
            </div>
            <div className="conflict-panel">
              <h4>{c.remote_source}</h4>
              <pre>{JSON.stringify(c.remote, null, 2)}</pre>
            </div>
          </div>
          <button
            className={c.default_choice === "local" ? "primary" : "secondary"}
            onClick={() => resolve(c.id, "local")}
          >
            Keep Local
          </button>
          <button
            className={c.default_choice === "remote" ? "primary" : "secondary"}
            onClick={() => resolve(c.id, "remote")}
            style={{ marginLeft: 8 }}
          >
            Keep Remote
          </button>
        </div>
      ))}
    </div>
  );
}
