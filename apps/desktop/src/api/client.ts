import { invoke } from "@tauri-apps/api/core";

interface ApiRuntimeConfig {
  base_url: string;
  bootstrap_secret: string;
  instance_id: string;
}

let runtimeConfigPromise: Promise<ApiRuntimeConfig> | null = null;
let token: string | null = null;
try {
  localStorage.removeItem("vault_token");
} catch {
  // Ignore storage access failures; tokens are never persisted by this version.
}
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

function validateRuntimeConfig(config: ApiRuntimeConfig): ApiRuntimeConfig {
  const baseUrl = config.base_url.replace(/\/+$/, "");
  let parsed: URL;
  try {
    parsed = new URL(baseUrl);
  } catch {
    throw new Error("Vault sidecar returned an invalid API URL");
  }
  if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1") {
    throw new Error("Vault sidecar must use an authenticated loopback endpoint");
  }
  if (!config.bootstrap_secret || config.bootstrap_secret.length < 32) {
    throw new Error("Vault sidecar bootstrap secret is missing or too short");
  }
  if (!config.instance_id) {
    throw new Error("Vault sidecar instance identity is missing");
  }
  return {
    ...config,
    base_url: baseUrl,
  };
}

async function loadRuntimeConfig(): Promise<ApiRuntimeConfig> {
  try {
    const config = await invoke<ApiRuntimeConfig>("get_api_runtime_config");
    return validateRuntimeConfig(config);
  } catch (tauriError) {
    const baseUrl = import.meta.env.VITE_API_URL?.trim();
    const bootstrapSecret = import.meta.env.VITE_API_BOOTSTRAP_SECRET?.trim();
    if (!baseUrl || !bootstrapSecret) {
      const detail = tauriError instanceof Error ? `: ${tauriError.message}` : "";
      throw new Error(`Secure Vault sidecar runtime is unavailable${detail}`);
    }
    return validateRuntimeConfig({
      base_url: baseUrl,
      bootstrap_secret: bootstrapSecret,
      instance_id: import.meta.env.VITE_API_INSTANCE_ID?.trim() || "vite-development",
    });
  }
}

function runtimeConfig(): Promise<ApiRuntimeConfig> {
  if (!runtimeConfigPromise) {
    runtimeConfigPromise = loadRuntimeConfig();
  }
  return runtimeConfigPromise;
}

export function setToken(value: string) {
  token = value;
}

export function clearToken() {
  token = null;
  try {
    localStorage.removeItem("vault_token");
  } catch {
    // Ignore storage access failures.
  }
}

export function hasToken() {
  return !!token;
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
  const config = await runtimeConfig();
  const requestHeaders = new Headers(options.headers);
  requestHeaders.set("Content-Type", "application/json");
  requestHeaders.set("X-Vault-Bootstrap", config.bootstrap_secret);
  requestHeaders.set("X-Vault-Client", "vault-unified-desktop");
  if (token) requestHeaders.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${config.base_url}${path}`, {
    ...options,
    headers: requestHeaders,
  });
  if (!res.ok) {
    if (res.status === 401 && token) {
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

export interface VaultInfo {
  exists: boolean;
  format: "missing" | "legacy" | "v3" | "unreadable";
  path: string;
}

export interface Entry {
  id: string;
  title: string;
  username: string;
  password: string;
  url: string;
  notes: string;
  has_password: boolean;
  has_notes: boolean;
  source: string;
  tags: string[];
  sync_status: string;
  linked_sources: Record<string, string>;
}

export interface IntegrationField {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  value: string;
  present: boolean;
  origin: string;
}

export interface Integration {
  source: string;
  label: string;
  configured: boolean;
  cli_installed: boolean;
  fields: IntegrationField[];
}

export interface IntegrationTestResult {
  source: string;
  configured: boolean;
  available: boolean;
  message: string;
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

export const api = {
  vaultInfo: () => request<VaultInfo>("/auth/vault-info"),
  createVault: (password: string, confirmPassword: string, remember = false) =>
    request<{ token: string }>("/auth/create", {
      method: "POST",
      body: JSON.stringify({
        password,
        confirm_password: confirmPassword,
        remember,
      }),
    }),
  restoreVault: (backupPath: string, password: string, remember = false) =>
    request<{ token: string }>("/auth/restore", {
      method: "POST",
      body: JSON.stringify({ backup_path: backupPath, password, remember }),
    }),
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
  integrations: () => request<Integration[]>("/integrations"),
  saveIntegration: (
    source: string,
    values: Record<string, string>,
    clear: string[] = []
  ) =>
    request<Integration>(`/integrations/${encodeURIComponent(source)}`, {
      method: "PUT",
      body: JSON.stringify({ values, clear }),
    }),
  clearIntegration: (source: string) =>
    request<Integration>(`/integrations/${encodeURIComponent(source)}`, {
      method: "DELETE",
    }),
  testIntegration: (source: string) =>
    request<IntegrationTestResult>(
      `/integrations/${encodeURIComponent(source)}/test`,
      { method: "POST" }
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
