import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

/** Actual loopback WebDAV fixture; it sees only encrypted record bytes. */
export async function generatedWebDAV(username: string, password: string) {
  const files = new Map<string, Buffer>();
  const state = { offline: false };
  const server = createServer(async (request, response) => {
    if (state.offline) { response.writeHead(503).end(); return; }
    if (request.headers.authorization !== `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`) { response.writeHead(401).end(); return; }
    const path = new URL(request.url || "/", "http://127.0.0.1").pathname;
    if (request.method === "MKCOL") { response.writeHead(201).end(); return; }
    if (request.method === "PROPFIND") {
      for await (const chunk of request) { void chunk; }
      const listing = [...files.keys()].filter(key => key.startsWith(path)).map(key => `<d:response><d:href>${key}</d:href></d:response>`).join("");
      response.writeHead(207, { "Content-Type": "application/xml" }).end(`<d:multistatus xmlns:d="DAV:">${listing}</d:multistatus>`); return;
    }
    if (request.method === "GET") { const bytes = files.get(path); response.writeHead(bytes ? 200 : 404).end(bytes); return; }
    if (request.method === "PUT") {
      const parts: Buffer[] = []; for await (const part of request) parts.push(Buffer.from(part));
      if (files.has(path)) { response.writeHead(request.headers["if-none-match"] === "*" ? 412 : 409).end(); return; }
      files.set(path, Buffer.concat(parts)); response.writeHead(201).end(); return;
    }
    response.writeHead(405).end();
  });
  await new Promise<void>(accept => server.listen(0, "127.0.0.1", accept));
  return { address: `http://127.0.0.1:${(server.address() as AddressInfo).port}/generated/`, state,
    stop: () => new Promise<void>((accept, reject) => server.close(error => error ? reject(error) : accept())) };
}
