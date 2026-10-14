import { invoke } from "@tauri-apps/api/core";

export interface GenerationOptions {
  kind: "password" | "passphrase"; length: number; symbols: boolean; digits: boolean;
  upper: boolean; lower: boolean; allowed: string; excluded: string; words: number; separator: "-" | " " | "." | "_";
}
export interface GeneratedPassword { id: string; kind: "password" | "passphrase"; created_at: number; origin: string }
export interface WebsiteRules { match: "exact" | "base_domain"; additional_urls: string[]; excluded_urls: string[] }
export interface HelloStatus { supported: boolean; ready: boolean; busy: boolean }
export interface TypeTarget { id: string; title: string; application: string }
export interface PasswordHealthItem { id: string; title: string; username: string; updated_at: string; change_url: string; weak: boolean; reused: boolean; reuse_count: number; score: number | null }
export interface PasswordHealthReport { checked_at: string; total: number; weak: number; reused: number; unscored: number; entries: PasswordHealthItem[] }
export interface PersonalSyncSetup { provider: "folder" | "webdav"; mode: "create" | "join"; location: string; label: string; automatic: boolean; code: string; username: string; password: string }
export interface PersonalSyncPreview { preview_token: string; items: Array<{ id: string; title: string; action: "add" | "update" | "remove" }>; total: number; conflicts: number; local_entries: number; result_entries: number; provider: string; location: string; automatic: boolean }
export interface PersonalSyncStatus { connected: boolean; reconnect?: boolean; upgrade_required?: boolean; generation: number; provider?: string; location?: string; label?: string; automatic?: boolean; disabled?: boolean; pending?: number; outbox?: number; conflicts?: number; pending_deletions?: number; devices?: Array<{ id: string; label: string; current: boolean }>; busy?: boolean; error?: string; last_success?: number; waiting?: number; more?: boolean }
export interface PersonalSyncResult { skipped?: boolean; busy?: boolean; waiting?: number; more?: boolean; downloaded?: number; uploaded?: number; conflicts?: number; changed?: boolean }
export interface PersonalSyncChoice { id: string; object: string; title: string; path: string[]; kind: string; device: string; local: { present: boolean; value: string; state?: string; truncated?: boolean }; remote: { present: boolean; value: string; state?: string; truncated?: boolean } }
export interface PersonalSyncConflicts { generation: number; items: PersonalSyncChoice[] }
export interface PasskeySummary { id: string; rp_id: string; rp_name: string; user_name: string; user_display_name: string; created_at: string }
export interface PasskeyRequest { id: string; operation: "create" | "get"; origin: string; rp_id: string; user_name: string; user_display_name: string; remaining_seconds: number; state: "pending" | "verifying"; choices: Array<{ entry_id: string; credential_id: string; title: string; user_name: string; user_display_name: string }> }
export type SharingAction = "share" | "revoke-share" | "create-family" | "join-family" | "invite" | "approve-member" | "remove-member" | "revoke-invite" | "save-entry" | "trash-entry" | "restore-entry" | "restore-history";
export interface SharedValues { title: string; username: string; password: string; url: string; notes: string }
export interface SharedEntry extends SharedValues { updated_at: number; trashed_at: number; history: Array<SharedValues & { updated_at: number }> }
export interface SharingOptions { action: SharingAction; family_id?: string; entry_id?: string; fields?: string[]; hours?: number; max_reads?: number; name?: string; invite?: string; role?: "reader" | "editor"; member_id?: string; pending_id?: string; values?: SharedValues; history_index?: number; replace_pending_id?: string }
export interface SharingPreview { preview_token: string; action: SharingAction; title: string; server: string; details: string[] }
export interface SharingStatus { service: string; identity: string; shares: Array<{ id: string; title: string; server: string; expires: number; max_reads: number; phase: string; reads: number }>; families: Array<{ id: string; name: string; server: string; pending: boolean; revision: number; removed: boolean }>; outbox: Array<{ id: string; action: SharingAction; title: string; family: string }> }
export interface SharedFamily { id: string; name: string; role: "owner" | "editor" | "reader"; revision: number; members: Array<{ id: string; role: string }>; entries: Array<{ id: string; title: string; username: string; url: string; trashed_at: number; history_count: number }> }
export interface FamilyPending { requests: Array<{ id: string; identity: string; role: "reader" | "editor"; expires: number }>; invitations: Array<{ id: string; role: string; expires: number; accepted: boolean }> }

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

