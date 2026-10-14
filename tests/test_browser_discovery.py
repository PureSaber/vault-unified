import json
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from vault_unified.api.app import create_app
from vault_unified import browser_discovery as discovery


def test_public_runtime_contains_no_authentication_material_and_cleans_only_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_BROWSER_DISCOVERY_DIR", str(tmp_path))
    discovery.publish(43210, "generated-instance")
    path = tmp_path / "runtime.json"
    assert json.loads(path.read_text()) == {"protocol": 1, "base_url": "http://127.0.0.1:43210/api", "instance_id": "generated-instance"}
    discovery.clear("older-process")
    assert path.exists()
    discovery.clear("generated-instance")
    assert not path.exists()


def test_discovery_is_public_but_other_api_paths_still_require_authentication():
    with TestClient(create_app(instance_id="generated-instance")) as client:
        assert client.get("/api/browser/discovery").json() == {"protocol": 1, "instance_id": "generated-instance"}
        assert client.get("/api/health").status_code == 403
        assert client.get("/api/browser/devices").status_code == 403
        assert client.post("/api/browser/discovery").status_code == 403


def test_registration_uses_only_exact_authorized_extension_origins(tmp_path, monkeypatch):
    # Exercise registration without writing any real browser registry key.
    executable = tmp_path / "generated.exe"
    executable.write_bytes(b"generated-fixture")
    monkeypatch.setenv("VAULT_BROWSER_DISCOVERY_DIR", str(tmp_path))
    monkeypatch.setenv("VAULT_BROWSER_HOST_EXE", str(executable))
    writes = []
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    fake = SimpleNamespace(HKEY_CURRENT_USER=1, KEY_SET_VALUE=2, REG_SZ=3,
                           CreateKeyEx=lambda *args: Key(),
                           SetValueEx=lambda *args: writes.append(args[-1]))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    if discovery.os.name != "nt":
        # The production path is intentionally Windows-only.
        assert not discovery.register("chrome-extension://" + "a" * 32)
        return
    assert not discovery.register("https://attacker.invalid")
    assert writes == []
    first, second = "chrome-extension://" + "a" * 32, "chrome-extension://" + "b" * 32
    assert discovery.register(first)
    assert discovery.register(second)
    manifest = json.loads((tmp_path / "native-host.json").read_text())
    assert manifest["allowed_origins"] == [first + "/", second + "/"]
    assert manifest["path"] == str(executable.resolve())
    assert len(writes) == 4
    writes.clear()  # A manual installer removed registry keys, not local state.
    assert discovery.restore_registration()
    assert len(writes) == 2
    assert json.loads((tmp_path / "native-host.json").read_text())["allowed_origins"] == [first + "/", second + "/"]
    assert {item.name for item in tmp_path.iterdir()} == {"native-host.json", "generated.exe"}


def test_startup_never_registers_new_or_unowned_browser_manifest(tmp_path, monkeypatch):
    executable = tmp_path / "generated.exe"; executable.write_bytes(b"generated")
    other = tmp_path / "other.exe"; other.write_bytes(b"generated")
    monkeypatch.setenv("VAULT_BROWSER_DISCOVERY_DIR", str(tmp_path))
    monkeypatch.setenv("VAULT_BROWSER_HOST_EXE", str(executable))
    called = []
    monkeypatch.setattr(discovery, "register", lambda origin: called.append(origin) or True)
    assert not discovery.restore_registration()
    value = {"name": discovery.HOST_NAME, "type": "stdio", "path": str(executable), "allowed_origins": ["chrome-extension://" + "a" * 32 + "/"]}
    path = tmp_path / "native-host.json"
    for changes in ({"path": str(other)}, {"path": "generated.exe"}, {"name": "other.host"}, {"allowed_origins": ["https://unapproved.invalid/"]}, {"allowed_origins": []}):
        path.write_text(json.dumps({**value, **changes}))
        assert not discovery.restore_registration()
    path.write_text("not-json")
    assert not discovery.restore_registration()
    assert called == []
