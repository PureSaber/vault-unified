# UI/UX refresh

Baseline: `a2aa07a`; branch: `codex/uiux-refresh`.
The GitHub `main` reference was checked again on 2026-10-22 and still matches
this baseline. The refresh is delivered separately for review.

The owner authorized autonomous design, implementation and verification on
2026-10-21. The review source is `vault-unified-uiux-handoff.html` (2026-10-21).
Use the Windows-inspired list/detail direction, preserving text navigation at
the default 1000 × 700 window size. Validate the actual renderer as the visual
prototype with generated data before completing the rollout.

## Data boundary

- Do not open, inspect, migrate, overwrite or use the owner's real vault,
  credentials, exported accounts, browser profiles or signing keys.
- Keep the current encryption, data format, authentication, transactional editing,
  reveal expiry, auto-lock, preview/confirmation and recovery behavior.
- Use the existing generated-data renderer/API harness and isolated directories.
- Do not run the normal desktop launcher or install an unverified development
  build over the user's daily application.
- Reading a detail view must not perform a write. Cancelled edits must leave the
  stored entry unchanged. Verify these properties with existing and new journeys.

## Implementation sequence

1. Correct backup/sync status, localization, error lifetime and accessibility.
2. Establish shared visual tokens, responsive navigation and theme preferences.
3. Deliver read-only item details, efficient copy/TOTP and explicit editing;
   refine unlock and browser popup using rendered screenshots.
4. Organize security, connection, import, sharing and settings workflows.
5. Run relevant journeys, complete the full required checks, review diffs and
   prepare a reviewable delivery with evidence.

## Resolved design choices

- Backup configuration and successful recoverable backup are separate states;
  local atomic-recovery copies do not satisfy the backup reminder.
- Preserve Tab/Shift+Tab focus navigation; use visible actions for menus.
- Keep browser import visible during onboarding and on the password page.
- Keep confirmation for archive, trash, import and other consequential actions.
- Preserve existing master-password requirements and remembered-password behavior;
  do not change account access policy as part of a visual refresh.
- Use the existing Chinese term “保险库” consistently for vault; distinguish
  account, password, recovery code and passkey according to their actual roles.
- Small-window layouts adapt to content; do not blindly copy platform breakpoints.
- Native Hello, signing and release changes are not necessary for UI work; retain
  their existing behavior and test contracts.

## Evidence

Implemented renderer scope:

- Text sidebar; list/detail workspace with independent scrolling at desktop sizes;
  explicit editing, preserved list context, and narrow-window navigation.
- Shared color/spacing/type tokens, original outline SVGs, light/dark/system themes;
  matching neutral extension popup surfaces without permission changes.
- Read-only fields, masked secrets and recovery codes, direct timed TOTP viewing,
  copy feedback using the service lifetime, and share initiation from the selected item.
- First-run language selection and primary form before support actions; document
  language, localized authentication/maintenance messages, persistent dismissible errors.
- Correct independent-backup reminders and configured-service sync badges; section
  navigation for security/recovery; a cancellable lock-before-recovery handoff.
- Browser integration first in Connections; structured sharing review; three truthful
  import steps and 100-record preview pages preserving every submitted resolution.
- Existing editor transaction, preview, restore and cancellation assertions retained;
  editor journeys now explicitly select Edit from the read-only view.

Verified locally on 2026-10-21/22:

- `pytest -q`: **592 passed**; generated fixtures only.
- `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --lib --test updater_transport`:
  **10 passed**, including signed-update rejection cases.
- TypeScript lint and production Vite build passed.
- Focused renderer verification: **21 passed** on the final source, including
  an encrypted-file SHA-256 comparison proving that viewing, revealing and
  cancelling edits did not change its bytes; 101-record import pagination keeps
  decisions across pages, and a delayed sharing response cannot erase typed input.
- Delayed secret responses are discarded on blur; switching, locking, theme changes,
  persistent errors, Chinese/English and 1000 × 700 / 640-wide layouts are covered.
- Final full renderer run: **100 passed in 7.5 minutes**, including the original
  save/cancel, import/undo, sync, recovery, extension and accessibility journeys.
- Repository secret scan passed. The post-test artifact scan initially failed
  because an extra scan attempted an unsupported documentation directory and
  consumed the temporary marker file. The exact markers were recovered from
  that run's generated Vite build; the existing scanner then passed against its
  approved test/report directories with **zero unsafe files**. The six retained
  screenshots have identical SHA-256 hashes to those scanned originals and were
  visually checked for masked secrets.
- Python dependency audit passed after refreshing the local development environment's
  certifi and Pillow packages; no product dependency manifest changed.

### Rendered review images

All retained images use generated accounts with masked secrets at 1000 × 700.

| View | Light | Dark |
| --- | --- | --- |
| Chinese account details | [Preview](uiux-refresh/accounts-zh-light.png) | [Preview](uiux-refresh/accounts-zh-dark.png) |
| English account details | [Preview](uiux-refresh/accounts-en-light.png) | [Preview](uiux-refresh/accounts-en-dark.png) |
| First-run onboarding | [Chinese](uiux-refresh/onboarding-zh-light.png) | [English](uiux-refresh/onboarding-en-dark.png) |

## Release blocker found during verification

The unchanged baseline `apps/desktop/src-tauri/Cargo.lock` fails the current RustSec
vulnerability audit. The database was cloned freshly from the official RustSec repository
and read with the SHA-256-verified `cargo-audit` 0.22.2 binary used by CI:

- `rustls-webpki` 0.103.15: RUSTSEC-2026-0382 (patched in 0.103.16).
- `webpki-root-certs` 1.0.9: RUSTSEC-2026-0383 (patched in 1.0.10).
- `zip` 4.6.1: RUSTSEC-2026-0367, -0368 and -0369 (audit requires 9.0.0).
  It is brought in by `tauri-plugin-updater` 2.13.3 on Windows. The current stable
  2.14.0 updater also declares `zip ^4`, so a routine stable updater bump does not
  clear this gate. No advisory has been ignored and no dependency override introduced.

This is a draft for review, not an installer release. Resolve the native dependency
baseline and rerun the packaged Windows checks before release. This work has not
installed over the daily application or accessed an existing user vault.

## Handoff proposals reserved for subsequent slices

The HTML is a design backlog, not a claim that every one of its 25 proposals is in
this diff. Full extraction of legacy inline strings, Hello onboarding, a combined
pairing-code format, security/sharing subpage separation, a new settings-save model,
and a live clipboard countdown are still separate work. Existing preview/confirmation
rules remain instead of adopting a destructive-action Undo replacement.

## References and design decisions

- [1Password for Windows](https://support.1password.com/getting-started-windows/):
  list/detail mental model and common account actions.
- [Windows NavigationView](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/navigationview):
  labeled navigation adapted to our actual 1000-pixel window.
- [WAI-ARIA keyboard interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/):
  Tab and Shift+Tab remain focus navigation; action shortcuts do not replace them.
- [Proton Pass for Windows](https://proton.me/support/how-to-use-proton-pass-windows-app):
  clear separation between finding credentials and changing them.

## Rollback

Revert the UI commit and rebuild. There is no vault format migration or backend
transaction change. The previous renderer ignores the optional `vault_theme` preference.
The local daily application, vault files, signing keys, user extension archive and
extracted user extension directory were excluded from the change.
