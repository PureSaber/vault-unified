import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import type { Page, Request } from "@playwright/test";
import { testData } from "./test-data";

/** Real isolated API, with only Tauri's runtime-config handoff substituted. */
export async function startGeneratedSidecar(page: Page, options: { oldPayload?: boolean } = {}) {
  const root = resolve(process.cwd(), "../..");
  const directory = await mkdtemp(join(tmpdir(), "vault-renderer-generated-"));
  let child: ChildProcess | undefined;
  const pending = new Set<Request>();
  let changed = () => {};
  const started = (request: Request) => { pending.add(request); changed(); };
  const finished = (request: Request) => { pending.delete(request); changed(); };
  page.on("request", started);
  page.on("requestfinished", finished);
  page.on("requestfailed", finished);
  const stop = async () => {
    if (child?.pid && child.exitCode === null && child.signalCode === null) {
      const exited = new Promise<void>((accept) => child!.once("exit", () => accept()));
      try {
        // waitForLoadState can reuse an earlier idle state. Observe a fresh quiet
        // interval instead, so cancellation and unlock effects finish before exit.
        if (!page.isClosed()) await new Promise<void>((accept, reject) => {
          let quiet: ReturnType<typeof setTimeout> | undefined;
          const deadline = setTimeout(() => {
            clearTimeout(quiet);
            changed = () => {};
            reject(new Error("Generated API still has pending renderer requests"));
          }, 5000);
          changed = () => {
            clearTimeout(quiet);
            if (!pending.size) quiet = setTimeout(() => {
              clearTimeout(deadline);
              changed = () => {};
              accept();
            }, 500);
          };
          changed();
        });
      } finally {
        child.kill();
        await exited;
        page.off("request", started);
        page.off("requestfinished", finished);
        page.off("requestfailed", finished);
      }
    }
    const target = resolve(directory);
    if (dirname(target) !== resolve(tmpdir()) || !basename(target).startsWith("vault-renderer-generated-")) {
      throw new Error("Generated test directory is outside its cleanup boundary");
    }
    await rm(target, { recursive: true, force: true, maxRetries: 3 });
  };
  try {
    child = spawn(join(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"),
      options.oldPayload ? ["-c", "import os; from pathlib import Path; from vault_unified.v3_crypto import create_v3_file; create_v3_file(Path(os.environ['VAULT_FILE']), os.environ['UI_TEST_MASTER_PASSWORD'], {'version': 2, 'entries': {}}); from vault_unified.api.app import main; main()"] : ["-m", "vault_unified.api.app"], {
        cwd: directory, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env, PYTHONPATH: join(root, "src"), PYTHONUNBUFFERED: "1",
          VAULT_API_BOOTSTRAP_SECRET: testData.bootstrapSecret, VAULT_API_PORT: "0",
          VAULT_API_HOST: "127.0.0.1", VAULT_DATA_DIR: directory,
          VAULT_FILE: join(directory, "generated.vault"), VAULT_CONFIG_DIR: join(directory, "config"),
        },
      });
    child.stderr!.on("data", () => {});
    const port = await new Promise<number>((accept, reject) => {
      let output = "";
      const timeout = setTimeout(() => reject(new Error("Generated API startup timed out")), 20_000);
      child!.once("error", () => { clearTimeout(timeout); reject(new Error("Generated API could not start")); });
      child!.once("exit", () => { clearTimeout(timeout); reject(new Error("Generated API exited")); });
      child!.stdout!.on("data", (chunk: Buffer) => {
        output += chunk.toString();
        const ready = output.split("\n").find((line) => line.startsWith("VAULT_API_READY "));
        if (ready) {
          clearTimeout(timeout);
          const value = JSON.parse(ready.slice(16)) as { port: number };
          output = "";
          accept(value.port);
        }
      });
    });
    await page.addInitScript((config) => {
      Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {
        invoke: async (command: string) => {
          if (command === "get_api_runtime_config") return config;
          throw new Error("Native commands are outside this renderer journey");
        },
      } });
    }, { base_url: `http://127.0.0.1:${port}/api`, bootstrap_secret: testData.bootstrapSecret, instance_id: "generated-renderer-api" });
    return { stop };
  } catch (error) {
    await stop();
    throw error;
  }
}
