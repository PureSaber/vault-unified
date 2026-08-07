from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vault_unified.api.routes import auth, entries, sync
from vault_unified.env import load_env

load_env()


def create_app() -> FastAPI:
    app = FastAPI(title="Vault Unified API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router, prefix="/api")
    app.include_router(entries.router, prefix="/api")
    app.include_router(sync.router, prefix="/api")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.environ.get("VAULT_API_HOST", "127.0.0.1")
    port = int(os.environ.get("VAULT_API_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
