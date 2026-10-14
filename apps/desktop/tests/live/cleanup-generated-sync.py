"""Remove only sync credentials belonging to this generated renderer fixture."""
import json
import os
from pathlib import Path
import sys
import tempfile

from vault_unified.local_store import LocalVault
from vault_unified.personal_sync.connections import Connections, SERVICE
from vault_unified.personal_sync.codec import STATE_NAMESPACE
from vault_unified.device_keyring import get_approved_backend

directory = Path(sys.argv[1]).resolve()
if directory.parent != Path(tempfile.gettempdir()).resolve() or not directory.name.startswith("vault-renderer-generated-"):
    raise RuntimeError("Generated sync cleanup boundary failed")
path = directory / "generated.vault"
if path.exists():
    local = LocalVault(path, os.environ["UI_GENERATED_SYNC_MASTER"])
    state = local.metadata_value(STATE_NAMESPACE)
    manager = Connections(config_dir=directory / "config")
    if manager._bound(local, state):
        backend = get_approved_backend()
        account = manager._account(state["connection"])
        if backend.get_password(SERVICE, account) is not None:
            backend.delete_password(SERVICE, account)
