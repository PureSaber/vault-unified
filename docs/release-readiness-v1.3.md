# v1.3.0 release readiness

Status: **published; evidence reconciled; outstanding approval and coverage gaps remain**. v1.3.0 was published on **2026-09-12 at 13:01:10 UTC**. This retrospective checklist, updated on 2026-09-14, records observed results; it does not retroactively authorize the release or assert that every original gate was met. Details and hashes are in the [v1.3.0 publication record](release-record-v1.3.0.md).

Checked items below mean that the stated, bounded check has evidence. Unchecked items are not confirmed by the reviewed evidence; they are not automatically product failures. Later documentation commits do not change the published source, tag or assets.

## Published release identity

- Built source commit: [`76c610a88409e8845eda5c613112c2dcea09e2a0`](https://github.com/PureSaber/vault-unified/commit/76c610a88409e8845eda5c613112c2dcea09e2a0).
- Version-contract output: `1.3.0`, recorded in CI #134's release validation step at `2026-09-12T13:00:14Z`.
- Build run: [CI #134](https://github.com/PureSaber/vault-unified/actions/runs/34694677987), run `34694677987`, attempt 1, `success`.
- Published tag: `v1.3.0`; annotated object `071e54e3dccea272b1231cff5f0a3c6bf220fee3` resolves to the built source above.
- Release manifest SHA-256, **as reported by the Release API**: `f44b7326bcc8654794a6861679fd43d05c915e8bbe338c37f1f58f45d4d79f77` (1,337 bytes). The manifest does not hash itself.
- Pre-publication P0/P1 data-integrity review: **not recorded**; no historical review timestamp is inferred.

## Automated quality gates

All command results below refer to the built source above and CI #134, not a new test run for this documentation update. Exact job links and execution scope are in the [CI results table](release-record-v1.3.0.md#ci-134-results).

- [x] Python full suite: `.\.venv\Scripts\pytest -q` — [python job](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004556), `success`.
- [x] Python dependency audit: `.\.venv\Scripts\python -m pip_audit --local --skip-editable --progress-spinner off` — same python job, `success`.
- [x] TypeScript typecheck: `npm run lint` in `apps/desktop` — [desktop job](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004590), grouped step `success`.
- [x] Vite production build: `npm run build` in `apps/desktop` — same desktop job, grouped step `success`.
- [x] Playwright generated-data renderer journey command: `npm run test:ui` in `apps/desktop` — [ui-journey job](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004582), command and enforcement steps `success`.
- [ ] Separately recorded axe result confirms no critical or serious violations — the UI job succeeded, but a separate findings summary was not extracted into this record.
- [x] Rust unit tests: `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --lib` — desktop job, `success`.
- [x] RustSec automated audit of `apps/desktop/src-tauri/Cargo.lock` — [rustsec job](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004485), `success`.
- [ ] Reviewer confirmation of the RustSec risk register — not inferred from automated audit success.
- [x] Repository secret scan: `.\.venv\Scripts\python scripts\scan_repository_secrets.py --repo-root .` — python job, `success`.
- [x] Generated-data renderer journey and artifact-scanning command completed successfully — ui-journey job. Failure-artifact upload was `skipped`, not a separate scan of uploaded failure files.

## Packaged Windows gates

These are real packaged-lifecycle requirements; renderer-only Playwright results cannot satisfy them. [Release job `103556441042`](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556441042) ran:

```powershell
pwsh -NoProfile -File scripts/validate-desktop-release.ps1
```

The command ran **without** `-SkipInstallerLifecycle` and completed successfully. The printed manifest records both installer lifecycle results as `passed`, not `not-run-user-deferred`.

- [x] Packaged sidecar generated-data smoke passes — manifest `packaged_sidecar_generated_data_smoke=passed`.
- [x] Backup cleanup preview/confirmation smoke passes — manifest `backup_cleanup_preview_confirmed=passed`.
- [x] NSIS install / process-alive launch / stop / uninstall / cleanup smoke passes — manifest `nsis_install_launch_uninstall=passed`.
- [x] MSI install / process-alive launch / stop / uninstall / cleanup smoke passes — manifest `msi_install_launch_uninstall=passed`.
- [ ] Full NSIS install / launch / **create-use-lock** / stop / uninstall journey — create-use-lock in the installed renderer is not performed by this validator.
- [ ] Full MSI install / launch / **create-use-lock** / stop / uninstall journey — same coverage gap.
- [ ] Failed restore leaves the active encrypted vault bytes unchanged **in the packaged application** — not established by this validator.
- [x] Browser-extension ZIP structure, permission and version contract pass — manifest `browser_extension_structure_permissions_and_version=passed`.
- [ ] Browser pairing, fill safety and lock/revocation checks **against the packaged application** — not established by ZIP validation or a renderer-only journey.

The separate sidecar smoke must not be substituted for the installed-renderer create-use-lock journey. See [exact packaged coverage](release-record-v1.3.0.md#what-the-packaged-validation-actually-covered).

For future candidates only, an owner-deferred, non-installing preflight may use `-SkipInstallerLifecycle`. Such a run records `not-run-user-deferred` and cannot satisfy either installer lifecycle gate. That was **not** the mode used by CI #134.

## Artifact and publication gates

The four published assets are `Vault.Unified_1.3.0_x64-setup.exe`, `Vault.Unified_1.3.0_x64_en-US.msi`, `Vault-Unified-Browser-Extension-v1.3.0.zip`, and `release-manifest-v1.3.0.json`. Exact byte sizes, hashes, asset IDs, build-to-download filename mapping and unsigned-installer status are in the [asset table](release-record-v1.3.0.md#published-assets).

### Build and publication evidence

- [x] All component versions equal `1.3.0` — version-contract output from the release validator.
- [x] The published tag is exactly `v1.3.0` and resolves to the built source.
- [x] Release notes exist at [docs/release-v1.3.0.md](release-v1.3.0.md).
- [x] The published manifest records source commit, tag, filenames, byte sizes and SHA-256 values for the three payloads.
- [ ] Every asset record has an explicit kind — schema 1 includes `kind` only for the extension, not the two installers; the published JSON is left unchanged.
- [x] Published extension ZIP passes the allowlisted structure/permission/version validator in the release step and again after download.
- [ ] A separately recorded byte-for-byte deterministic rebuild comparison — not claimed from the structure validator alone.
- [x] EXE, MSI and extension ZIP sizes and SHA-256 values match the downloaded manifest — CI #134's post-publication verification step.
- [ ] Independent download/hash verification of the manifest itself against its API-reported digest — not performed by that step, because the manifest does not list itself.
- [ ] Pre-publication review confirmed no open P0/P1 data-loss, cancellation-write, partial-success, stale-preview, restore-corruption or secret-exposure issue — historical review evidence is not recorded.

### After publication

- [x] Download all four assets into a fresh directory through the release endpoint — CI #134, `Re-download and verify published assets`, `success`.
- [x] Recompute the three listed payloads' byte sizes and SHA-256 values against the downloaded manifest — same step, `success`.
- [x] Re-run extension ZIP structure/version/permission validation — same step, verified at `2026-09-12T13:01:20Z`.
- [x] Resolve the published tag through its annotated-tag layer and confirm it identifies the built source commit — same step; tag objects also inspected for this record.

**Preservation rule:** do not replace a published asset or move `v1.3.0`; fix binary defects in a new version. This documentation-only correction changes neither the original manifest nor any other published asset. GitHub reports `immutable=false`, so this is a repository rule, not a claim of platform-enforced immutability.

## Human novice usability gate

Attach or link a sanitized copy of [usability-test-results-template.md](usability-test-results-template.md) completed from real novice sessions. Automated journeys, screenshots, axe and an expert walkthrough do not satisfy this gate.

- Real novice results: **not recorded in this checklist**.
- Owner decision and unresolved limitations: **not recorded**; only the repository owner can supply the review decision. The published tag is not a substitute for this evidence.

Codex and CI must leave this line unchecked:

- [ ] Repository owner reviewed real novice usability results

## Release authorization and correction boundary

v1.3.0 already exists as a published release. Recording that fact is not a waiver of its unconfirmed gates, a new approval, or an instruction to recreate the tag. The historical documents at the tag remain unchanged; the documentation correction records actual results and outstanding evidence separately.

Before any **future** formal tag is created, every applicable automated, packaged, artifact, issue and human gate must be checked by the responsible reviewer. A failed gate returns work to a small corrective PR and a new candidate build. Missing evidence must be obtained or explicitly handled by the responsible reviewer, not silently marked passed by automation.
