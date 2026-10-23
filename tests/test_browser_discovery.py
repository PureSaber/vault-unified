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


def test_connect_nonce_is_owner_only_never_public_and_cleaned_with_its_run(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_BROWSER_DISCOVERY_DIR", str(tmp_path))
    assert discovery.publish(43210, "generated-instance", "generated-connect-nonce")
    assert "connect_nonce" not in (tmp_path / "runtime.json").read_text()
    path = tmp_path / discovery.CONNECT_FILE
    assert json.loads(path.read_text()) == {"instance_id": "generated-instance", "connect_nonce": "generated-connect-nonce"}
    assert {item.name for item in tmp_path.iterdir()} == {"runtime.json", discovery.CONNECT_FILE}
    if discovery.os.name == "nt":
        import subprocess
        acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True).stdout
        entries = [line.strip() for line in acl.replace(str(path), "").splitlines() if ":(" in line]
        # Only the owner, granted on the file itself: no inherited or group entries.
        assert entries == ["OWNER RIGHTS:(F)"], acl
    with TestClient(create_app(instance_id="generated-instance", connect_nonce="generated-connect-nonce")) as client:
        assert "connect_nonce" not in client.get("/api/browser/discovery").text
    discovery.clear("older-process")
    assert path.exists()
    discovery.clear("generated-instance")
    assert not path.exists()


def test_fixed_registration_keeps_the_fixed_origin_prunes_unused_and_never_takes_over(tmp_path, monkeypatch):
    executable = tmp_path / "generated.exe"; executable.write_bytes(b"generated")
    other = tmp_path / "other.exe"; other.write_bytes(b"generated")
    monkeypatch.setenv("VAULT_BROWSER_DISCOVERY_DIR", str(tmp_path))
    monkeypatch.setenv("VAULT_BROWSER_HOST_EXE", str(executable))
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    writes = []
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(HKEY_CURRENT_USER=1, KEY_SET_VALUE=2, REG_SZ=3,
                        CreateKeyEx=lambda *args: Key(), SetValueEx=lambda *args: writes.append(args[-1])))
    if discovery.os.name != "nt":
        assert not discovery.register_fixed()
        return
    fixed = next(iter(discovery.EXTENSION_ORIGINS)) + "/"
    old = ["chrome-extension://" + "".join(chr(97 + (index >> shift) % 16) for shift in range(32)) + "/" for index in range(32)]
    used = old[5][:-1]
    monkeypatch.setattr("vault_unified.browser_trust.browser_trust.origins", lambda: {used})
    path = tmp_path / "native-host.json"
    manifest = {"name": discovery.HOST_NAME, "type": "stdio", "path": str(other), "allowed_origins": old}
    path.write_text(json.dumps(manifest))
    assert not discovery.register_fixed(), "another existing installation keeps its manifest"
    assert json.loads(path.read_text()) == manifest and writes == []
    path.write_text(json.dumps({**manifest, "path": str(executable)}))
    assert discovery.register_fixed()
    assert json.loads(path.read_text())["allowed_origins"] == sorted([fixed, used + "/"])
    assert len(writes) == 2
    path.unlink()
    assert discovery.register_fixed(), "a new installation registers the fixed origin"
    assert json.loads(path.read_text())["allowed_origins"] == [fixed]


def test_fixed_extension_id_matches_the_manifest_public_key_and_the_desktop():
    import base64
    import hashlib
    from pathlib import Path
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "apps/browser-extension/manifest.json").read_text(encoding="utf-8"))
    raw = base64.b64decode(manifest["key"], validate=True)
    load_der_public_key(raw)  # Only the public half exists; a private key would not parse here.
    derived = "".join(chr(ord("a") + int(digit, 16)) for digit in hashlib.sha256(raw).hexdigest()[:32])
    assert derived == discovery.EXTENSION_ID
    assert discovery.EXTENSION_ORIGINS == {f"chrome-extension://{derived}"}
    assert f'"chrome-extension://{derived}"' in (root / "apps/desktop/src/components/ConnectionTools.tsx").read_text(encoding="utf-8")
    assert "alarms" in manifest["permissions"]
