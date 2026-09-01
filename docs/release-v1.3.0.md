# Vault Unified v1.3.0

Vault Unified v1.3.0 is a productization and reliability release for the existing Windows password manager. It freezes feature expansion and concentrates on atomic data changes, beginner-first navigation, complete import/sync/backup workflows, a deliverable browser extension, realistic generated-data journeys, and open-source governance.

## Beginner-first Windows experience

- The permanent top level is limited to Passwords, Security & recovery, Connections, Settings, and Lock now.
- Add password is the main action on the Passwords page. Conflict and synchronization controls appear only in context.
- New and edited logins start with essential fields; tags, TOTP keys, custom fields, attachments, history, and source details are progressively disclosed.
- Security & recovery begins with protection and backup status, then offers backup, verification, restore, retention history, and emergency-recovery actions.
- The README now starts with the installed Windows path rather than source setup.

## Data-integrity hardening

- Entry fields, attachment additions/removals, and history restoration commit as one backend transaction. Cancel means zero persistent writes.
- Import is preview-first, deterministic about duplicates, atomic as a batch, and produces a secret-free receipt with state-bound undo.
- Synchronization previews list item-level additions, changes, conflicts, and deletions without secret values. Stale previews and unreviewed deletes are rejected.
- Restore validation is read-only; apply is state-bound and atomic. A failed restore leaves the active vault bytes unchanged, while a successful restore retains an encrypted copy of the replaced vault and locks the application.
- Unsaved plaintext drafts remain in memory, are cleared by lock, and cannot permanently defeat automatic lock.

## Backup, recovery, and connections

- Backup health, last success/error, next eligible run, destination checks, verification, and retry remain visible in one recovery center.
- Everyday encrypted backups, emergency recovery kits, and short-lived plaintext migration exports are explained as distinct artifacts.
- External password services remain optional and disabled by default. Configuration is shown only for the service selected by the user.
- Imports remain local until the user explicitly previews and confirms a later synchronization.

## Browser extension delivery

- Releases contain `Vault-Unified-Browser-Extension-v1.3.0.zip` as a deterministic, allowlisted asset alongside EXE, MSI, and the release manifest.
- Desktop and extension versions share one checked contract.
- Pairing uses a short-lived code and session-only browser storage; lock, exit, expiry, cancellation, and re-pairing revoke the old token.
- Filling requires a user action and refuses ambiguous multi-form, change-password, iframe, and Shadow DOM cases instead of claiming success.
- Extension permissions are unchanged. v1.3.0 distributes an unpacked Chrome/Edge ZIP; it is not a Chrome Web Store release.

## Verification and governance

- Playwright covers generated-data first use, editing/cancellation, import/undo, item-level sync, backup/restore, connections, conflicts, and browser pairing across keyboard, language, scaling, narrow-window, forced-color, reduced-motion, timeout, disconnection, and stale-state cases.
- CI runs Python tests and dependency audit, TypeScript/Vite checks, renderer journeys with axe, Rust tests, RustSec, repository secret scanning, and release-only packaged validation.
- Failure screenshots and traces are eligible for upload only after generated-secret marker scanning.
- The repository now includes MIT licensing, security and contribution policies, a code of conduct, issue forms, privacy boundaries, and explicit release/usability gates.

Automated checks do not prove that a real novice can use the product. Publication remains blocked until the repository owner reviews sanitized results from actual novice sessions.

## Install and upgrade

1. Before upgrading, create and verify an encrypted backup in the current version.
2. Download the v1.3.0 EXE or MSI only from this repository's GitHub Release.
3. Verify the asset name, byte size, and SHA-256 against `release-manifest-v1.3.0.json`.
4. Install the desktop application. Existing vaults are opened in place without an implicit format migration.
5. Unlock, confirm the expected entries, create a fresh backup, and verify it before removing the previous installer.

The browser extension is a separate ZIP. Download it from the same release, extract it, load the directory through Chrome/Edge developer mode, and pair it from the desktop Connections page.

## Compatibility and rollback

- v1.3.0 does not add a password source, item type, mobile protocol, LAN API, collaboration feature, telemetry SDK, extension permission, or implicit vault migration.
- Data-format additions made during this cycle are optional, namespaced, defaulted, and backward-compatible. Existing v1/v2/v3 vault content must not be silently discarded.
- To roll back the application, first preserve the current encrypted vault and a verified backup. Uninstall v1.3.0, install the retained v1.2.0 installer, and restore only from a backup known to be compatible. Never overwrite the only current vault during rollback.

## Known boundaries

- Windows is the supported desktop platform.
- External-service workflows still depend on the selected provider, its local command-line client, and any provider account requirements.
- The unpacked browser extension requires developer mode and deliberately refuses page structures it cannot fill safely.
- Real novice usability results and owner sign-off are release gates, not claims supplied by automation.
