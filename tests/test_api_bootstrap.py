from __future__ import annotations

import socket

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import _bind_server_socket, create_app

SECRET = "bootstrap-secret-for-tests-0123456789abcdef"
INSTANCE_ID = "sidecar-test-instance"


def test_bootstrap_secret_is_required_for_health_and_unlock():
    app = create_app(bootstrap_secret=SECRET, instance_id=INSTANCE_ID)
    with TestClient(app) as client:
        missing = client.get("/api/health")
        assert missing.status_code == 403

        wrong = client.get(
            "/api/health",
            headers={"X-Vault-Bootstrap": "x" * 40},
        )
        assert wrong.status_code == 403

        healthy = client.get(
            "/api/health",
            headers={"X-Vault-Bootstrap": SECRET},
        )
        assert healthy.status_code == 200
        assert healthy.json() == {
            "status": "ok",
            "instance_id": INSTANCE_ID,
        }

        unlock_without_secret = client.post(
            "/api/auth/unlock",
            json={"password": "not-sent-to-an-untrusted-process", "remember": False},
        )
        assert unlock_without_secret.status_code == 403


def test_cors_preflight_may_negotiate_bootstrap_header_without_revealing_data():
    app = create_app(bootstrap_secret=SECRET, instance_id=INSTANCE_ID)
    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-vault-bootstrap",
            },
        )
        assert response.status_code in (200, 204)
        assert response.headers.get("access-control-allow-origin") == "tauri://localhost"
        assert "x-vault-bootstrap" in response.headers.get(
            "access-control-allow-headers", ""
        ).lower()


def test_random_port_is_bound_by_the_sidecar_before_it_is_announced():
    server_socket = _bind_server_socket("127.0.0.1", 0)
    try:
        host, port = server_socket.getsockname()[:2]
        assert host == "127.0.0.1"
        assert 0 < port <= 65535

        competing = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError):
                competing.bind((host, port))
        finally:
            competing.close()
    finally:
        server_socket.close()


def test_explicit_weak_bootstrap_secret_is_rejected():
    with pytest.raises(ValueError, match="at least 32"):
        create_app(bootstrap_secret="too-short", instance_id=INSTANCE_ID)
