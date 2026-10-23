# RustSec risk register

Owner: security and release owner. Reviewed 2026-10-23 for the Windows
`x86_64-pc-windows-msvc` target.

CI runs `cargo-audit` against the proposed `Cargo.lock` with the current RustSec
database and without advisory suppression. A vulnerability fails the job. The
review records remaining informational findings; it is not an ignore list.

## Current evidence

On 2026-10-23 the CI `rustsec` command was run locally, because hosted Actions
minutes were unavailable: the pinned `cargo-audit 0.22.2` Windows archive
(SHA-256 `0a7316540862c13d954f648917ceacca593747baed6eec180fafa590be2710ab`
verified), the same `audit --url https://github.com/RustSec/advisory-db.git
--file apps/desktop/src-tauri/Cargo.lock` invocation, advisory database commit
`640bf5a9f06e66d8721e8772766531fe77c8630d` (1,349 advisories). Result: **0
vulnerabilities and 5 informational warnings**. The pull request that changed
this file records the exact commit audited. The actual audit remains a required
check for subsequent commits.

Each informational finding was checked with
`cargo tree --offline --locked --target x86_64-pc-windows-msvc --invert <package>`;
none appears in the Windows target graph.

| Advisory | Package | Kind | Windows reachability | Disposition |
|---|---|---|---|---|
| [RUSTSEC-2024-0370](https://rustsec.org/advisories/RUSTSEC-2024-0370.html) | `proc-macro-error 1.0.4` | unmaintained | Absent; GTK3 build macros on Linux | Track upstream replacement; review by 2026-11-20 |
| [RUSTSEC-2024-0429](https://rustsec.org/advisories/RUSTSEC-2024-0429.html) | `glib 0.18.5` | unsound iterator implementation | Absent; Linux GTK3 stack | Track compatible upstream fix; review by 2026-11-20 |
| [RUSTSEC-2026-0370](https://rustsec.org/advisories/RUSTSEC-2026-0370.html) | `zvariant 5.15.0` | unmaintained | Absent; Linux D-Bus path of `tauri-plugin-single-instance` via `zbus 5.19.0` | Track upstream replacement; review by 2026-11-20 |
| [RUSTSEC-2026-0371](https://rustsec.org/advisories/RUSTSEC-2026-0371.html) | `zbus_names 4.3.4` | unmaintained | Absent; same `zbus` path | Track upstream replacement; review by 2026-11-20 |
| [RUSTSEC-2026-0372](https://rustsec.org/advisories/RUSTSEC-2026-0372.html) | `zvariant_derive 5.15.0` | unmaintained | Absent; same `zbus` path | Track upstream replacement; review by 2026-11-20 |

## Resolved on 2026-10-23

The advisory database update of 2026-10-22 reported five vulnerabilities in the
unchanged v1.4.0 lockfile. None was suppressed.

| Advisory | Package | Resolution |
|---|---|---|
| [RUSTSEC-2026-0382](https://rustsec.org/advisories/RUSTSEC-2026-0382.html) | `rustls-webpki 0.103.15` | Updated to the patched `0.103.16` (reached on Windows through `reqwest` for update checks) |
| [RUSTSEC-2026-0383](https://rustsec.org/advisories/RUSTSEC-2026-0383.html) | `webpki-root-certs 1.0.9` | Updated to the patched `1.0.10` |
| [RUSTSEC-2026-0367](https://rustsec.org/advisories/RUSTSEC-2026-0367.html), [RUSTSEC-2026-0368](https://rustsec.org/advisories/RUSTSEC-2026-0368.html), [RUSTSEC-2026-0369](https://rustsec.org/advisories/RUSTSEC-2026-0369.html) | `zip 4.6.1` | Removed. Every published `tauri-plugin-updater` release, including 2.14.0 and 3.0.0-alpha.3, still requires `zip ^4`, so no compatible upgrade exists. `zip` is the plugin's optional default `zip` feature and is used only to extract `.msi.zip`/`-setup.exe.zip` updater bundles on Windows. Vault Unified publishes plain NSIS/MSI updater artifacts (`createUpdaterArtifacts: true`) and `allowed_asset` in `apps/desktop/src-tauri/src/updates.rs` already rejects any asset that is not `-setup.exe` or `.msi`, so the extraction path was unreachable. The dependency now sets `default-features = false` with the remaining defaults `rustls-tls` and `system-proxy`. Signature verification (`requireSignedVersion`, pinned `pubkey`) runs in `download()` before installation and is unaffected |

The lockfile is versioned in Git and audited directly. A manually duplicated
lockfile hash in this document is no longer a gate. The download integrity check
for the audit executable stays in CI.

## Review triggers

Review these entries when the deadline arrives, when a finding becomes a
vulnerability or receives a compatible fix, when Windows reachability changes,
or when Linux delivery is added. Do not force a newer glib across incompatible
GTK3 dependencies. Update the relevant dependency normally, inspect the resolved
diff and run the audit and affected runtime checks. If updater ZIP bundles are
ever reintroduced, `tauri-plugin-updater` must first support a patched `zip`.
