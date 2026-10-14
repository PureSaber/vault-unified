# RustSec risk register

Owner: security and release owner. Reviewed 2026-10-14 for the Windows
`x86_64-pc-windows-msvc` target.

CI runs `cargo-audit` against the proposed `Cargo.lock` with the current RustSec
database and without advisory suppression. A vulnerability fails the job. The
review records remaining informational findings; it is not an ignore list.

## Current evidence

[CI run 38512446681](https://github.com/PureSaber/vault-unified/actions/runs/38512446681/job/115683782439)
audited commit `a85d1eb3d9d8f0a5857f8ecb6ff4d9149e387a7d` with the pinned,
download-verified `cargo-audit 0.22.2`: **0 vulnerabilities and 2 informational
warnings**. The actual audit remains a required check for subsequent commits.

The global-shortcut plugin requires Tauri 2.12. The resolved update uses
`tauri 2.12.3`, `tauri-utils 2.10.1` and `urlpattern 0.6.0`; the previous five
`unic-*` dependencies are gone. The current advisory database no longer reports
the previous GTK3 unmaintained notices. The two findings below remain on the
Linux GTK3 dependency path. Neither appears in the Windows target graph, checked
with `cargo tree --offline --locked --target x86_64-pc-windows-msvc --invert` for
each package.

| Advisory | Package | Kind | Windows reachability | Disposition |
|---|---|---|---|---|
| [RUSTSEC-2024-0370](https://rustsec.org/advisories/RUSTSEC-2024-0370.html) | `proc-macro-error 1.0.4` | unmaintained | Absent; GTK3 build macros on Linux | Track upstream replacement; review by 2026-11-20 |
| [RUSTSEC-2024-0429](https://rustsec.org/advisories/RUSTSEC-2024-0429.html) | `glib 0.18.5` | unsound iterator implementation | Absent; Linux GTK3 stack | Track compatible upstream fix; review by 2026-11-20 |

The lockfile is versioned in Git and audited directly. A manually duplicated
lockfile hash in this document is no longer a gate. The download integrity check
for the audit executable stays in CI.

## Review triggers

Review these entries when the deadline arrives, when a finding becomes a
vulnerability or receives a compatible fix, when Windows reachability changes,
or when Linux delivery is added. Do not force a newer glib across incompatible
GTK3 dependencies. Update the relevant dependency normally, inspect the resolved
diff and run the audit and affected runtime checks.
