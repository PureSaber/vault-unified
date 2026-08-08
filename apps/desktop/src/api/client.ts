const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8765/api";

let token: string | null = localStorage.getItem("vault_token");
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

function headers(): HeadersInit {
  const h: HeadersInit = {
    "Content-Type": "application/json",
    "X-Vault-Client": "vault-unified-desktop",
  };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

function formatDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return JSON.stringify(item);
      })
      .filter(Boolean)
      .join("; ");
  }
  if (detail != null && typeof detail === "object") {
    return JSON.stringify(detail);
  }
  return fallback;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...headers(), ...(options.headers || {}) },
  });
  if (!res.ok) {
    if (res.status === 401) {
      clearToken();
      onUnauthorized?.();
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatDetail(err.detail, res.statusText));
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export interface Entry {
  id: string;
  title: string;
  username: string;
  password: string;
  url: string;
  notes: string;
  source: string;
  tags: string[];
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
  enabled_sources?: string[] | null;
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
  unlockKeyring: () =>
    request<{ token: string }>("/auth/unlock-keyring", { method: "POST" }),
  lock: () => request("/auth/lock", { method: "POST" }),
  authStatus: () => request<{ unlocked: boolean }>("/auth/status"),
  checkKeyring: () =>
    request<{ has_saved_password: boolean }>("/auth/check-keyring"),
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
  generate: (length = 20, symbols = true) =>
    request<{ password: string }>(
      `/entries/tools/generate?length=${length}&symbols=${symbols}`
    ),
  status: () => request<{ components: Record<string, string> }>("/status"),
  getPrefs: () => request<SyncPrefs>("/sync/preferences"),
  savePrefs: (prefs: Partial<SyncPrefs>) =>
    request<SyncPrefs>("/sync/preferences", {
      method: "PUT",
      body: JSON.stringify(prefs),
    }),
  sync: () => request("/sync", { method: "POST" }),
  push: () => request("/sync/push", { method: "POST" }),
  pullSource: (source: string) =>
    request(`/sync/pull/${encodeURIComponent(source)}`, { method: "POST" }),
  listConflicts: (reveal = false) =>
    request<Record<string, unknown>[]>(
      reveal ? "/sync/conflicts?reveal=true" : "/sync/conflicts"
    ),
  /** @deprecated prefer listConflicts */
  conflicts: (reveal = false) =>
    request<Record<string, unknown>[]>(
      reveal ? "/sync/conflicts?reveal=true" : "/sync/conflicts"
    ),
  resolveConflict: (id: string, choice: string, merged?: Record<string, unknown>) =>
    request(`/sync/conflicts/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ choice, merged }),
    }),
};
