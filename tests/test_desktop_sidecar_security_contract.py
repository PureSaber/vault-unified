from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_desktop_has_no_fixed_port_or_existing_process_reuse():
    rust = read("apps/desktop/src-tauri/src/lib.rs")
    launcher = read("launch-desktop.ps1")

    assert "127.0.0.1:8765" not in rust
    assert "127.0.0.1:8765" not in launcher
    assert "API already healthy" not in rust
    assert "Invoke-WebRequest" not in launcher
    assert '.env("VAULT_API_PORT", "0")' in rust
    assert "read_sidecar_ready" in rust
    assert "wait_for_health(&ready" in rust


def test_renderer_uses_authenticated_runtime_and_memory_only_session():
    client = read("apps/desktop/src/api/client.ts")

    assert 'invoke<ApiRuntimeConfig>("get_api_runtime_config")' in client
    assert 'requestHeaders.set("X-Vault-Bootstrap"' in client
    assert 'localStorage.getItem("vault_token")' not in client
    assert 'localStorage.setItem("vault_token"' not in client
    assert "let token: string | null = null" in client


def test_api_requires_bootstrap_header_and_instance_health_check():
    app = read("src/vault_unified/api/app.py")
    rust = read("apps/desktop/src-tauri/src/lib.rs")

    assert 'request.headers.get("x-vault-bootstrap"' in app
    assert '"/api/health"' in app
    assert 'get("instance_id")' in rust
    assert "hmac.compare_digest" in app
