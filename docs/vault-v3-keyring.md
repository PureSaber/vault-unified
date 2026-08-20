# Vault Format v3 device keyring boundary

V3 device unlock is an explicit convenience feature for Windows. It never stores the master
password. The vault keeps its Argon2id password recovery slot and adds one device slot that
wraps the same DEK with a random 32-byte device KEK. Only that random KEK is written to the OS
keyring; the file contains the authenticated wrapped DEK.

Python keyring permits users and installed packages to select third-party backends, so a high
priority alone is not a security decision. Production device and anchor operations require
Windows and the exact core backend class `keyring.backends.Windows.WinVaultKeyring`. Null,
plaintext, chained, configured third-party, and non-Windows backends are rejected without a
file or environment fallback. Upstream documents the configurable backend mechanism and
`get_password`/`set_password`/`delete_password` API in the
[keyring documentation](https://keyring.readthedocs.io/en/stable/); the upstream
[`WinVaultKeyring` source](https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py)
states that it stores encrypted passwords with Windows Credential Manager.

This is not a second authentication factor. A process running as the same unlocked Windows
user may be able to request the KEK. It does not protect an already unlocked process or defend
against administrator, kernel, or same-user process compromise. Tests inject an in-memory
fake backend and never call the real keyring.

## Device lifecycle

Use a hidden password prompt where possible:

```powershell
.\vault.cmd v3 device-enable --vault-path C:\isolated\vault.vault
.\vault.cmd v3 device-disable --vault-path C:\isolated\vault.vault
```

Enablement authenticates both the existing password slot and payload, writes a newly generated
KEK to the scoped account `vault_id:slot_id`, builds and validates both unlock paths, and then
uses the compare-and-swap atomic writer. If activation fails, it removes the new keyring record;
if cleanup also fails, it reports that manual removal is required. Disablement does the reverse:
it first activates and validates a password-only vault, then deletes the external record. A
deletion failure leaves an orphan keyring item but not a device-unlockable vault.

Both operations increment `key_generation`, refresh the password-slot salt and wrap nonce, bind
the device backend/slot/generation in AES-GCM AAD, and preserve the payload ciphertext. The parser
requires at least one password recovery slot and permits at most one device slot. Password and
DEK rotation fail closed while a device slot exists; explicitly disable, rotate, and re-enable.

The legacy encrypted `conflicts.vault` sidecar still requires the master password. A device-only
session refuses to open when this sidecar exists and refuses to create/update it, rather than
silently dropping conflict state. Consolidating that state into the reviewed sync/conflict data
model belongs to 5f; use a password session for sync workflows until then.

## Optional rollback anchor

The anchor is opt-in and separate from the device KEK:

```powershell
.\vault.cmd v3 rollback-anchor enable --vault-path C:\isolated\vault.vault
.\vault.cmd v3 rollback-anchor verify --vault-path C:\isolated\vault.vault
.\vault.cmd v3 rollback-anchor inspect --vault-path C:\isolated\vault.vault
.\vault.cmd v3 rollback-anchor disable --vault-path C:\isolated\vault.vault
```

Enabling adds an authenticated file marker and stores only version, `vault_id`, content
generation, key generation, and whole-file SHA-256 in a separate keyring record. It stores no
password, KEK, or DEK. After successful authentication, lower content/key generations or a
different digest at the same generations fail with rollback detection; a valid monotonic advance
updates the anchor. File writes activate before the anchor advances, so an anchor write failure
cannot make the prior live file look rolled back before activation.

If the anchor record or approved backend is unavailable, password recovery still works and the
check reports unavailable/missing; rollback detection is degraded. Disabling first removes the
authenticated marker, then deletes the external record. Backups remain explicit recovery
evidence and may intentionally be rejected while the anchor is enabled; disable the anchor with
an authenticated current vault before a deliberate rollback.

## Test and recovery contract

The tests cover exact backend rejection, password/device round trips, set-before-activate and
activate-before-delete ordering, cleanup failures, session unlock and edits, slot tampering,
rotation refusal, anchor advance, authenticated old-file replay, same-generation digest conflict,
and missing-anchor degradation. They use generated fake vaults under isolated temporary paths.

Neither device-slot nor anchor commands migrate legacy files, publish a release, delete atomic
backups, or access third-party password managers. Storage interruptions continue through
`vault storage inspect` and dry-run-first `vault storage recover`.
