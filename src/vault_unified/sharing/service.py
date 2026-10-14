"""Separately deployed ciphertext service; never mounts the desktop API."""
from __future__ import annotations

import argparse
import hmac
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from .protocol import MAX_BODY, SharingError, identifier
from .store import ServiceError, Store


class BodyLimit:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http": return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect": return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY:
                return await JSONResponse({"detail": "Sharing request is too large"}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False): break
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, bounded_receive, send)


def create_app(*, database: Path, admin_token: str, clock=None, quota_bytes=256 * 1024 * 1024):
    if not isinstance(admin_token, str) or not 32 <= len(admin_token) <= 256: raise SharingError("Configure a sharing administration token of at least 32 characters")
    app = FastAPI(title="Vault Unified Sharing", docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(database, quota_bytes=quota_bytes, **({"clock": clock} if clock else {}))
    app.state.store = store
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})
        return response

    @app.exception_handler(SharingError)
    async def protocol_error(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=getattr(error, "status", 400))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _error):
        return JSONResponse({"detail": "Invalid sharing request"}, status_code=422)

    async def malformed(_request, _error):
        return JSONResponse({"detail": "Invalid sharing document"}, status_code=400)
    for error_type in (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        app.add_exception_handler(error_type, malformed)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(_request, _error):
        return JSONResponse({"detail": "Sharing storage is temporarily unavailable"}, status_code=503)

    def admin(request):
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + admin_token):
            raise ServiceError(401, "Sharing service administration token required")

    @app.get("/health")
    def health(): return {"status": "ok", "protocol": 1}

    @app.post("/v1/shares")
    def create_share(body: dict, request: Request):
        admin(request)
        return store.share_create(body, request.url.path)

    @app.post("/v1/shares/{sid}/read")
    def read_share(sid: str, body: dict): return store.share_read(sid, body)

    @app.post("/v1/shares/{sid}/{action}")
    def manage_share(sid: str, action: str, body: dict, request: Request):
        if action not in {"status", "revoke"}: raise ServiceError(404, "Unknown share action")
        return store.share_manage(body, request.url.path, sid, action,
                                  allow_missing=hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + admin_token))

    @app.post("/v1/families")
    def create_family(body: dict, request: Request):
        admin(request)
        return store.family_create(body, request.url.path)

    @app.post("/v1/families/{gid}/{action}")
    def family(gid: str, action: str, body: dict, request: Request):
        return store.family_operation(body, request.url.path, gid, action)

    static = Path(__file__).with_name("web")
    @app.get("/s/{sid}")
    def viewer(sid: str):
        identifier(sid)
        return FileResponse(static / "share.html", media_type="text/html")

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in {"share.js", "share.css"}: raise ServiceError(404, "Asset not found")
        return FileResponse(static / name, media_type="text/javascript" if name.endswith(".js") else "text/css")

    return app


def main():
    parser = argparse.ArgumentParser(description="Run the optional Vault Unified ciphertext sharing service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--database", type=Path, default=Path("data/sharing.db"))
    parser.add_argument("--admin-token-file", type=Path, default=os.environ.get("VAULT_SHARING_ADMIN_FILE"))
    args = parser.parse_args()
    if not args.admin_token_file: parser.error("--admin-token-file or VAULT_SHARING_ADMIN_FILE is required")
    token = args.admin_token_file.read_text(encoding="utf-8").strip()
    app = create_app(database=args.database, admin_token=token)
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, proxy_headers=False, limit_concurrency=100)


if __name__ == "__main__": main()