export function browserPairingOrigin(baseUrl: string): string {
  const parsed = new URL(baseUrl);
  if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1") {
    throw new Error("Browser pairing requires the authenticated loopback sidecar");
  }
  return parsed.origin;
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
      if ((res.status === 401 || res.status === 423) && token) {
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

export interface RecoveryCode { id: string; value: string; used_at: string }
export interface TotpCode { code: string; period: number; expires_at: number; remaining_seconds: number; algorithm: string; digits: number; label: string; issuer: string }
export interface TemplateData { recovery_codes?: RecoveryCode[]; registered_to?: string; expires_on?: string; environment?: string; scopes?: string }

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
  entry_type: "login" | "secure_note" | "card" | "identity" | "ssh_key" | "recovery_code" | "software_license" | "api_credential";
  template_data?: TemplateData;
  website_rules?: WebsiteRules;
  passkeys?: PasskeySummary[];
  custom_fields: Array<{ label: string; value: string; concealed: boolean }>;
  totp_secret: string;
  has_totp_secret: boolean;
  attachments: Attachment[];
  history_count: number;
  created_at: string;
  updated_at: string;
  state?: "active" | "archived" | "trash";
  favorite?: boolean;
  trashed_at?: string;
}

export type OrganizationAction = "trash" | "archive" | "restore" | "purge" | "favorite" | "unfavorite" | "tag";
export interface OrganizationChange { entry_ids: string[]; action: OrganizationAction; tags: string[] }
export interface OrganizationPreview { preview_token: string; action: OrganizationAction; entries: Array<{ id: string; title: string }> }
export const mergeFields = ["title", "username", "password", "url", "notes", "tags", "custom_fields", "totp_secret", "template_data", "website_rules"] as const;
export type MergeField = typeof mergeFields[number];
export interface MergeChange { target_id: string; source_id: string; choices: Record<MergeField, "target" | "source"> }
export interface MergePreview { preview_token: string; target_title: string; source_title: string; history_count: number; attachment_count: number }

export interface Attachment {
  id: string;
  filename: string;
  mime_type: string;
  size: number;
  sha256: string;
}

export interface EntryTransactionPayload {
  template_data?: TemplateData;
  website_rules?: WebsiteRules;
  transaction_id: string;
  entry_id: string | null;
  expected_updated_at: string | null;
  title: string;
  username: string;
  password: string;
  url: string;
  notes: string;
  tags: string[];
  entry_type: Entry["entry_type"];
  custom_fields: Array<{ label: string; value: string; concealed: boolean }>;
  totp_secret: string;
  add_attachments: Array<{ filename: string; mime_type: string; data_b64: string }>;
  remove_attachment_ids: string[];
  restore_history_id: string | null;
}

export interface PersonalSettings {
  lock_after_seconds: number;
  auto_backup_enabled: boolean;
  auto_backup_interval_hours: number;
  auto_backup_destination: string;
  last_auto_backup_at: string;
  backup_status: {
    last_success_at: string;
    last_error_at: string;
    last_error_summary: string;
    last_verification_at: string;
    last_verification_status: "unverified" | "passed" | "failed";
    recovery_kit_created_at: string;
  };
}

export interface MaintenanceNotice {
  code: string;
  level: "info" | "error";
  message: string;
}

