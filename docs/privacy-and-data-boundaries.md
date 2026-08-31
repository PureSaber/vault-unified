# Privacy and data boundaries

Vault Unified is a local-first password manager. This document describes where data goes, what is intentionally retained, and which boundaries a contributor must not weaken.

## Default local behavior

- The desktop vault is encrypted on the user's device. A packaged Windows install normally stores it below `%LOCALAPPDATA%\VaultUnified`.
- Vault passwords, notes, custom secret fields, TOTP keys, recovery codes, and attachment contents are encrypted vault content.
- The desktop's bearer session token and per-launch bootstrap secret remain in renderer/process memory. Lock, reload, or exit invalidates them; they are not written to `localStorage` or `sessionStorage`.
- Secrets for optional external-service connections are stored through Windows Credential Manager. Non-secret connection configuration may be stored under the application's local configuration directory.
- The project does not include a telemetry, analytics, crash-upload, or user-tracking SDK. A future change to that boundary requires a separate public design and privacy review; it is outside the v1.3 feature freeze.

## Optional network boundaries

Vault Unified does not require an external password service for its core local workflow. If a user explicitly enables Bitwarden, KeePassXC, gopass, or Proton Pass, the chosen provider and its command-line client receive the data required for that requested operation under that provider's own terms.

The desktop background service listens only on a system-assigned loopback address and requires per-launch authentication. The browser extension pairs with the local desktop service using a short-lived code. Its token remains in `chrome.storage.session`, and lock, exit, expiry, or re-pairing invalidates the old token. Extension permissions must not be expanded as part of v1.3.

## Metadata that may be stored

Operational side files may retain non-secret metadata needed for correctness, such as:

- opaque entry or operation identifiers;
- enabled-source names and non-secret connection settings;
- generations, timestamps, state digests, file digests, sizes, and paths;
- backup health summaries and a sanitized last-error category;
- import receipt transaction IDs and added/updated entry IDs;
- synchronization operation type, direction, changed field names, and destructive status.

This metadata must not contain passwords, TOTP keys, recovery codes, full notes, attachment bytes, custom-field secret values, API tokens, provider command output, or plaintext imported records.

## Backups, recovery kits, and exports

- **Encrypted backup:** an encrypted copy for routine recovery. Backup paths and hashes may appear in backup history; decrypted contents must not.
- **Emergency recovery kit:** a separately encrypted recovery artifact whose code must be stored separately, preferably offline.
- **Plaintext export:** a short-lived migration file. It contains secrets, is not a backup, is never uploaded by Vault Unified, and should be deleted after use.

Restore validation reads, authenticates, and parses the selected encrypted source without changing the active vault. Apply requires an explicit, state-bound confirmation. A failed restore must leave the active vault bytes unchanged; a successful restore retains an encrypted copy of the replaced vault and locks the application.

## Logs, errors, tests, and support

Passwords, TOTP keys, recovery codes, attachments, token values, provider output, and imported file contents must never appear in logs, exceptions, pull requests, issues, screenshots, Playwright traces, CI artifacts, import receipts, or synchronization preview metadata.

All repository and release tests use disposable generated data and isolated directories. UI failure artifacts are scanned before upload. Repository reports must use minimal sanitized evidence. Never ask a user to upload a real vault or full log.

## User responsibilities

Users should keep the master password and recovery code offline and separate from backup files, verify backups periodically, protect the Windows account, and understand that malware or an administrator already controlling the unlocked device is outside the application's complete protection boundary.

See also [`sidecar-security.md`](sidecar-security.md), [`backup-retention-and-restore.md`](backup-retention-and-restore.md), and [`feature-freeze-v1.3.md`](feature-freeze-v1.3.md).
