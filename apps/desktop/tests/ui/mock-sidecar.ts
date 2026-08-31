import type { Page, Route } from "@playwright/test";
import { testData } from "./test-data";

type StoredEntry = {
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
  entry_type: "login" | "secure_note" | "card" | "identity" | "ssh_key" | "recovery_code";
  custom_fields: Array<{ label: string; value: string; concealed: boolean }>;
  totp_secret: string;
  has_totp_secret: boolean;
  attachments: Array<Record<string, unknown>>;
  history_count: number;
  created_at: string;
  updated_at: string;
};

type StoredConflict = {
  id: string;
  title: string;
  default_choice: "local" | "remote";
  local: Record<string, string>;
  remote: Record<string, string>;
  remote_source: string;
};

const CORS_HEADERS = {
  "access-control-allow-origin": "http://127.0.0.1:1420",
  "access-control-allow-headers":
    "authorization,content-type,x-vault-bootstrap,x-vault-client",
  "access-control-allow-methods": "DELETE,GET,OPTIONS,PATCH,POST,PUT",
  "content-type": "application/json",
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function body(route: Route): Record<string, unknown> {
  try {
    return (route.request().postDataJSON() || {}) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export class MockAuthenticatedSidecar {
  private vaultExists = false;
  private unlocked = false;
  private masterPassword = "";
  private entries = new Map<string, StoredEntry>();
  private transactionReceipts = new Map<string, string>();
  private histories = new Map<string, Array<{ id: string; saved_at: string; snapshot: StoredEntry }>>();
  private importPreviews = new Map<string, {
    revision: number;
    before: StoredEntry[];
    items: Array<Record<string, unknown>>;
    rawEntries: Array<Record<string, unknown>>;
  }>();
  private importReceipts = new Map<string, { before: StoredEntry[]; after: StoredEntry[]; undone: boolean }>();
  private integrations = [
    {
      source: "proton_pass",
      label: "Proton Pass",
      configured: false,
      cli_installed: false,
      fields: [
        { key: "access_token", label: "Access token", secret: true, required: true, value: "", present: false, origin: "unset" },
      ],
    },
    {
      source: "bitwarden",
      label: "Bitwarden",
      configured: false,
      cli_installed: true,
      fields: [
        { key: "server_url", label: "Server address", secret: false, required: false, value: "", present: false, origin: "default" },
      ],
    },
    {
      source: "keepassxc",
      label: "KeePassXC",
      configured: false,
      cli_installed: false,
      fields: [
        { key: "database_path", label: "Database file", secret: false, required: true, value: "", present: false, origin: "unset" },
      ],
    },
    {
      source: "gopass",
      label: "gopass",
      configured: false,
      cli_installed: false,
      fields: [
        { key: "store_path", label: "Store folder", secret: false, required: false, value: "", present: false, origin: "unset" },
      ],
    },
  ];
  private syncPrefs = {
    primary: "local",
    auto_push_on_edit: false,
    auto_pull_on_sync: false,
    conflict_default: "manual",
    proton_vault_name: "",
    proton_share_id: "",
    enabled_sources: [] as string[],
  };
  private conflicts: StoredConflict[] = [];
  private revision = 0;

  readonly writes = { create: 0, update: 0, delete: 0 };
  readonly importWrites = { apply: 0, undo: 0 };
  readonly syncWrites = { execute: 0 };

  constructor(
    private readonly lockAfterSeconds = 900,
    private readonly commitDelayMs = 0,
    private readonly syncPreviewMode: "empty" | "deletion" = "empty",
    conflictCount = 0,
    entryCount = 0,
  ) {
    this.conflicts = Array.from({ length: conflictCount }, (_, index) => ({
      id: `generated-conflict-${index + 1}`,
      title: `Generated conflict ${index + 1}`,
      default_choice: index % 2 === 0 ? "local" : "remote",
      local: {
        title: `Generated conflict ${index + 1}`,
        username: `device-${index + 1}@example.invalid`,
        password: testData.entryPassword,
        url: `https://device-${index + 1}.example.invalid`,
        notes: "Generated device note",
      },
      remote: {
        title: `Generated conflict ${index + 1}`,
        username: `service-${index + 1}@example.invalid`,
        password: `${testData.entryPassword}-service`,
        url: `https://service-${index + 1}.example.invalid`,
        notes: "Generated service note",
      },
      remote_source: "bitwarden",
    }));
    for (let index = 1; index <= entryCount; index += 1) {
      const suffix = String(index).padStart(4, "0");
      const entry: StoredEntry = {
        id: `generated-entry-${suffix}`,
        title: `Generated account ${suffix}`,
        username: `person-${suffix}@example.invalid`,
        password: testData.entryPassword,
        url: `https://account-${suffix}.example.invalid/login`,
        notes: "Generated scale fixture",
        has_password: true,
        has_notes: true,
        source: "local",
        tags: index % 10 === 0 ? ["generated-scale"] : [],
        sync_status: "clean",
        linked_sources: {},
        entry_type: "login",
        custom_fields: [],
        totp_secret: "",
        has_totp_secret: false,
        attachments: [],
        history_count: 0,
        created_at: "2026-08-31T00:00:00Z",
        updated_at: "2026-08-31T00:00:00Z",
      };
      this.entries.set(entry.id, entry);
    }
  }

  get persistedEntries(): StoredEntry[] {
    return Array.from(this.entries.values(), clone);
  }

  seedCompatibilityEntry(entryType: Exclude<StoredEntry["entry_type"], "login" | "secure_note">): string {
    const id = `generated-compatibility-${entryType}`;
    const entry: StoredEntry = {
      id,
      title: "Generated compatibility item",
      username: "compatibility@example.invalid",
      password: testData.entryPassword,
      url: "https://compatibility.example.invalid",
      notes: "Generated compatibility notes",
      has_password: true,
      has_notes: true,
      source: "bitwarden",
      tags: ["generated", "compatibility"],
      sync_status: "clean",
      linked_sources: { bitwarden: "generated-remote-id" },
      entry_type: entryType,
      custom_fields: [{ label: "Generated field", value: "Generated value", concealed: false }],
      totp_secret: "",
      has_totp_secret: false,
      attachments: [],
      history_count: 0,
      created_at: "2026-08-31T00:00:00Z",
      updated_at: this.timestamp(),
    };
    this.entries.set(id, entry);
    return id;
  }

  private timestamp(): string {
    this.revision += 1;
    return `2026-08-31T00:00:${String(this.revision).padStart(2, "0")}Z`;
  }

  async install(page: Page): Promise<void> {
    await page.route("http://127.0.0.1:43129/**", (route) => this.handle(route));
  }

  private async respond(route: Route, status: number, value: unknown): Promise<void> {
    await route.fulfill({
      status,
      headers: CORS_HEADERS,
      body: value == null ? "" : JSON.stringify(value),
    });
  }

  private listed(entry: StoredEntry): StoredEntry {
    return {
      ...clone(entry),
      password: "",
      notes: "",
      custom_fields: entry.custom_fields.map((field) => ({ ...field, value: "" })),
      totp_secret: "",
    };
  }

  private async handle(route: Route): Promise<void> {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());

    if (method === "OPTIONS") {
      await this.respond(route, 204, null);
      return;
    }

    const headers = request.headers();
    if (headers["x-vault-bootstrap"] !== testData.bootstrapSecret) {
      await this.respond(route, 401, { detail: "Invalid generated bootstrap credential" });
      return;
    }

    if (method === "GET" && url.pathname === "/auth/vault-info") {
      await this.respond(route, 200, {
        exists: this.vaultExists,
        format: this.vaultExists ? "v3" : "missing",
        path: `C:\\isolated-vault-tests\\${testData.runId}\\secrets.vault`,
      });
      return;
    }

    if (method === "GET" && url.pathname === "/auth/check-keyring") {
      await this.respond(route, 200, { has_saved_password: false });
      return;
    }

    if (method === "POST" && url.pathname === "/auth/create") {
      const value = body(route);
      if (
        this.vaultExists ||
        typeof value.password !== "string" ||
        value.password !== value.confirm_password
      ) {
        await this.respond(route, 400, { detail: "Invalid isolated vault creation" });
        return;
      }
      this.vaultExists = true;
      this.unlocked = true;
      this.masterPassword = value.password;
      await this.respond(route, 200, { token: testData.bearerToken });
      return;
    }

    if (method === "POST" && url.pathname === "/auth/unlock") {
      const value = body(route);
      if (!this.vaultExists || value.password !== this.masterPassword) {
        await this.respond(route, 401, { detail: "Invalid generated test password" });
        return;
      }
      this.unlocked = true;
      await this.respond(route, 200, { token: testData.bearerToken });
      return;
    }

    const authorized =
      this.unlocked && headers.authorization === `Bearer ${testData.bearerToken}`;
    if (!authorized) {
      await this.respond(route, 401, { detail: "Generated test session is locked" });
      return;
    }

    if (method === "POST" && url.pathname === "/auth/lock") {
      this.unlocked = false;
      await this.respond(route, 200, { locked: true });
      return;
    }

    if (method === "GET" && url.pathname === "/auth/status") {
      await this.respond(route, 200, { unlocked: true });
      return;
    }

    if (method === "GET" && url.pathname === "/personal/settings") {
      await this.respond(route, 200, {
        lock_after_seconds: this.lockAfterSeconds,
        auto_backup_enabled: false,
        auto_backup_interval_hours: 24,
        auto_backup_destination: "",
        last_auto_backup_at: "",
      });
      return;
    }

    if (method === "PUT" && url.pathname === "/personal/settings") {
      await this.respond(route, 200, {
        lock_after_seconds: this.lockAfterSeconds,
        auto_backup_enabled: false,
        auto_backup_interval_hours: 24,
        auto_backup_destination: "",
        last_auto_backup_at: "",
      });
      return;
    }

    if (method === "GET" && url.pathname === "/integrations") {
      await this.respond(route, 200, clone(this.integrations));
      return;
    }

    if ((method === "PUT" || method === "DELETE") && url.pathname.startsWith("/integrations/")) {
      const source = decodeURIComponent(url.pathname.split("/").pop() || "");
      const index = this.integrations.findIndex((item) => item.source === source);
      if (index < 0) {
        await this.respond(route, 404, { detail: "Generated connection not found" });
        return;
      }
      const values = body(route);
      const current = this.integrations[index];
      const fields = current.fields.map((field) => {
        const nextValue = method === "DELETE" ? "" : String(values.values && typeof values.values === "object" ? (values.values as Record<string, unknown>)[field.key] || "" : "");
        return { ...field, value: field.secret ? "" : nextValue, present: Boolean(nextValue), origin: nextValue ? "saved" : "unset" };
      });
      this.integrations[index] = { ...current, configured: method !== "DELETE", fields };
      await this.respond(route, 200, clone(this.integrations[index]));
      return;
    }

    if (method === "POST" && url.pathname.startsWith("/integrations/") && url.pathname.endsWith("/test")) {
      const source = decodeURIComponent(url.pathname.split("/")[2] || "");
      const item = this.integrations.find((candidate) => candidate.source === source);
      const available = Boolean(item?.configured && item.cli_installed);
      await this.respond(route, 200, {
        source,
        configured: Boolean(item?.configured),
        available,
        message: available ? "Connection test passed" : "Connection needs setup",
      });
      return;
    }

    if (method === "POST" && url.pathname === "/personal/maintenance") {
      await this.respond(route, 200, {
        settings: {
          lock_after_seconds: this.lockAfterSeconds,
          auto_backup_enabled: false,
          auto_backup_interval_hours: 24,
          auto_backup_destination: "",
          last_auto_backup_at: "",
        },
        components: { conflicts: String(this.conflicts.length) },
        notices: [],
      });
      return;
    }

    if (method === "GET" && url.pathname === "/sync/conflicts") {
      const reveal = url.searchParams.get("reveal") === "true";
      const response = this.conflicts.map((conflict) => reveal ? conflict : {
        ...conflict,
        local: { ...conflict.local, password: "", notes: "" },
        remote: { ...conflict.remote, password: "", notes: "" },
      });
      await this.respond(route, 200, clone(response));
      return;
    }

    if (method === "POST" && /^\/sync\/conflicts\/[^/]+\/resolve$/.test(url.pathname)) {
      const conflictId = decodeURIComponent(url.pathname.split("/")[3] || "");
      const before = this.conflicts.length;
      this.conflicts = this.conflicts.filter((conflict) => conflict.id !== conflictId);
      if (this.conflicts.length === before) {
        await this.respond(route, 404, { detail: "Generated conflict not found" });
        return;
      }
      await this.respond(route, 200, { resolved: true });
      return;
    }

    if (method === "GET" && url.pathname === "/sync/preferences") {
      await this.respond(route, 200, clone(this.syncPrefs));
      return;
    }

    if (method === "PUT" && url.pathname === "/sync/preferences") {
      this.syncPrefs = { ...this.syncPrefs, ...body(route) } as typeof this.syncPrefs;
      await this.respond(route, 200, clone(this.syncPrefs));
      return;
    }

    if (method === "GET" && url.pathname === "/status") {
      await this.respond(route, 200, {
        components: {
          local: `ready (${this.entries.size} entries)`,
          dirty: "0",
          conflicts: "0",
          bitwarden: "ready (enabled)",
        },
      });
      return;
    }

    if (method === "POST" && url.pathname === "/sync/preview") {
      const operation = {
        operation_id: "a".repeat(64),
        source: "bitwarden",
        source_label: "Bitwarden",
        direction: "push",
        action: "delete",
        local_id: "generated-local-entry-id",
        remote_id: "generated-remote-entry-id",
        title: "Generated deletion review",
        username_display: "g***@example.invalid",
        website_host: "sync.example.invalid",
        changed_fields: [],
        deletion_side: "connected_service",
        reason: "deleted_on_this_device",
        destructive: true,
        next_step: null,
      };
      const operations = this.syncPreviewMode === "deletion" ? [operation] : [];
      await this.respond(route, 200, {
        preview_token: `generated-sync-preview-${testData.runId}`,
        generated_at: "2026-08-31T00:00:00Z",
        expires_at: "2026-08-31T00:05:00Z",
        include_pull: true,
        include_push: true,
        sources: ["bitwarden"],
        per_source: {
          bitwarden: {
            label: "Bitwarden",
            configured: true,
            available: true,
            status: "ready",
            error: "",
            pull: {
              remote_total: 0,
              add: 0,
              update: 0,
              conflict: 0,
              unchanged: 0,
              local_only: 0,
              delete_observed: 0,
              pending_verification: 0,
            },
            push: {
              create: 0,
              update: 0,
              delete: operations.length,
              pending: 0,
              conflict: 0,
              total: operations.length,
            },
            operations,
          },
        },
        totals: {
          pull_add: 0,
          pull_update: 0,
          pull_conflict: 0,
          pull_delete_observed: 0,
          push_create: 0,
          push_update: 0,
          push_delete: operations.length,
          push_conflict: 0,
          pending: 0,
          unavailable_sources: 0,
        },
        destructive_count: operations.length,
        warnings: operations.length ? ["The plan includes remote deletion"] : [],
        operations,
      });
      return;
    }

    if (method === "POST" && url.pathname === "/sync/execute") {
      if (this.syncPreviewMode !== "deletion") {
        await this.respond(route, 409, { detail: "No generated operation to execute" });
        return;
      }
      this.syncWrites.execute += 1;
      await this.respond(route, 200, {
        pulled: {},
        pushed: { pushed: 1, errors: 0 },
        conflicts: [],
        errors: [],
        operations: [{
          operation_id: "a".repeat(64),
          source: "bitwarden",
          source_label: "Bitwarden",
          direction: "push",
          action: "delete",
          local_id: "generated-local-entry-id",
          remote_id: "generated-remote-entry-id",
          title: "Generated deletion review",
          username_display: "g***@example.invalid",
          website_host: "sync.example.invalid",
          changed_fields: [],
          deletion_side: "connected_service",
          reason: "deleted_on_this_device",
          destructive: true,
          next_step: null,
          status: "completed",
          outcome_reason: "connected_service_state_verified",
        }],
      });
      return;
    }

    if (method === "GET" && url.pathname === "/backups") {
      await this.respond(route, 200, {
        backups: [],
        count: 0,
        total_bytes: 0,
        verified_count: 0,
        pinned_count: 0,
        default_destination: `C:\\isolated-vault-tests\\${testData.runId}\\backups`,
      });
      return;
    }

    if (method === "GET" && url.pathname === "/entries") {
      const query = (url.searchParams.get("q") || "").trim().toLowerCase();
      const values = this.persistedEntries
        .filter((entry) =>
          !query
            ? true
            : [entry.title, entry.username, entry.url, ...entry.tags]
                .join(" ")
                .toLowerCase()
                .includes(query),
        )
        .map((entry) => this.listed(entry));
      await this.respond(route, 200, values);
      return;
    }

    if (method === "POST" && url.pathname === "/transfer/import/preview") {
      const value = body(route);
      const content = String(value.content || "");
      let rawEntries: Array<Record<string, unknown>> = [];
      try {
        if (value.format === "json") {
          const parsed = JSON.parse(content) as { entries?: Array<Record<string, unknown>> };
          rawEntries = Array.isArray(parsed.entries) ? parsed.entries : [];
        } else {
          throw new Error("Generated UI mock only accepts JSON import fixtures");
        }
      } catch {
        await this.respond(route, 400, { detail: "Transfer JSON is invalid" });
        return;
      }
      const items = rawEntries.map((item, index) => {
        const title = String(item.title || "");
        const username = String(item.username || "");
        const urlValue = String(item.url || "");
        const host = (() => {
          try { return new URL(urlValue).hostname; } catch { return ""; }
        })();
        const matches = this.persistedEntries.filter((entry) => {
          const entryHost = (() => {
            try { return new URL(entry.url).hostname; } catch { return ""; }
          })();
          return (entryHost && entryHost === host && entry.username === username)
            || (entry.title === title && entry.username === username);
        });
        const exact = matches.find((entry) =>
          entry.title === title
          && entry.username === username
          && entry.password === String(item.password || "")
          && entry.url === urlValue
          && entry.notes === String(item.notes || ""),
        );
        const classification = exact
          ? "exact_duplicate"
          : matches.length
            ? "possible_duplicate"
            : "new";
        return {
          preview_id: `item-${index + 1}`,
          index: index + 1,
          title,
          username,
          host,
          classification,
          reason: classification === "new" ? "New entry" : "Generated duplicate match",
          default_action: classification === "new" ? "create" : "skip",
          candidates: matches.map((entry) => ({
            id: entry.id,
            title: entry.title,
            username: entry.username,
            host,
          })),
          unsupported_fields: [],
          attachment_count: 0,
          attachment_bytes: 0,
        };
      });
      const token = `generated-import-preview-${testData.runId}-${this.importPreviews.size + 1}`;
      this.importPreviews.set(token, {
        revision: this.revision,
        before: this.persistedEntries,
        items,
        rawEntries,
      });
      const count = (classification: string) => items.filter((item) => item.classification === classification).length;
      await this.respond(route, 200, {
        preview_token: token,
        source_file_digest: "a".repeat(64),
        expires_at: "2026-08-31T00:05:00Z",
        counts: {
          total: items.length,
          importable: count("new") + count("possible_duplicate"),
          exact_duplicates: count("exact_duplicate"),
          possible_duplicates: count("possible_duplicate"),
          format_errors: 0,
          skipped: count("exact_duplicate") + count("possible_duplicate"),
          add: count("new"),
          update: 0,
          unsupported_fields: 0,
          attachments: 0,
          attachment_bytes: 0,
        },
        items,
        warning: "Preview only",
      });
      return;
    }

    if (method === "POST" && url.pathname === "/transfer/import/cancel") {
      const value = body(route);
      const token = String(value.preview_token || "");
      if (!this.importPreviews.delete(token)) {
        await this.respond(route, 409, { detail: "Import preview expired, was cancelled, or was already used" });
        return;
      }
      await this.respond(route, 200, { cancelled: true });
      return;
    }

    if (method === "POST" && url.pathname === "/transfer/import/apply") {
      const value = body(route);
      const token = String(value.preview_token || "");
      const preview = this.importPreviews.get(token);
      this.importPreviews.delete(token);
      if (!preview) {
        await this.respond(route, 409, { detail: "Import preview expired, was cancelled, or was already used" });
        return;
      }
      if (preview.revision !== this.revision) {
        await this.respond(route, 409, { detail: "Vault changed after the import preview; create a new preview" });
        return;
      }
      const decisions = new Map(
        (Array.isArray(value.decisions) ? value.decisions : []).map((decision) => {
          const item = decision as Record<string, unknown>;
          return [String(item.preview_id || ""), item];
        }),
      );
      const addedIds: string[] = [];
      const updatedIds: string[] = [];
      let skipped = 0;
      preview.items.forEach((item, index) => {
        const raw = preview.rawEntries[index];
        const decision = decisions.get(String(item.preview_id));
        const action = String(decision?.action || item.default_action);
        if (action === "skip") {
          skipped += 1;
          return;
        }
        const targetId = String(decision?.target_entry_id || "");
        const existing = action === "update" ? this.entries.get(targetId) : undefined;
        const id = existing?.id || `generated-imported-${testData.runId}-${index + 1}`;
        const now = this.timestamp();
        const stored: StoredEntry = {
          id,
          title: String(raw.title || ""),
          username: String(raw.username || ""),
          password: String(raw.password || ""),
          url: String(raw.url || ""),
          notes: String(raw.notes || ""),
          has_password: Boolean(raw.password),
          has_notes: Boolean(raw.notes),
          source: "local",
          tags: Array.isArray(raw.tags) ? raw.tags.map(String) : [],
          sync_status: "dirty",
          linked_sources: existing?.linked_sources || {},
          entry_type: (raw.entry_type || "login") as StoredEntry["entry_type"],
          custom_fields: Array.isArray(raw.custom_fields) ? raw.custom_fields as StoredEntry["custom_fields"] : [],
          totp_secret: String(raw.totp_secret || ""),
          has_totp_secret: Boolean(raw.totp_secret),
          attachments: [],
          history_count: existing ? existing.history_count + 1 : 0,
          created_at: existing?.created_at || now,
          updated_at: now,
        };
        this.entries.set(id, stored);
        if (existing) {
          updatedIds.push(id);
          this.writes.update += 1;
        } else {
          addedIds.push(id);
          this.writes.create += 1;
        }
      });
      if (!addedIds.length && !updatedIds.length) {
        await this.respond(route, 200, {
          applied: false,
          added: 0,
          updated: 0,
          skipped,
          receipt: null,
          warning: "Nothing was imported",
        });
        return;
      }
      const transactionId = `generated-import-receipt-${testData.runId}-${this.importReceipts.size + 1}`;
      const after = this.persistedEntries;
      this.importReceipts.set(transactionId, { before: preview.before, after, undone: false });
      this.importWrites.apply += 1;
      await this.respond(route, 200, {
        applied: true,
        added: addedIds.length,
        updated: updatedIds.length,
        skipped,
        receipt: {
          transaction_id: transactionId,
          source_file_digest: "a".repeat(64),
          before_vault_digest: "b".repeat(64),
          before_generation: preview.revision,
          after_vault_digest: "c".repeat(64),
          after_generation: this.revision,
          added_entry_ids: addedIds,
          updated_entry_ids: updatedIds,
          created_at: "2026-08-31T00:00:00Z",
          undone: false,
        },
        warning: "Imported entries remain local",
      });
      return;
    }

    if (method === "POST" && url.pathname === "/transfer/import/undo") {
      const value = body(route);
      const transactionId = String(value.transaction_id || "");
      const receipt = this.importReceipts.get(transactionId);
      if (!receipt || receipt.undone || JSON.stringify(receipt.after) !== JSON.stringify(this.persistedEntries)) {
        await this.respond(route, 409, { detail: "Vault changed after the import; undo was refused" });
        return;
      }
      this.entries = new Map(receipt.before.map((entry) => [entry.id, clone(entry)]));
      receipt.undone = true;
      this.importWrites.undo += 1;
      await this.respond(route, 200, {
        undone: true,
        receipt: {
          transaction_id: transactionId,
          source_file_digest: "a".repeat(64),
          before_vault_digest: "b".repeat(64),
          before_generation: 0,
          after_vault_digest: "c".repeat(64),
          after_generation: 1,
          added_entry_ids: [],
          updated_entry_ids: [],
          created_at: "2026-08-31T00:00:00Z",
          undone: true,
        },
        restored_vault_digest: "b".repeat(64),
      });
      return;
    }

    if (method === "POST" && url.pathname === "/entries/commit") {
      const value = body(route);
      if (this.commitDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, this.commitDelayMs));
      }
      const transactionId = String(value.transaction_id || "");
      const receiptId = this.transactionReceipts.get(transactionId);
      if (receiptId) {
        await this.respond(route, 200, clone(this.entries.get(receiptId)));
        return;
      }
      const additions = Array.isArray(value.add_attachments)
        ? value.add_attachments as Array<Record<string, unknown>>
        : [];
      if (additions.some((item) => String(item.filename) === "generated-fail-third.txt")) {
        await this.respond(route, 500, { detail: "Entry was not saved; no changes were committed" });
        return;
      }
      const requestedId = typeof value.entry_id === "string" ? value.entry_id : "";
      const existing = requestedId ? this.entries.get(requestedId) : undefined;
      if (requestedId && !existing) {
        await this.respond(route, 404, { detail: "Generated entry not found" });
        return;
      }
      if (existing && value.expected_updated_at !== existing.updated_at) {
        await this.respond(route, 409, { detail: "Entry changed after this editor was opened; reload before saving" });
        return;
      }
      const id = existing?.id || `generated-entry-${testData.runId}-${this.entries.size + 1}`;
      const removed = new Set(Array.isArray(value.remove_attachment_ids) ? value.remove_attachment_ids.map(String) : []);
      const keptAttachments = (existing?.attachments || []).filter((item) => !removed.has(String(item.id)));
      const addedAttachments = additions.map((item, index) => ({
        id: `generated-attachment-${this.revision}-${index}`,
        filename: String(item.filename || ""),
        mime_type: String(item.mime_type || "application/octet-stream"),
        size: Math.max(1, Math.floor(String(item.data_b64 || "").length * 0.75)),
        sha256: "0".repeat(64),
      }));
      const now = this.timestamp();
      if (existing) {
        const entryHistory = this.histories.get(id) || [];
        entryHistory.unshift({
          id: `generated-history-${this.revision}`,
          saved_at: now,
          snapshot: clone(existing),
        });
        this.histories.set(id, entryHistory);
      }
      const committed: StoredEntry = {
        id,
        title: String(value.title || ""),
        username: String(value.username || ""),
        password: String(value.password || ""),
        url: String(value.url || ""),
        notes: String(value.notes || ""),
        has_password: Boolean(value.password),
        has_notes: Boolean(value.notes),
        source: "local",
        tags: Array.isArray(value.tags) ? value.tags.map(String) : [],
        sync_status: "dirty",
        linked_sources: existing?.linked_sources || {},
        entry_type: (value.entry_type || "login") as StoredEntry["entry_type"],
        custom_fields: Array.isArray(value.custom_fields) ? value.custom_fields as StoredEntry["custom_fields"] : [],
        totp_secret: String(value.totp_secret || ""),
        has_totp_secret: Boolean(value.totp_secret),
        attachments: [...keptAttachments, ...addedAttachments],
        history_count: this.histories.get(id)?.length || 0,
        created_at: existing?.created_at || now,
        updated_at: now,
      };
      this.entries.set(id, committed);
      this.transactionReceipts.set(transactionId, id);
      if (existing) this.writes.update += 1;
      else this.writes.create += 1;
      await this.respond(route, 200, clone(committed));
      return;
    }

    if (method === "POST" && url.pathname === "/entries") {
      const value = body(route);
      const id = `generated-entry-${testData.runId}`;
      const entry: StoredEntry = {
        id,
        title: String(value.title || ""),
        username: String(value.username || ""),
        password: String(value.password || ""),
        url: String(value.url || ""),
        notes: String(value.notes || ""),
        has_password: Boolean(value.password),
        has_notes: Boolean(value.notes),
        source: "local",
        tags: Array.isArray(value.tags) ? value.tags.map(String) : [],
        sync_status: "dirty",
        linked_sources: {},
        entry_type: (value.entry_type || "login") as StoredEntry["entry_type"],
        custom_fields: Array.isArray(value.custom_fields)
          ? (value.custom_fields as StoredEntry["custom_fields"])
          : [],
        totp_secret: String(value.totp_secret || ""),
        has_totp_secret: Boolean(value.totp_secret),
        attachments: [],
        history_count: 0,
        created_at: this.timestamp(),
        updated_at: this.timestamp(),
      };
      this.entries.set(id, entry);
      this.writes.create += 1;
      await this.respond(route, 200, clone(entry));
      return;
    }

    const historyMatch = url.pathname.match(/^\/entries\/([^/]+)\/history$/);
    if (method === "GET" && historyMatch) {
      const id = decodeURIComponent(historyMatch[1]);
      const values = (this.histories.get(id) || []).map(({ id: historyId, saved_at }) => ({
        id: historyId,
        saved_at,
        snapshot: {},
      }));
      await this.respond(route, 200, { history: values });
      return;
    }

    const historyPreviewMatch = url.pathname.match(/^\/entries\/([^/]+)\/history\/([^/]+)$/);
    if (method === "GET" && historyPreviewMatch) {
      const id = decodeURIComponent(historyPreviewMatch[1]);
      const historyId = decodeURIComponent(historyPreviewMatch[2]);
      const selected = (this.histories.get(id) || []).find((item) => item.id === historyId);
      if (!selected) {
        await this.respond(route, 404, { detail: "Generated history version not found" });
        return;
      }
      await this.respond(route, 200, { history_id: historyId, entry: clone(selected.snapshot) });
      return;
    }

    const copyMatch = url.pathname.match(/^\/entries\/([^/]+)\/copy$/);
    if (method === "POST" && copyMatch) {
      await this.respond(route, 200, { copied: "password", clears_in_seconds: 45 });
      return;
    }

    const entryMatch = url.pathname.match(/^\/entries\/([^/]+)$/);
    if (entryMatch) {
      const id = decodeURIComponent(entryMatch[1]);
      const entry = this.entries.get(id);
      if (!entry) {
        await this.respond(route, 404, { detail: "Generated entry not found" });
        return;
      }
      if (method === "GET") {
        await this.respond(
          route,
          200,
          url.searchParams.get("reveal") === "true" ? clone(entry) : this.listed(entry),
        );
        return;
      }
      if (method === "PATCH") {
        const value = body(route);
        this.entries.set(id, { ...entry, ...value } as StoredEntry);
        this.writes.update += 1;
        await this.respond(route, 200, clone(this.entries.get(id)));
        return;
      }
      if (method === "DELETE") {
        this.entries.delete(id);
        this.writes.delete += 1;
        await this.respond(route, 200, { deleted: entry.title });
        return;
      }
    }

    await this.respond(route, 501, {
      detail: `Unhandled mock route: ${method} ${url.pathname}`,
    });
  }
}