export interface BrowserPairing {
  sidecar_url: string;
  pairing_code: string;
  expires_in_seconds: number;
  message: string;
}

export interface BrowserDevice {
  id: string;
  name: string;
  origin: string;
  created_at: string;
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

export interface BackupRecord {
  path: string;
  kind: "local_atomic" | "manual" | string;
  size: number;
  modified_at: string;
  sha256: string;
  format: "legacy" | "v3" | "unreadable" | string;
  verified: boolean;
  pinned: boolean;
  transaction_id: string;
}

export interface BackupSummary {
  backups: BackupRecord[];
  count: number;
  total_bytes: number;
  verified_count: number;
  pinned_count: number;
  default_destination: string;
  health: PersonalSettings["backup_status"] & {
    backup_location: string;
    next_eligible_at: string;
    auto_backup_enabled: boolean;
  };
}

export interface BackupRestorePreview {
  preview_token: string;
  expires_at: string;
  backup: BackupRecord;
  impact: string;
  warning: string;
}

export interface StartupRestorePreview {
  preview_token: string;
  expires_at: string;
  backup: { path: string; size: number; modified_at: string; sha256: string };
  impact: string;
  warning: string;
}

export interface RecoveryRehearsalResult {
  verified_at: string;
  payload_version: number;
  complete_payload_matched: boolean;
  temporary_copy_removed: boolean;
  counts: { entries: number; active: number; archived: number; trash: number; attachments: number; history: number; totp: number };
}

export interface RecoveryKitPreview {
  preview_token: string;
  expires_at: string;
  kit: { path: string; size: number; modified_at: string; sha256: string; format: string; entry_count: number };
  impact: string;
  warning: string;
}

export interface BackupPruneResult {
  policy: {
    newest_count: number;
    daily_days: number;
    weekly_weeks: number;
  };
  keep_count: number;
  delete_count: number;
  reclaim_bytes: number;
  delete: BackupRecord[];
  applied: boolean;
  deleted_count: number;
  reclaimed_bytes: number;
  errors: string[];
  summary: BackupSummary;
  preview_token?: string;
  expires_at?: string;
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

export interface ImportPreviewCandidate {
  id: string;
  title: string;
  username: string;
  host: string;
}

export interface ImportPreviewItem {
  preview_id: string;
  index: number;
  title: string;
  username: string;
  host: string;
  classification: "new" | "exact_duplicate" | "possible_duplicate" | "invalid";
  reason: string;
  default_action: "create" | "skip";
  candidates: ImportPreviewCandidate[];
  unsupported_fields: string[];
  attachment_count: number;
  attachment_bytes: number;
}

export interface ImportPreview {
  source_format?: "chromium_csv" | "vault_csv" | "vault_json";
  preview_token: string;
  source_file_digest: string;
  expires_at: string;
  counts: {
    total: number;
    importable: number;
    exact_duplicates: number;
    possible_duplicates: number;
    format_errors: number;
    skipped: number;
    add: number;
    update: number;
    unsupported_fields: number;
    attachments: number;
    attachment_bytes: number;
  };
  items: ImportPreviewItem[];
  warning: string;
}

export interface ImportReceipt {
  transaction_id: string;
  source_file_digest: string;
  before_vault_digest: string;
  before_generation: number;
  after_vault_digest: string;
  after_generation: number;
  added_entry_ids: string[];
  updated_entry_ids: string[];
  created_at: string;
  undone: boolean;
}

export interface ImportApplyResult {
  applied: boolean;
  added: number;
  updated: number;
  skipped: number;
  receipt: ImportReceipt | null;
  warning: string;
}

export interface SyncSourcePreview {
  label: string;
  configured: boolean;
  available: boolean;
  status: string;
  error: string;
  pull: {
    remote_total: number;
    add: number;
    update: number;
    conflict: number;
    unchanged: number;
    local_only: number;
    delete_observed: number;
    pending_verification: number;
  };
  push: {
    create: number;
    update: number;
    delete: number;
    pending: number;
    conflict: number;
    total: number;
  };
  operations: SyncPreviewOperation[];
}

export type SyncOperationAction =
  | "add"
  | "update"
  | "delete"
  | "conflict"
  | "unchanged"
  | "pending_verification";

export interface SyncPreviewOperation {
  operation_id: string;
  source: string;
  source_label: string;
  direction: "pull" | "push";
  action: SyncOperationAction;
  local_id: string | null;
  remote_id: string | null;
  title: string;
  username_display: string;
  website_host: string;
  changed_fields: string[];
  deletion_side: "this_device" | "connected_service" | null;
  reason: string;
  destructive: boolean;
  next_step: string | null;
}

export interface SyncOperationResult extends SyncPreviewOperation {
  status:
    | "completed"
    | "unchanged"
    | "conflict"
    | "pending_verification"
    | "failed";
  outcome_reason: string;
}

export interface SyncPreview {
  preview_token: string;
  generated_at: string;
  expires_at: string;
  include_pull: boolean;
  include_push: boolean;
  sources: string[];
  per_source: Record<string, SyncSourcePreview>;
  totals: {
    pull_add: number;
    pull_update: number;
    pull_conflict: number;
    pull_delete_observed: number;
    push_create: number;
    push_update: number;
    push_delete: number;
    push_conflict: number;
    pending: number;
    unavailable_sources: number;
  };
  destructive_count: number;
  warnings: string[];
  operations: SyncPreviewOperation[];
}

export const api = {
  sharingStatus: () => request<SharingStatus>("/sharing/status"),
  configureSharing: (server: string, admin_token: string) => request<SharingStatus>("/sharing/connection", { method: "PUT", body: JSON.stringify({ server, admin_token, confirm: true }) }),
  previewSharing: (options: SharingOptions) => request<SharingPreview>("/sharing/preview", { method: "POST", body: JSON.stringify({ options }) }),
  cancelSharing: (preview_token: string) => request("/sharing/cancel", { method: "POST", body: JSON.stringify({ preview_token }) }),
  applySharing: (options: SharingOptions, preview_token: string) => request<{ completed: boolean; action: SharingAction; invitation?: string }>("/sharing/apply", { method: "POST", body: JSON.stringify({ options, preview_token, confirm: true }) }),
  pendingSharing: (id: string, action: "retry" | "discard") => request<{ invitation?: string }>(`/sharing/pending/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  reviewPendingSharing: (id: string) => request<{ options: SharingOptions; current: SharedValues | null }>(`/sharing/pending/${encodeURIComponent(id)}/review`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  sharingLink: (id: string) => request<{ link: string }>(`/sharing/shares/${encodeURIComponent(id)}/link`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  copySharingLink: (id: string) => request(`/sharing/shares/${encodeURIComponent(id)}/copy`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  sharedFamily: (id: string) => request<SharedFamily>(`/sharing/families/${encodeURIComponent(id)}`),
  refreshFamily: (id: string) => request<{ pending: boolean }>(`/sharing/families/${encodeURIComponent(id)}/refresh`, { method: "POST" }),
  sharedEntry: (family: string, id: string) => request<SharedEntry>(`/sharing/families/${encodeURIComponent(family)}/entry/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  copySharedEntry: (family: string, id: string, field: "username" | "password") => request(`/sharing/families/${encodeURIComponent(family)}/entry/${encodeURIComponent(id)}/copy/${field}`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  familyPending: (id: string) => request<FamilyPending>(`/sharing/families/${encodeURIComponent(id)}/pending`),
  copyFamilyInvitation: (code: string) => request("/sharing/invitations/copy", { method: "POST", body: JSON.stringify({ code, confirm: true }) }),
  pendingPasskeys: (signal?: AbortSignal) => request<{ items: PasskeyRequest[] }>("/passkeys/pending", { signal }),
  approvePasskey: (request_id: string, password: string, entry_id = "", credential_id = "") => request<{ approved: boolean; changed: boolean }>("/passkeys/approve", { method: "POST", body: JSON.stringify({ request_id, password, entry_id, credential_id, confirm: true }) }),
  rejectPasskey: (request_id: string, fallback = false) => request("/passkeys/reject", { method: "POST", body: JSON.stringify({ request_id, fallback }) }),
  personalSyncStatus: () => request<PersonalSyncStatus>("/personal-sync/status"),
  previewPersonalSync: (setup: PersonalSyncSetup) => request<PersonalSyncPreview>("/personal-sync/preview", { method: "POST", body: JSON.stringify(setup) }),
  cancelPersonalSync: (preview_token: string) => request("/personal-sync/cancel", { method: "POST", body: JSON.stringify({ preview_token }) }),
  connectPersonalSync: (preview_token: string) => request<{ connected: boolean; backup_path: string }>("/personal-sync/connect", { method: "POST", body: JSON.stringify({ preview_token, confirm: true }) }),
  runPersonalSync: (automatic = false, signal?: AbortSignal) => request<PersonalSyncResult>("/personal-sync/run", { method: "POST", body: JSON.stringify({ automatic }), signal }),
  updatePersonalSync: (automatic: boolean, label: string) => request<PersonalSyncStatus>("/personal-sync/settings", { method: "PUT", body: JSON.stringify({ automatic, label }) }),
  personalSyncCode: () => request<{ code: string }>("/personal-sync/code", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  copyPersonalSyncCode: () => request("/personal-sync/code/copy", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  disconnectPersonalSync: () => request<{ disconnected: boolean; cleanup_pending: boolean }>("/personal-sync/disconnect", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  personalSyncConflicts: (reveal = false) => request<PersonalSyncConflicts>(`/personal-sync/conflicts?reveal=${reveal}`),
  resolvePersonalSync: (generation: number, choices: Record<string, "local" | "remote">) => request("/personal-sync/resolve", { method: "POST", body: JSON.stringify({ generation, choices, confirm: true }) }),
  passwordHealth: () => request<PasswordHealthReport>("/security/password-health"),
  checkExposure: (entryId: string, confirmNetwork: boolean, signal?: AbortSignal) => request<{ entry_id: string; count: number; matching_entry_ids: string[] }>("/security/exposure", { method: "POST", body: JSON.stringify({ entry_id: entryId, confirm_network: confirmNetwork }), signal }),
  captureTypeTarget: () => invoke<TypeTarget>("capture_type_target"),
  startAutoType: (targetId: string, entryId: string, sequence: string, delayMs: number) => invoke<void>("start_auto_type", { targetId, entryId, token, sequence, delayMs }),
  cancelAutoType: () => invoke<void>("cancel_auto_type"),
  helloStatus: () => invoke<HelloStatus>("windows_hello_status"),
  enableHello: () => invoke<HelloStatus>("enable_windows_hello", { token }),
  disableHello: () => invoke<void>("disable_windows_hello"),
  unlockHello: () => invoke<{ token: string }>("unlock_windows_hello"),
  payloadFormat: () => request<{ version: number; current_version: number }>("/personal/format"),
  previewPayloadUpgrade: () => request<{ preview_token: string; entry_count: number }>("/personal/format/preview", { method: "POST" }),
  cancelPayloadUpgrade: (preview_token: string) => request("/personal/format/cancel", { method: "POST", body: JSON.stringify({ preview_token }) }),
  applyPayloadUpgrade: (preview_token: string) => request<{ backup_path: string; locked: boolean }>("/personal/format/apply", { method: "POST", body: JSON.stringify({ preview_token, confirm_upgrade: true }) }),
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
  previewVaultRestore: (backupPath: string, password: string, remember = false) =>
    request<StartupRestorePreview>("/auth/restore/preview", {
      method: "POST",
      body: JSON.stringify({ backup_path: backupPath, password, remember }),
    }),
  applyVaultRestore: (previewToken: string, password: string, remember = false) =>
    request<{ locked: boolean; message: string }>("/auth/restore/apply", {
      method: "POST",
      body: JSON.stringify({ preview_token: previewToken, password, remember, confirm_restore: true }),
    }),
  cancelVaultRestore: (previewToken: string) =>
    request<{ cancelled: boolean }>("/auth/restore/cancel", {
      method: "POST",
      body: JSON.stringify({ preview_token: previewToken }),
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
  listEntries: (q?: string, state = "active") =>
    request<Entry[]>(`/entries?state=${encodeURIComponent(state)}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  previewOrganization: (data: OrganizationChange) => request<OrganizationPreview>("/organization/preview", { method: "POST", body: JSON.stringify(data) }),
  duplicateGroups: () => request<{ groups: string[][] }>("/organization/duplicates"),
  previewMerge: (data: MergeChange) => request<MergePreview>("/organization/merge/preview", { method: "POST", body: JSON.stringify(data) }),
  cancelMerge: (preview_token: string) => request("/organization/merge/cancel", { method: "POST", body: JSON.stringify({ preview_token }) }),
  applyMerge: (data: MergeChange, preview_token: string) => request<{ merged_id: string; trashed_id: string }>("/organization/merge/apply", { method: "POST", body: JSON.stringify({ ...data, preview_token, confirm: true }) }),
  cancelOrganization: (preview_token: string) => request("/organization/cancel", { method: "POST", body: JSON.stringify({ preview_token }) }),
  applyOrganization: (data: OrganizationChange, preview_token: string) => request("/organization/apply", { method: "POST", body: JSON.stringify({ ...data, preview_token, confirm: true }) }),
  getEntry: (id: string, reveal = true) =>
    request<Entry>(`/entries/${id}?reveal=${reveal}`),
  commitEntry: (data: EntryTransactionPayload) =>
    request<Entry>("/entries/commit", { method: "POST", body: JSON.stringify(data) }),
  deleteEntry: (id: string) => request(`/entries/${id}`, { method: "DELETE" }),
  downloadAttachment: (id: string, attachmentId: string) =>
    request<Attachment & { data_b64: string }>(`/entries/${id}/attachments/${attachmentId}`),
  entryHistory: (id: string, reveal = false) =>
    request<{ history: Array<{ id: string; saved_at: string; snapshot: Record<string, unknown> }> }>(
      `/entries/${id}/history?reveal=${reveal}`
    ),
  previewEntryHistory: (id: string, historyId: string) =>
    request<{ history_id: string; entry: Entry }>(`/entries/${id}/history/${historyId}`),
  copy: (id: string, field = "password") =>
    request(`/entries/${id}/copy?field=${field}`, { method: "POST" }),
  copyRecoveryCode: (id: string, codeId: string) => request(`/entries/${encodeURIComponent(id)}/recovery-codes/${encodeURIComponent(codeId)}/copy`, { method: "POST" }),
  previewTotp: (value: string) => request<({ valid: true } & TotpCode) | { valid: false }>("/entries/tools/totp/preview", { method: "POST", body: JSON.stringify({ value }) }),
  copyTotp: (id: string) => request<{ clears_in_seconds: number }>(`/entries/${encodeURIComponent(id)}/totp/copy`, { method: "POST" }),
  generate: (length = 20, symbols = true) =>
    request<{ password: string }>(
      `/entries/tools/generate?length=${length}&symbols=${symbols}`
    ),
  generateSaved: (options: GenerationOptions, url: string, request_id: string) => request<{ password: string; history_saved: boolean }>("/entries/tools/generate", { method: "POST", body: JSON.stringify({ ...options, url, request_id }) }),
  generationHistory: () => request<{ items: GeneratedPassword[] }>("/entries/tools/generation/history"),
  testWebsiteMatch: (primary_url: string, rules: WebsiteRules, test_url: string) => request<{ valid: boolean; matches: boolean }>("/entries/tools/website-match", { method: "POST", body: JSON.stringify({ primary_url, rules, test_url }) }),
  generationValue: (id: string) => request<{ password: string }>(`/entries/tools/generation/history/${encodeURIComponent(id)}`),
  copyGeneration: (id: string) => request(`/entries/tools/generation/history/${encodeURIComponent(id)}/copy`, { method: "POST" }),
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
  backups: () => request<BackupSummary>("/backups"),
  createBackup: (destinationDir?: string) =>
    request<BackupSummary & { created: BackupRecord; warning: string }>("/backups/create", {
      method: "POST",
      body: JSON.stringify({ destination_dir: destinationDir || null }),
    }),
  pinBackup: (path: string, pinned: boolean) =>
    request<BackupSummary & { backup: BackupRecord }>("/backups/pin", {
      method: "PUT",
      body: JSON.stringify({ path, pinned }),
    }),
  pruneBackups: (
    apply: boolean,
    policy: { newest_count: number; daily_days: number; weekly_weeks: number },
    previewToken?: string
  ) =>
    request<BackupPruneResult>("/backups/prune", {
      method: "POST",
      body: JSON.stringify({
        apply,
        ...policy,
        preview_token: previewToken || null,
      }),
    }),
  testBackupDestination: (destinationDir: string) =>
    request<{ path: string; exists: boolean; writable: boolean; free_bytes: number; message: string }>(
      "/backups/test-destination",
      { method: "POST", body: JSON.stringify({ destination_dir: destinationDir }) },
    ),
  verifyBackup: (path?: string) =>
    request<{ verified: boolean; verified_at: string; backup: BackupRecord; message: string; warning: string }>(
      "/backups/verify",
      { method: "POST", body: JSON.stringify({ path: path || null }) },
    ),
  previewBackupRestore: (path: string, password = "") =>
    request<BackupRestorePreview>("/backups/restore/preview", {
      method: "POST",
      body: JSON.stringify({ path, password }),
    }),
  applyBackupRestore: (previewToken: string, password = "", confirmRestore = false) =>
    request<{ restored: string; locked: boolean; message: string }>(
      "/backups/restore/apply",
      {
        method: "POST",
        body: JSON.stringify({
          preview_token: previewToken,
          password,
          confirm_restore: confirmRestore,
        }),
      }
    ),
  cancelBackupRestore: (previewToken: string) =>
    request<{ cancelled: boolean }>("/backups/restore/cancel", {
      method: "POST",
      body: JSON.stringify({ preview_token: previewToken }),
    }),
  status: () => request<{ components: Record<string, string> }>("/status"),
  getPersonalSettings: () => request<PersonalSettings>("/personal/settings"),
  savePersonalSettings: (settings: Partial<PersonalSettings>) =>
    request<PersonalSettings>("/personal/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  runMaintenance: () =>
    request<{ settings: PersonalSettings; components: Record<string, string>; notices: MaintenanceNotice[] }>(
      "/personal/maintenance",
      { method: "POST" }
    ),
  exportTransfer: (format: "json" | "csv") =>
    request<{ format: string; filename: string; mime_type: string; content: string; warning: string }>(
      "/transfer/export",
      { method: "POST", body: JSON.stringify({ format, confirm_plaintext: true }) }
    ),
  previewImport: (format: "json" | "csv" | "browser_csv", content: string) =>
    request<ImportPreview>("/transfer/import/preview", {
      method: "POST",
      body: JSON.stringify({ format, content, confirm_plaintext: true }),
    }),
  applyImport: (
    previewToken: string,
    decisions: Array<{
      preview_id: string;
      action: "skip" | "create" | "update";
      target_entry_id: string | null;
    }>,
  ) =>
    request<ImportApplyResult>("/transfer/import/apply", {
      method: "POST",
      body: JSON.stringify({ preview_token: previewToken, decisions }),
    }),
  cancelImport: (previewToken: string) =>
    request<{ cancelled: boolean }>("/transfer/import/cancel", {
      method: "POST",
      body: JSON.stringify({ preview_token: previewToken }),
    }),
  undoImport: (transactionId: string) =>
    request<{ undone: boolean; receipt: ImportReceipt; restored_vault_digest: string }>(
      "/transfer/import/undo",
      {
        method: "POST",
        body: JSON.stringify({ transaction_id: transactionId }),
      },
    ),
  newRecoveryCode: () => request<{ recovery_code: string }>("/auth/recovery-code", { method: "POST" }),
  createRecoveryKit: (recoveryCode: string, destinationDir?: string) =>
    request<{ path: string; message: string; warning: string }>("/auth/recovery-kit", {
      method: "POST",
      body: JSON.stringify({
        recovery_code: recoveryCode,
        confirm_recovery_code: recoveryCode,
        destination_dir: destinationDir || null,
      }),
    }),
  rehearseRecoveryKit: (kitPath: string, recoveryCode: string) =>
    request<RecoveryRehearsalResult>("/auth/recover/rehearse", { method: "POST", body: JSON.stringify({ kit_path: kitPath, recovery_code: recoveryCode }) }),
  previewRecoveryKit: (kitPath: string, recoveryCode: string) =>
    request<RecoveryKitPreview>("/auth/recover/preview", {
      method: "POST",
      body: JSON.stringify({
        kit_path: kitPath,
        recovery_code: recoveryCode,
      }),
    }),
  applyRecoveryKit: (
    previewToken: string,
    recoveryCode: string,
    newPassword: string,
    confirmNewPassword: string,
  ) =>
    request<{ locked: boolean; message: string }>("/auth/recover/apply", {
      method: "POST",
      body: JSON.stringify({
        preview_token: previewToken,
        recovery_code: recoveryCode,
        new_password: newPassword,
        confirm_new_password: confirmNewPassword,
        confirm_recovery: true,
      }),
    }),
  cancelRecoveryKit: (previewToken: string) =>
    request<{ cancelled: boolean }>("/auth/recover/cancel", {
      method: "POST",
      body: JSON.stringify({ preview_token: previewToken }),
    }),
  createBrowserPairing: async (): Promise<BrowserPairing> => {
    const [result, config] = await Promise.all([
      request<{ pairing_code: string; expires_in_seconds: number; message: string }>(
        "/browser/pairing-code",
        { method: "POST" },
      ),
      runtimeConfig(),
    ]);
    return { ...result, sidecar_url: browserPairingOrigin(config.base_url) };
  },
  cancelBrowserPairing: () =>
    request<{ cancelled: boolean }>("/browser/pairing/cancel", { method: "POST" }),
  browserDevices: () => request<{ available: boolean; devices: BrowserDevice[] }>("/browser/devices"),
  revokeBrowserDevice: (id: string) => request<{ revoked: boolean }>(`/browser/devices/${encodeURIComponent(id)}`, { method: "DELETE" }),
  getPrefs: () => request<SyncPrefs>("/sync/preferences"),
  savePrefs: (prefs: Partial<SyncPrefs>) =>
    request<SyncPrefs>("/sync/preferences", {
      method: "PUT",
      body: JSON.stringify(prefs),
    }),
  previewSync: (
    includePull: boolean,
    includePush: boolean,
    sources?: string[]
  ) =>
    request<SyncPreview>("/sync/preview", {
      method: "POST",
      body: JSON.stringify({
        include_pull: includePull,
        include_push: includePush,
        sources: sources ?? null,
      }),
    }),
  executeSync: (previewToken: string) =>
    request("/sync/execute", {
      method: "POST",
      body: JSON.stringify({ preview_token: previewToken }),
    }),
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
