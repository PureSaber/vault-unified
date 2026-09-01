from __future__ import annotations

import hmac
import json
import os
import secrets
import socket

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from vault_unified.api.routes import auth, backups, browser, entries, integrations, personal, sync, transfer
from vault_unified.env import load_env

load_env()

READY_PREFIX = "VAULT_API_READY "
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
MIN_BOOTSTRAP_SECRET_LENGTH = 32


def _resolve_bootstrap_secret(value: str | None = None) -> str:
    """Return a per-process sidecar secret, rejecting weak explicit values."""
    explicit = value if value is not None else os.environ.get("VAULT_API_BOOTSTRAP_SECRET")
    secret = (explicit or "").strip()
    if not secret:
        secret = secrets.token_urlsafe(32)
    if len(secret) < MIN_BOOTSTRAP_SECRET_LENGTH:
        raise ValueError(
            f"VAULT_API_BOOTSTRAP_SECRET must be at least {MIN_BOOTSTRAP_SECRET_LENGTH} characters"
        )
    return secret


def create_app(
    *,
    bootstrap_secret: str | None = None,
    instance_id: str | None = None,
) -> FastAPI:
    docs_url = None if os.environ.get("VAULT_API_DISABLE_DOCS", "1") == "1" else "/docs"
    secret = _resolve_bootstrap_secret(bootstrap_secret)
    runtime_instance_id = instance_id or secrets.token_urlsafe(18)

    app = FastAPI(
        title="Vault Unified API",
        version="1.3.0",
        docs_url=docs_url,
        redoc_url=None if docs_url is None else "/redoc",
    )
    app.state.bootstrap_secret = secret
    app.state.instance_id = runtime_instance_id

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_origin_regex=r"chrome-extension://[a-p]{32}",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Vault-Bootstrap",
            "X-Vault-Client",
            "X-Vault-Browser-Pairing",
            "X-Vault-Browser-Token",
        ],
    )
    app.include_router(auth.router, prefix="/api")
    app.include_router(browser.router, prefix="/api")
    app.include_router(backups.router, prefix="/api")
    app.include_router(entries.router, prefix="/api")
    app.include_router(integrations.router, prefix="/api")
    app.include_router(personal.router, prefix="/api")
    app.include_router(sync.router, prefix="/api")
    app.include_router(transfer.router, prefix="/api")

    @app.get("/api/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "instance_id": runtime_instance_id,
        }

    @app.middleware("http")
    async def sidecar_security_guard(request: Request, call_next):
        client = request.client.host if request.client else ""
        allow_remote = os.environ.get("VAULT_API_ALLOW_REMOTE", "") == "1"
        if not allow_remote and client and client not in LOOPBACK_HOSTS:
            return JSONResponse({"detail": "Loopback only"}, status_code=403)
        if request.method == "OPTIONS":
            return await call_next(request)
        provided = request.headers.get("x-vault-bootstrap", "")
        browser_pair = (
            request.method == "POST"
            and request.url.path == "/api/browser/pair"
            and bool(request.headers.get("x-vault-browser-pairing"))
        )
        browser_token = (
            request.method in {"GET", "POST"}
            and request.url.path in {"/api/browser/matches", "/api/browser/fill"}
            and bool(request.headers.get("x-vault-browser-token"))
        )
        if browser_pair or browser_token:
            return await call_next(request)
        if not provided or not hmac.compare_digest(provided, secret):
            return JSONResponse(
                {"detail": "Sidecar authentication failed"},
                status_code=403,
            )
        return await call_next(request)

    return app


app = create_app()


def _bind_server_socket(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    server_socket = socket.socket(family, socket.SOCK_STREAM)
    try:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            server_socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        server_socket.bind((host, port))
        server_socket.listen(2048)
        return server_socket
    except Exception:
        server_socket.close()
        raise


def main() -> None:
    import uvicorn

    host = os.environ.get("VAULT_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host == "localhost":
        host = "127.0.0.1"
    allow_remote = os.environ.get("VAULT_API_ALLOW_REMOTE", "") == "1"
    if host not in ("127.0.0.1", "::1") and not allow_remote:
        raise SystemExit(
            f"Refusing to bind VAULT_API_HOST={host!r}. "
            "Use 127.0.0.1 or set VAULT_API_ALLOW_REMOTE=1"
        )

    try:
        requested_port = int(os.environ.get("VAULT_API_PORT", "0"))
    except ValueError as exc:
        raise SystemExit("VAULT_API_PORT must be an integer") from exc
    if requested_port < 0 or requested_port > 65535:
        raise SystemExit("VAULT_API_PORT must be between 0 and 65535")

    secret = _resolve_bootstrap_secret()
    instance_id = os.environ.get("VAULT_API_INSTANCE_ID", "").strip()
    if not instance_id:
        instance_id = secrets.token_urlsafe(18)

    runtime_app = create_app(
        bootstrap_secret=secret,
        instance_id=instance_id,
    )
    server_socket = _bind_server_socket(host, requested_port)
    actual_port = int(server_socket.getsockname()[1])

    ready = {
        "host": host,
        "port": actual_port,
        "bootstrap_secret": secret,
        "instance_id": instance_id,
    }
    print(
        READY_PREFIX + json.dumps(ready, separators=(",", ":")),
        flush=True,
    )

    config = uvicorn.Config(
        runtime_app,
        host=host,
        port=actual_port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run(sockets=[server_socket])


if __name__ == "__main__":
    main()
