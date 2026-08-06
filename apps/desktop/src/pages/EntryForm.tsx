import { useState } from "react";
import { api, Entry } from "../api/client";

interface Props {
  entry?: Entry | null;
  onDone: () => void;
}

export default function EntryForm({ entry, onDone }: Props) {
  const [title, setTitle] = useState(entry?.title || "");
  const [username, setUsername] = useState(entry?.username || "");
  const [password, setPassword] = useState(entry?.password || "");
  const [url, setUrl] = useState(entry?.url || "");
  const [notes, setNotes] = useState(entry?.notes || "");
  const [error, setError] = useState("");

  async function handleGenerate() {
    const res = await api.generate(20);
    setPassword(res.password);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      if (entry) {
        await api.updateEntry(entry.id, { title, username, password, url, notes });
      } else {
        await api.createEntry({ title, username, password, url, notes });
      }
      onDone();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="card">
      <h2>{entry ? "Edit Entry" : "Add Entry"}</h2>
      <form onSubmit={handleSave}>
        <label>Title</label>
        <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        <label>Username</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} />
        <label>Password</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ flex: 1 }}
          />
          <button type="button" className="secondary" onClick={handleGenerate}>
            Generate
          </button>
        </div>
        <label>URL</label>
        <input value={url} onChange={(e) => setUrl(e.target.value)} />
        <label>Notes</label>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        {error && <div className="error">{error}</div>}
        <button className="primary" type="submit">
          Save
        </button>
        <button className="secondary" type="button" onClick={onDone} style={{ marginLeft: 8 }}>
          Cancel
        </button>
      </form>
    </div>
  );
}
