from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_desktop_has_no_fixed_port_or_existing_process_reuse():
    rust = read("apps/desktop/src-tauri/src/lib.rs")
    launcher = read("launch-desktop.ps1")
    integrations = read("configure-integrations.ps1")
    translations = read("apps/desktop/src/i18n/index.tsx")

    assert "127.0.0.1:8765" not in rust
    assert "127.0.0.1:8765" not in launcher
    assert "VAULT_API_PORT=8765" not in integrations
    assert "VAULT_API_PORT=0" in integrations
    assert "port 8765" not in translations
    assert "端口 8765" not in translations
    assert "API already healthy" not in rust
    assert "Invoke-WebRequest" not in launcher
    assert '.env("VAULT_API_PORT", "0")' in rust
    assert "read_sidecar_ready" in rust
    assert "wait_for_health(&ready" in rust
    assert "CREATE_SUSPENDED" in rust
    assert "AssignProcessToJobObject" in rust
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in rust
    assert "TerminateJobObject" in rust
    assert "tauri::WindowEvent::Destroyed" in rust
    assert "tauri::RunEvent::ExitRequested" in rust
    assert 'label == "main"' in rust
    assert "app.exit(0)" in rust


def test_native_window_close_preserves_draft_confirmation_before_destroy():
    renderer = read("apps/desktop/src/App.tsx")
    capabilities = json.loads(read("apps/desktop/src-tauri/capabilities/default.json"))

    assert 'import { isTauri } from "@tauri-apps/api/core"' in renderer
    assert "if (!isTauri()) return" in renderer
    assert 'import { getCurrentWindow } from "@tauri-apps/api/window"' in renderer
    assert ".onCloseRequested(async (event) =>" in renderer
    assert "event.preventDefault()" in renderer
    assert 'setPendingAction({ kind: "close" })' in renderer
    assert 'kind: "close"' in renderer
    assert "await getCurrentWindow().destroy()" in renderer
    assert "Discard changes and close?" in renderer
    assert capabilities["windows"] == ["main"]
    assert "core:window:allow-destroy" in capabilities["permissions"]


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
