from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from vault_unified.api.routes import auth, entries, sync
from vault_unified.env import load_env

load_env()


def create_app() -> FastAPI:
    docs_url = None if os.environ.get("VAULT_API_DISABLE_DOCS", "1") == "1" else "/docs"
    app = FastAPI(
        title="Vault Unified API",
        version="1.0.3",
        docs_url=docs_url,
        redoc_url=None if docs_url is None else "/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Vault-Client"],
    )
    app.include_router(auth.router, prefix="/api")
    app.include_router(entries.router, prefix="/api")
    app.include_router(sync.router, prefix="/api")

    @app.middleware("http")
    async def loopback_guard(request: Request, call_next):
        # Extra defense when mis-bound; TestClient uses "testclient".
        client = request.client.host if request.client else ""
        allow_remote = os.environ.get("VAULT_API_ALLOW_REMOTE", "") == "1"
        if not allow_remote and client and client not in {
            "127.0.0.1",
            "::1",
            "localhost",
            "testclient",
        }:
            return JSONResponse({"detail": "Loopback only"}, status_code=403)
        return await call_next(request)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.environ.get("VAULT_API_HOST", "127.0.0.1")
    allow_remote = os.environ.get("VAULT_API_ALLOW_REMOTE", "") == "1"
    if host not in ("127.0.0.1", "::1", "localhost") and not allow_remote:
        raise SystemExit(
            f"Refusing to bind VAULT_API_HOST={host!r}. "
            "Use 127.0.0.1 or set VAULT_API_ALLOW_REMOTE=1"
        )
    port = int(os.environ.get("VAULT_API_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
