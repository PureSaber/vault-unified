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

  readonly writes = { create: 0, update: 0, delete: 0 };

  get persistedEntries(): StoredEntry[] {
    return Array.from(this.entries.values(), clone);
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
        lock_after_seconds: 900,
        auto_backup_enabled: false,
        auto_backup_interval_hours: 24,
        auto_backup_destination: "",
        last_auto_backup_at: "",
      });
      return;
    }

    if (method === "POST" && url.pathname === "/personal/maintenance") {
      await this.respond(route, 200, {
        settings: {
          lock_after_seconds: 900,
          auto_backup_enabled: false,
          auto_backup_interval_hours: 24,
          auto_backup_destination: "",
          last_auto_backup_at: "",
        },
        components: { conflicts: "0" },
        notices: [],
      });
      return;
    }

    if (method === "GET" && url.pathname === "/sync/conflicts") {
      await this.respond(route, 200, []);
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
      };
      this.entries.set(id, entry);
      this.writes.create += 1;
      await this.respond(route, 200, clone(entry));
      return;
    }

    const historyMatch = url.pathname.match(/^\/entries\/([^/]+)\/history$/);
    if (method === "GET" && historyMatch) {
      await this.respond(route, 200, { history: [] });
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
