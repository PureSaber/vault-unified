# RustSec risk register

Owner: security and release owner

Baseline date: 2026-08-20 UTC

Windows release target: `x86_64-pc-windows-msvc`

This register records informational RustSec findings that cannot currently be removed by a safe, targeted dependency update. It is not an ignore list: CI runs `cargo-audit` without `--ignore`, so every warning remains visible and any vulnerability still fails the job.

## Audit evidence

- Tool: RustSec `cargo-audit 0.22.2`; official Windows archive SHA-256 `0a7316540862c13d954f648917ceacca593747baed6eec180fafa590be2710ab`.
- Advisory database: `RustSec/advisory-db` commit `2f08fbb85332687b721f2f22706d07448369451b` (commit time `2026-08-18T10:23:07+02:00`), 1,217 advisories.
- Lockfile: `apps/desktop/src-tauri/Cargo.lock`, SHA-256 `158e0b495da52a95dc21986537b5eeb15ae0088ce4bb3f85721ae2bab3cddc94`,
  441 packages. The v1.0.5 release preparation changed only the root package version; the
  advisory set and dependency graph were re-audited unchanged.
- Unfiltered result: **0 vulnerabilities; 17 allowed informational warnings** (16 unmaintained, 1 unsound).
- `--target-os windows --target-arch x86_64` result: also 0 vulnerabilities and 17 warnings. Advisory target filters do not prove dependency reachability when an advisory has no OS/architecture restriction.
- Reachability was therefore determined with `cargo tree --locked --target x86_64-pc-windows-msvc --invert <package>`. A second `--target all` tree established why non-Windows packages remain in the universal lockfile.

Representative commands:

```powershell
cargo-audit.exe audit --db .codex-tmp\rustsec-advisory-db --file apps\desktop\src-tauri\Cargo.lock --no-fetch --stale --json
cargo-audit.exe audit --db .codex-tmp\rustsec-advisory-db --file apps\desktop\src-tauri\Cargo.lock --no-fetch --stale --target-os windows --target-arch x86_64 --json
cargo tree --offline --manifest-path apps\desktop\src-tauri\Cargo.toml --locked --target x86_64-pc-windows-msvc --invert gtk@0.18.2
```

## Findings

“Windows” means present in Cargo's resolved Windows target graph, not merely present in `Cargo.lock`.

