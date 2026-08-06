const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8765/api";

let token: string | null = localStorage.getItem("vault_token");

function headers(): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers: headers() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export interface Entry {
  id: string;
  title: string;
  username: string;
  password: string;
  url: string;
  notes: string;
  source: string;
  sync_status: string;
  linked_sources: Record<string, string>;
}

export interface SyncPrefs {
  primary: string;
  auto_push_on_edit: boolean;
  auto_pull_on_sync: boolean;
  conflict_default: string;
  proton_vault_name: string;
  proton_share_id: string;
}

export function setToken(t: string) {
  token = t;
  localStorage.setItem("vault_token", t);
}

export function clearToken() {
  token = null;
  localStorage.removeItem("vault_token");
}

export function hasToken() {
  return !!token;
}

export const api = {
  unlock: (password: string, remember = false) =>
    request<{ token: string }>("/auth/unlock", {
      method: "POST",
      body: JSON.stringify({ password, remember }),
    }),
  unlockKeyring: () => request<{ token: string }>("/auth/unlock-keyring", { method: "POST" }),
  lock: () => request("/auth/lock", { method: "POST" }),
  checkKeyring: () => request<{ has_saved_password: boolean }>("/auth/check-keyring"),
  listEntries: (q?: string) =>
    request<Entry[]>(q ? `/entries?q=${encodeURIComponent(q)}` : "/entries"),
  getEntry: (id: string, reveal = true) =>
    request<Entry>(`/entries/${id}?reveal=${reveal}`),
  createEntry: (data: Partial<Entry>) =>
    request<Entry>("/entries", { method: "POST", body: JSON.stringify(data) }),
  updateEntry: (id: string, data: Partial<Entry>) =>
    request<Entry>(`/entries/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteEntry: (id: string) => request(`/entries/${id}`, { method: "DELETE" }),
  copy: (id: string, field = "password") =>
    request(`/entries/${id}/copy?field=${field}`, { method: "POST" }),
  generate: (length = 20) => request<{ password: string }>(`/entries/tools/generate?length=${length}`),
  status: () => request<{ components: Record<string, string> }>("/status"),
  getPrefs: () => request<SyncPrefs>("/sync/preferences"),
  savePrefs: (prefs: Partial<SyncPrefs>) =>
    request<SyncPrefs>("/sync/preferences", {
      method: "PUT",
      body: JSON.stringify(prefs),
    }),
  sync: () => request("/sync", { method: "POST" }),
  push: () => request("/sync/push", { method: "POST" }),
  conflicts: () => request<Record<string, unknown>[]>("/sync/conflicts"),
  resolveConflict: (id: string, choice: string, merged?: Record<string, unknown>) =>
    request(`/sync/conflicts/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ choice, merged }),
    }),
};
