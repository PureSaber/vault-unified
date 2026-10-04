"""Isolated native-messaging fixture; never touches the product's registry keys."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path


def main():
    operation, directory, name = sys.argv[1:4]
    root = Path(directory).resolve()
    if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith("vault-trust-live-"):
        raise ValueError("Fixture directory is not isolated")
    if not re.fullmatch(r"org\.vaultunified\.test_[a-f0-9]{16}", name):
        raise ValueError("Fixture host name is not isolated")
    import winreg
    from vault_unified.browser_discovery import REGISTRY_BROWSERS
    keys = [browser + "\\" + name for browser in REGISTRY_BROWSERS]
    if operation == "register":
        executable, origin = sys.argv[4:6]
        if not Path(executable).is_file() or not re.fullmatch(r"chrome-extension://[a-p]{32}/", origin):
            raise ValueError("Invalid fixture manifest")
        for path in keys:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path):
                    raise ValueError("Fixture host name already exists")
            except FileNotFoundError:
                pass
        bridge = root / "bridge"
        bridge.mkdir(exist_ok=True)
        manifest = bridge / "native-host.json"
        manifest.write_text(json.dumps({"name": name, "description": "Generated isolated bridge test",
            "path": executable, "type": "stdio", "allowed_origins": [origin]}), encoding="utf-8")
        created = []
        try:
            for path in keys:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                    created.append(path)
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))
        except Exception:
            for path in created:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            raise
    elif operation == "clean":
        for path in keys:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                    value = winreg.QueryValueEx(key, "")[0]
                if Path(value).resolve() != root / "bridge" / "native-host.json":
                    raise ValueError("Fixture registry target changed")
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass
        os.environ["VAULT_CONFIG_DIR"] = str(root / "config")
        from vault_unified.browser_trust import BrowserTrustStore
        store = BrowserTrustStore()
        for device in store._index():
            record = store._record(device)
            if record:
                store.revoke(tuple(record["binding"]), device)
        if store._read("index") is not None:
            store._delete("index")
    else:
        raise ValueError("Unknown fixture operation")


if __name__ == "__main__":
    main()
