import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import type { Page } from "@playwright/test";
import { testData } from "./test-data";

/** Real isolated API, with only Tauri's runtime-config handoff substituted. */
export async function startGeneratedSidecar(page: Page) {
  const root = resolve(process.cwd(), "../..");
  const directory = await mkdtemp(join(tmpdir(), "vault-renderer-generated-"));
  let child: ChildProcess | undefined;
  const stop = async () => {
    if (child?.pid && child.exitCode === null && child.signalCode === null) {
      const exited = new Promise<void>((accept) => child!.once("exit", () => accept()));
      child.kill();
      await exited;
    }
    const target = resolve(directory);
    if (dirname(target) !== resolve(tmpdir()) || !basename(target).startsWith("vault-renderer-generated-")) {
      throw new Error("Generated test directory is outside its cleanup boundary");
    }
    await rm(target, { recursive: true, force: true, maxRetries: 3 });
  };
  try {
    child = spawn(join(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"),
      ["-m", "vault_unified.api.app"], {
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
