# RustSec risk register

Owner: security and release owner. Reviewed 2026-10-23 for the Windows
`x86_64-pc-windows-msvc` target.

CI runs `cargo-audit` against the proposed `Cargo.lock` with the current RustSec
database and without advisory suppression. A vulnerability fails the job. The
review records remaining informational findings; it is not an ignore list.

## Current evidence

[CI run 39904514664](https://github.com/PureSaber/vault-unified/actions/runs/39904514664)
audited commit `d66e3923b53ed28ed70a283db1ffd82998b72d97` with the pinned,
download-verified `cargo-audit 0.22.2`: **0 vulnerabilities and 5 informational
warnings** (1,349 advisories loaded). The same run's `desktop` job built and
tested the Windows target with this dependency change. The identical command was
also run locally on 2026-10-23 against advisory database commit
`640bf5a9f06e66d8721e8772766531fe77c8630d` with the same result. The actual
audit remains a required check for subsequent commits.

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

Advisories dated 2026-10-09 to 2026-10-20 made the audit of the unchanged
v1.4.0 lockfile report five vulnerabilities (first seen in CI on 2026-10-22).
None was suppressed.

| Advisory | Package | Resolution |
|---|---|---|
| [RUSTSEC-2026-0382](https://rustsec.org/advisories/RUSTSEC-2026-0382.html) | `rustls-webpki 0.103.15` | Updated to the patched `0.103.16` (reached on Windows through `reqwest` for update checks) |
| [RUSTSEC-2026-0383](https://rustsec.org/advisories/RUSTSEC-2026-0383.html) | `webpki-root-certs 1.0.9` | Updated to the patched `1.0.10` |
| [RUSTSEC-2026-0367](https://rustsec.org/advisories/RUSTSEC-2026-0367.html), [RUSTSEC-2026-0368](https://rustsec.org/advisories/RUSTSEC-2026-0368.html), [RUSTSEC-2026-0369](https://rustsec.org/advisories/RUSTSEC-2026-0369.html) | `zip 4.6.1` | Removed. Every published `tauri-plugin-updater` release, including 2.14.0 and 3.0.0-alpha.3, still requires `zip ^4`, so no compatible upgrade exists. `zip` is the plugin's optional default `zip` feature (with `tar`/`flate2` for non-Windows bundles). On Windows it is used only when the *downloaded bytes* are a ZIP (`infer::archive::is_zip`), to extract `.msi.zip`/`-setup.exe.zip` updater bundles. Only bytes whose minisign signature verifies against the pinned `pubkey` reach `install()`, and the release pipeline (`scripts/build_release_assets.py`, `createUpdaterArtifacts: true`) signs and lists only plain `-setup.exe` and `.msi` files; `allowed_asset` in `apps/desktop/src-tauri/src/updates.rs` additionally rejects other URLs. The extraction path was therefore not reachable with a validly signed update, and it is now compiled out. The dependency sets `default-features = false` with the remaining defaults `rustls-tls` and `system-proxy`. Signature verification (`requireSignedVersion`, pinned `pubkey`) runs in `download()` independently of this feature |

The lockfile is versioned in Git and audited directly. A manually duplicated
lockfile hash in this document is no longer a gate. The download integrity check
for the audit executable stays in CI.

## Review triggers

Review these entries when the deadline arrives, when a finding becomes a
vulnerability or receives a compatible fix, when Windows reachability changes,
or when Linux delivery is added. Do not force a newer glib across incompatible
GTK3 dependencies. Update the relevant dependency normally, inspect the resolved
diff and run the audit and affected runtime checks. If ZIP or tar.gz updater
bundles are ever reintroduced, `tauri-plugin-updater` must first support a
patched `zip`.
