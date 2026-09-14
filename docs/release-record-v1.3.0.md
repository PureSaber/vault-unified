# v1.3.0 publication and validation record

Evidence reconciled on **2026-09-14** from GitHub release metadata, tag objects, CI #134 job results and release-job logs, and the validator at the published source. This is a retrospective record, not a new Windows test run, an independent download/hash run, or retroactive release approval. No raw credential-bearing logs are copied here.

**Status: published; automated results recorded; approval and coverage gaps remain.** See the [release checklist](release-readiness-v1.3.md) for outstanding requirements.

## Published identity

| Field | Recorded value |
| --- | --- |
| Release | [Vault Unified v1.3.0](https://github.com/PureSaber/vault-unified/releases/tag/v1.3.0), release ID `387572604`; `draft=false`, `prerelease=false` |
| Published at | `2026-09-12T13:01:10Z` |
| Built source commit | [`76c610a88409e8845eda5c613112c2dcea09e2a0`](https://github.com/PureSaber/vault-unified/commit/76c610a88409e8845eda5c613112c2dcea09e2a0) |
| Source change | Merge of PR #55, `test: reject incomplete installer cleanup`, committed `2026-09-12T09:45:58Z` |
| Annotated tag object | `071e54e3dccea272b1231cff5f0a3c6bf220fee3`, created `2026-09-12T12:48:18Z`, resolves to the built source above |
| Release workflow | [CI #134](https://github.com/PureSaber/vault-unified/actions/runs/34694677987), run ID `34694677987`, attempt 1, tag push, conclusion `success` |
| Workflow timestamps | Created `2026-09-12T12:48:23Z`; final update `2026-09-12T13:01:25Z` |
| Version-contract output | `1.3.0`, in the release validation step at `2026-09-12T13:00:14Z` |
| Manifest generation | `2026-09-12T13:01:02.7092580Z`; schema `1`; source and tag match the values above |

Identity sources: [tag ref](https://api.github.com/repos/PureSaber/vault-unified/git/ref/tags/v1.3.0), [annotated tag object](https://api.github.com/repos/PureSaber/vault-unified/git/tags/071e54e3dccea272b1231cff5f0a3c6bf220fee3), and [Release API](https://api.github.com/repos/PureSaber/vault-unified/releases/387572604). `target_commitish=main` is not used as a substitute for resolving the actual tag. Later documentation commits do not change the source of the published binaries.

## CI #134 results

All commands below refer to the published source, not the later documentation correction. A successful job is not a claim of broader coverage than its tests implement.

| Job | Command or step | Recorded result |
| --- | --- | --- |
| [python](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004556) | `.\.venv\Scripts\pytest -q` | `success` |
| [python](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004556) | `.\.venv\Scripts\python -m pip_audit --local --skip-editable --progress-spinner off` | `success` |
| [python](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004556) | `.\.venv\Scripts\python scripts\scan_repository_secrets.py --repo-root .` | `success` |
| [desktop](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004590) | `npm ci`, `npm run lint`, `npm run build` in `apps/desktop` | Grouped step `success` |
| [desktop](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004590) | `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --lib` | `success` |
| [desktop](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004590) | Parse `scripts/validate-desktop-release.ps1` with the PowerShell parser | `success` |
| [ui-journey](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004582) | `npm run test:ui` in `apps/desktop`; generated-data renderer journeys and artifact scanning | `success`; enforcement step `success`; failure-artifact upload `skipped` |
| [rustsec](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004485) | Pinned `cargo-audit` audit of `apps/desktop/src-tauri/Cargo.lock` against the RustSec advisory database | `success` |
| [release-desktop](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556441042) | `powershell -ExecutionPolicy Bypass -File scripts/build-desktop-release.ps1` | `success` |
| [release-desktop](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556441042) | `pwsh -NoProfile -File scripts/validate-desktop-release.ps1` | `success`; installer lifecycle was **not skipped** |
| [release-desktop](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556441042) | Upload Release Assets; Re-download and verify published assets | Both steps `success` |

The manifest's `passed-by-required-job` values for Python tests, desktop build, Rust tests and RustSec refer to required upstream jobs. They are not extra test executions inside the installer validator. No test count or separate axe finding count is inferred from a green job summary. The failure-artifact upload being skipped does not indicate a skipped test suite.

## What the packaged validation actually covered

Evidence: the [release-job log](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556441042) and [validator at the built source](https://github.com/PureSaber/vault-unified/blob/76c610a88409e8845eda5c613112c2dcea09e2a0/scripts/validate-desktop-release.ps1).

| Validation | Manifest result | Coverage boundary |
| --- | --- | --- |
| `packaged_sidecar_generated_data_smoke` | `passed` | Separate packaged API process: authenticated readiness, generated v3 vault and entry create/update/list, encrypted backup creation/verification, local-only defaults and rejection of direct sync without preview |
| `backup_cleanup_preview_confirmed` | `passed` | Reject unconfirmed cleanup; check preview/confirmation behavior using generated data |
| `nsis_install_launch_uninstall` | `passed` | Silent install, registered executable discovery, process-alive launch check, process-tree stop, uninstall, and no remaining install directory, uninstall registration or running installation process |
| `msi_install_launch_uninstall` | `passed` | Equivalent MSI installation/launch/stop/uninstall and cleanup checks |
| `browser_extension_structure_permissions_and_version` | `passed` | ZIP structure, permission and version contract, not a live browser filling session |

The log starts the sidecar smoke at `13:00:14Z`, NSIS at `13:00:23Z`, and MSI at `13:00:46Z`; all three timestamps are on 2026-09-12. The completed manifest is printed at `13:01:02Z`.

`Launch-And-StopInstalledApp` checks that the installed process survives an eight-second launch window, then stops it. It does not perform create-use-lock through the installed renderer. The separate sidecar smoke must not be counted as that installed-UI journey. This validator also does not establish packaged failed-restore byte preservation or a packaged browser pairing/fill/lock-revocation journey. Those original broader gates remain open unless separate evidence is attached.

## Published assets

The following are **GitHub-published filenames**, byte sizes and SHA-256 digests reported by the [Release API](https://api.github.com/repos/PureSaber/vault-unified/releases/387572604). The three payloads also match the manifest printed in the CI log. The manifest's own digest is supplied by release metadata, not by a self-hash inside the manifest.

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `Vault.Unified_1.3.0_x64-setup.exe` | 24,899,953 | `63bd2029792e07f5d314a84d80b06ac925dad5bbbe7f255a3623ee00b662947d` |
| `Vault.Unified_1.3.0_x64_en-US.msi` | 25,604,096 | `42ad04beb5098cfec1b4e77c70227c451f7284e4196a669c2d94bff958b20d12` |
| `Vault-Unified-Browser-Extension-v1.3.0.zip` | 11,971 | `cd9fbd9083059f05b2e2b83ae28897b582f80f996f8dc8ee165619c9136e0a3d` |
| `release-manifest-v1.3.0.json` | 1,337 | `f44b7326bcc8654794a6861679fd43d05c915e8bbe338c37f1f58f45d4d79f77` |

Asset IDs, respectively: `559276249`, `559276250`, `559276252`, `559276253`. Download them from the [v1.3.0 Release](https://github.com/PureSaber/vault-unified/releases/tag/v1.3.0), not from a later build of the source.

### Filename mapping, signing and manifest limitations

The published manifest retains `Vault Unified_1.3.0_x64-setup.exe` and `Vault Unified_1.3.0_x64_en-US.msi` as build filenames. GitHub exposes them as `Vault.Unified_...` and retains the spaced names in the asset labels. CI's download verifier explicitly allows this space-to-period filename mapping; the byte-size and SHA-256 checks remain exact.

Both installer records have `authenticode_status: NotSigned`. A passing smoke test or matching hash is not Authenticode publisher verification. Only the extension entry has an explicit `kind: browser_extension`; the two installer entries have no `kind` field. The incomplete asset-kind requirement is recorded as a gap, not silently rewritten into the already-published JSON.

The release API reports `immutable=false`. The requirement not to replace assets is a repository policy, not a claim that GitHub has enforced release immutability. This documentation correction does not replace or regenerate any of the four assets, edit the tag, or change the manifest bytes.

## Post-publication verification

CI #134's final release step downloaded all four assets into a fresh directory with `gh release download`. It checked the downloaded manifest's source commit and tag, recomputed sizes and SHA-256 values for its **three listed payloads**, validated the extension ZIP again, and peeled the annotated tag to confirm the built source. The step completed successfully; the extension verification is logged at `2026-09-12T13:01:20Z`.

The manifest does not list itself. That step did not independently hash the manifest against the Release API's own digest. The value above is recorded as API-reported; a separate manifest self-integrity download/hash check is not claimed. No new installer execution or independent binary re-download was performed when preparing this documentation correction.

## Outstanding approval and evidence

The checklist does not contain sanitized real-novice session results, an owner review decision, or a recorded pre-publication P0/P1 issue review. Do not infer those decisions from the tag author, a successful workflow, an empty current issue list, or the fact of publication. Retain the human gate unchecked and attach evidence only when the responsible reviewer provides it.

Also outstanding are the broader installed-UI and packaged journeys described above, a separately recorded axe result and risk-register review, explicit installer asset kinds, and independent verification of the manifest's own digest. These are evidence/coverage limitations, not a claim that every corresponding product behavior is broken. Future formal versions must satisfy the documented gates; this record does not waive them.