| Advisory | Package | Kind | Dependency path | Windows | Disposition / review deadline |
| --- | --- | --- | --- | --- | --- |
| [RUSTSEC-2024-0413](https://rustsec.org/advisories/RUSTSEC-2024-0413.html) | `atk 0.18.2` | unmaintained | root → Tauri GTK3 stack → `gtk` → `atk` | No | Track GTK3 removal; review by 2026-11-20 |
| [RUSTSEC-2024-0416](https://rustsec.org/advisories/RUSTSEC-2024-0416.html) | `atk-sys 0.18.2` | unmaintained | root → Tauri GTK3 stack → `gtk` → `atk`/`gtk-sys` → `atk-sys` | No | Track GTK3 removal; review by 2026-11-20 |
| [RUSTSEC-2024-0412](https://rustsec.org/advisories/RUSTSEC-2024-0412.html) | `gdk 0.18.2` | unmaintained | root → Tauri `gtk`/`webkit2gtk`/`wry` → `gdk` | No | Track GTK3 removal; review by 2026-11-20 |
| [RUSTSEC-2024-0418](https://rustsec.org/advisories/RUSTSEC-2024-0418.html) | `gdk-sys 0.18.2` | unmaintained | root → Tauri GTK3 stack → `gdk` → `gdk-sys` | No | Track GTK3 removal; review by 2026-11-20 |
| [RUSTSEC-2024-0411](https://rustsec.org/advisories/RUSTSEC-2024-0411.html) | `gdkwayland-sys 0.18.2` | unmaintained | root → `tauri-runtime-wry` → `wry` → `gdkwayland-sys` | No | Linux/Wayland only; review by 2026-11-20 |
| [RUSTSEC-2024-0417](https://rustsec.org/advisories/RUSTSEC-2024-0417.html) | `gdkx11 0.18.2` | unmaintained | root → `tauri-runtime-wry` → `wry` → `gdkx11` | No | Linux/X11 only; review by 2026-11-20 |
| [RUSTSEC-2024-0414](https://rustsec.org/advisories/RUSTSEC-2024-0414.html) | `gdkx11-sys 0.18.2` | unmaintained | root → `tauri-runtime-wry` → `wry` → `gdkx11` → `gdkx11-sys` | No | Linux/X11 only; review by 2026-11-20 |
| [RUSTSEC-2024-0415](https://rustsec.org/advisories/RUSTSEC-2024-0415.html) | `gtk 0.18.2` | unmaintained | root → Tauri/`muda`/`tao`/`webkit2gtk`/`wry` → `gtk` | No | Track GTK3 removal; review by 2026-11-20 |
| [RUSTSEC-2024-0420](https://rustsec.org/advisories/RUSTSEC-2024-0420.html) | `gtk-sys 0.18.2` | unmaintained | root → Tauri GTK3 stack → `gtk` → `gtk-sys` | No | Track GTK3 removal; review by 2026-11-20 |
| [RUSTSEC-2024-0419](https://rustsec.org/advisories/RUSTSEC-2024-0419.html) | `gtk3-macros 0.18.2` | unmaintained | root → Tauri GTK3 stack → `gtk` → `gtk3-macros` | No | Build macro on GTK3 path; review by 2026-11-20 |
| [RUSTSEC-2024-0429](https://rustsec.org/advisories/RUSTSEC-2024-0429.html) | `glib 0.18.5` | unsound | root → Tauri GTK3 stack → `gtk`/`gdk`/`gio` → `glib` | No | Patched only in `glib >=0.20`; do not force across GTK3 constraints; review by 2026-11-20 |
| [RUSTSEC-2024-0370](https://rustsec.org/advisories/RUSTSEC-2024-0370.html) | `proc-macro-error 1.0.4` | unmaintained | root → GTK3 `glib-macros`/`gtk3-macros` → `proc-macro-error` | No | Build-only on absent Windows GTK3 path; review by 2026-11-20 |
| [RUSTSEC-2025-0081](https://rustsec.org/advisories/RUSTSEC-2025-0081.html) | `unic-char-property 0.9.0` | unmaintained | root → `tauri-utils` → `urlpattern 0.3.0` → `unic-ucd-ident` → `unic-char-property` | **Yes** | Temporary acceptance; review by 2026-10-20 |
| [RUSTSEC-2025-0075](https://rustsec.org/advisories/RUSTSEC-2025-0075.html) | `unic-char-range 0.9.0` | unmaintained | root → `tauri-utils` → `urlpattern` → `unic-ucd-ident` → `unic-char-range` (also via `unic-char-property`) | **Yes** | Temporary acceptance; review by 2026-10-20 |
| [RUSTSEC-2025-0080](https://rustsec.org/advisories/RUSTSEC-2025-0080.html) | `unic-common 0.9.0` | unmaintained | root → `tauri-utils` → `urlpattern` → `unic-ucd-ident` → `unic-ucd-version` → `unic-common` | **Yes** | Temporary acceptance; review by 2026-10-20 |
| [RUSTSEC-2025-0100](https://rustsec.org/advisories/RUSTSEC-2025-0100.html) | `unic-ucd-ident 0.9.0` | unmaintained | root → `tauri`/`tauri-runtime(-wry)` → `tauri-utils 2.9.3` → `urlpattern 0.3.0` → `unic-ucd-ident` | **Yes** | Temporary acceptance; review by 2026-10-20 |
| [RUSTSEC-2025-0098](https://rustsec.org/advisories/RUSTSEC-2025-0098.html) | `unic-ucd-version 0.9.0` | unmaintained | root → `tauri-utils` → `urlpattern` → `unic-ucd-ident` → `unic-ucd-version` | **Yes** | Temporary acceptance; review by 2026-10-20 |

## Why no dependency update is included

- `tauri 2.11.5` and `tauri-utils 2.9.3` are the current crates.io releases. The [Tauri 2.11.5 release audit](https://github.com/tauri-apps/tauri/releases/tag/tauri-v2.11.5) reports the same GTK3 and `unic-*` families upstream.
- Published `tauri-utils 2.9.3` requires `urlpattern = "0.3"`; `urlpattern 0.3.0` is the only compatible locked line and brings the five `unic-*` packages.
- Tauri's development branch at commit [`52e4b6e`](https://github.com/tauri-apps/tauri/blob/52e4b6e71d8632a7e648f866c442e287ecddee34/crates/tauri-utils/Cargo.toml) has moved to `urlpattern = "0.6"`, whose published crate uses `icu_properties` instead of `unic-*`. Consuming an unreleased git snapshot would broaden the change and reduce release provenance, so this repository will wait for a stable Tauri release.
- The GTK3/glib/proc-macro packages are absent from the Windows graph. Forcing `glib >=0.20`, patching transitive manifests, or replacing Tauri's Linux backend is not a safe maintenance update for a Windows release.

No `cargo update` was run against the project lockfile, and no RustSec advisory is suppressed.

## Early review triggers

Review the relevant entries before their deadline if any of these occurs:

- a stable Tauri/tauri-utils release adopts `urlpattern 0.6` or otherwise removes a listed package;
- a warning becomes a vulnerability, gains severity/affected-platform metadata, or receives a patched version compatible with the current graph;
- the repository adds Linux packaging, changes the Windows target, enables new Tauri features, or directly uses URL-pattern parsing with untrusted input;
- `cargo tree` changes the reachability classification or `cargo audit` reports a new advisory.

At review, use a narrowly scoped `cargo update -p <package> --precise <version>` only when the parent constraints permit it, inspect the exact lockfile diff, and rerun Windows target tree, Rust tests/checks, Python/frontend regression, installer CI, and the unfiltered audit.
