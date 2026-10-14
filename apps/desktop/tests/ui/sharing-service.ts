import { spawn } from "node:child_process";
import { appendFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { testData } from "./test-data";

export async function startGeneratedSharing() {
  const root = resolve(process.cwd(), "../..");
  const directory = await mkdtemp(join(tmpdir(), "vault-sharing-generated-"));
  const child = spawn(join(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"), [join(root, "tests/helpers/sharing_service.py")], {
    cwd: directory, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONPATH: join(root, "src"), UI_TEST_BOOTSTRAP_SECRET: testData.bootstrapSecret, UI_TEST_ENTRY_PASSWORD: testData.entryPassword },
  });
  child.stderr.on("data", () => {});
  const stop = async () => {
    if (child.exitCode === null && child.signalCode === null) {
      const exited = new Promise<void>(accept => child.once("exit", () => accept())); child.kill(); await exited;
    }
    const target = resolve(directory);
    if (dirname(target) !== resolve(tmpdir()) || !basename(target).startsWith("vault-sharing-generated-")) throw new Error("Generated sharing cleanup boundary failed");
    await rm(target, { recursive: true, force: true, maxRetries: 3 });
  };
  try {
    const ready = await new Promise<{ port: number; seed_url: string }>((accept, reject) => {
      let output = "";
      const timer = setTimeout(() => reject(new Error("Generated sharing startup timeout")), 15000);
      child.once("error", () => { clearTimeout(timer); reject(new Error("Generated sharing could not start")); });
      child.once("exit", () => { clearTimeout(timer); reject(new Error("Generated sharing exited")); });
      child.stdout.on("data", chunk => { output += chunk.toString(); if (output.includes("\n")) { clearTimeout(timer); accept(JSON.parse(output.split("\n")[0])); } });
    });
    const fragment = new URLSearchParams(new URL(ready.seed_url).hash.slice(1));
    await appendFile(join(process.cwd(), ".playwright-runtime/secret-markers.txt"), `${fragment.get("key")}\n${fragment.get("cap")}\n`);
    return { url: `http://127.0.0.1:${ready.port}`, seedUrl: ready.seed_url, directory, stop };
  } catch (error) { await stop(); throw error; }
}
