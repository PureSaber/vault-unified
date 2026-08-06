import { useEffect, useState } from "react";
import { api, Entry } from "../api/client";

interface Props {
  onEdit: (entry: Entry) => void;
}

export default function VaultList({ onEdit }: Props) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  async function load(q?: string) {
    try {
      setEntries(await api.listEntries(q));
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCopy(id: string) {
    await api.copy(id);
    alert("Password copied!");
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this entry?")) return;
    await api.deleteEntry(id);
    load(query);
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          placeholder="Search..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(query)}
        />
        <button className="secondary" onClick={() => load(query)}>
          Search
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {entries.map((e) => (
        <div className="entry-row" key={e.id}>
          <div className="title">{e.title}</div>
          <div className="meta">{e.username || "-"}</div>
          <span className="badge">{e.source}</span>
          <span className="badge">{e.sync_status}</span>
          <button className="secondary" onClick={() => handleCopy(e.id)}>
            Copy
          </button>
          <button className="secondary" onClick={() => onEdit(e)}>
            Edit
          </button>
          <button className="secondary" onClick={() => handleDelete(e.id)}>
            Delete
          </button>
        </div>
      ))}
    </div>
  );
}
