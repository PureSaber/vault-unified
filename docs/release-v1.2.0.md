# Vault Unified v1.2.0

Vault Unified v1.2.0 adds a personal-use workflow while preserving the existing
Vault Format v3 container and external password-manager sync boundaries.

## Personal security and recovery

- Personal settings now provide configurable automatic lock timeouts and
  scheduled, verified encrypted backups. Select a folder synchronized by a
  cloud or NAS client to keep an off-device encrypted copy; the job runs only
  while the desktop vault is open and unlocked.
- Entries support types, custom fields, optional TOTP secrets, small encrypted
  attachments, and restorable field history.
- JSON and CSV transfer flows require explicit plaintext confirmation. JSON
  preserves personal extensions and attachments; CSV is for basic account
  migration.
- An emergency recovery kit is encrypted with a separate high-entropy recovery
  code. Restoring it creates a new active vault under a new master password and
  retains the prior encrypted active-vault copy through the normal atomic write
  path.

## Browser and mobile boundaries

- The optional Chromium extension uses a five-minute, one-time pairing code.
  Its browser token is origin-bound, memory-only, and invalid when the desktop
  vault locks or exits. It fetches a secret only after the user chooses a
  matching entry in the extension popup.
- The desktop sidecar remains loopback-only. Mobile access is supported through
  an explicitly configured external source and that provider's official mobile
  app; this release does not expose a LAN API.

## Compatibility and validation

- The v3 payload remains compatible: personal-only values are encrypted,
  namespaced entry metadata and are not written to external password-manager
  adapters.
- The Python test suite, desktop type check and production build, and Tauri
  library test pass before release. GitHub Actions rebuilds and verifies the
  Windows installer artifacts from this exact tag.
