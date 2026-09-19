# v1.3.0 release readiness

Status: **published; owner approval and release completion recorded**. v1.3.0 was published on **2026-09-12 at 13:01:10 UTC**. This retrospective checklist, reconciled on 2026-09-19, combines CI evidence with the existing owner decision and manual acceptance records in issue #30. It does not create a new approval or claim unperformed tests. Details and hashes are in the [v1.3.0 publication record](release-record-v1.3.0.md).

Checked items below mean that the stated, bounded check has evidence. Remaining unchecked items describe coverage or schema limitations; they do not reopen the owner's completed release decision. Later documentation commits do not change the published source, tag or assets.

## Published release identity

- Built source commit: [`76c610a88409e8845eda5c613112c2dcea09e2a0`](https://github.com/PureSaber/vault-unified/commit/76c610a88409e8845eda5c613112c2dcea09e2a0).
- Version-contract output: `1.3.0`, recorded in CI #134's release validation step at `2026-09-12T13:00:14Z`.
- Build run: [CI #134](https://github.com/PureSaber/vault-unified/actions/runs/34694677987), run `34694677987`, attempt 1, `success`.
- Published tag: `v1.3.0`; annotated object `071e54e3dccea272b1231cff5f0a3c6bf220fee3` resolves to the built source above.
- Release manifest SHA-256: `f44b7326bcc8654794a6861679fd43d05c915e8bbe338c37f1f58f45d4d79f77` (1,337 bytes), reported by the Release API and independently matched after downloading the manifest on 2026-09-19. The manifest does not hash itself.
- P0/P1 status: [final release evidence](https://github.com/PureSaber/vault-unified/issues/30#issuecomment-5646056634) records no open P0/P1 issue at closure. A separate pre-publication review timestamp is not reconstructed.

## Automated quality gates

All command results below refer to the built source above and CI #134, not a new test run for this documentation update. Exact job links and execution scope are in the [CI results table](release-record-v1.3.0.md#ci-134-results).

- [x] Python full suite: `.\.venv\Scripts\pytest -q` — [python job](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004556), `success`.
- [x] Python dependency audit: `.\.venv\Scripts\python -m pip_audit --local --skip-editable --progress-spinner off` — same python job, `success`.
- [x] TypeScript typecheck: `npm run lint` in `apps/desktop` — [desktop job](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004590), grouped step `success`.
- [x] Vite production build: `npm run build` in `apps/desktop` — same desktop job, grouped step `success`.
- [x] Playwright generated-data renderer journey command: `npm run test:ui` in `apps/desktop` — [ui-journey job](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004582), command and enforcement steps `success`.
- [x] Axe assertions in the generated-data renderer journeys passed — the successful UI suite includes rejection of serious/critical violations on its tested screens. This is not an accessibility audit of every screen or assistive technology.
- [x] Rust unit tests: `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --lib` — desktop job, `success`.
- [x] RustSec automated audit of `apps/desktop/src-tauri/Cargo.lock` — [rustsec job](https://github.com/PureSaber/vault-unified/actions/runs/34694677987/job/103556004485), `success`.
- RustSec informational findings and review conditions remain in the [risk register](rustsec-risk-register.md); audit success is not a claim that all upstream warnings disappeared.
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
- [x] NSIS installed-UI create/use/lock/reopen and close paths — [owner walkthrough](https://github.com/PureSaber/vault-unified/issues/30#issuecomment-5645806553), separate from automated smoke. Product behavior was exercised on `5e56948`; `76c610a` only tightens installer validation.
- [x] MSI-specific install, payload identity, launch/stop and clean uninstall — [manual installer acceptance](https://github.com/PureSaber/vault-unified/issues/30#issuecomment-5645771218). The owner explicitly chose not to repeat the common product journey under MSI; no independent MSI create/use/lock run is claimed.
- [ ] Failed restore leaves the active encrypted vault bytes unchanged **in the packaged application** — not established by this validator.
- [x] Browser-extension ZIP structure, permission and version contract pass — manifest `browser_extension_structure_permissions_and_version=passed`.
- [x] Packaged desktop/browser pairing, single-form fill, multi-form/change-password refusal and lock revocation — [owner walkthrough](https://github.com/PureSaber/vault-unified/issues/30#issuecomment-5645806553); issue #51 was closed after these manual checks. This does not establish compatibility with arbitrary websites.

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
- Deterministic extension packaging is covered by the existing packaging tests; this documentation correction does not rerun a binary rebuild comparison.
- [x] EXE, MSI and extension ZIP sizes and SHA-256 values match the downloaded manifest — CI #134's post-publication verification step.
- [x] Independent manifest download/hash verification against its API-reported digest — matched on 2026-09-19. The [2026-09-12 release record](https://github.com/PureSaber/vault-unified/issues/30#issuecomment-5646056634) also records a local verification of all four assets.
- [x] No open P0/P1 issue at release closure — recorded in that final issue comment. This is not an invented earlier review timestamp.

### After publication

- [x] Download all four assets into a fresh directory through the release endpoint — CI #134, `Re-download and verify published assets`, `success`.
- [x] Recompute the three listed payloads' byte sizes and SHA-256 values against the downloaded manifest — same step, `success`.
- [x] Re-run extension ZIP structure/version/permission validation — same step, verified at `2026-09-12T13:01:20Z`.
- [x] Resolve the published tag through its annotated-tag layer and confirm it identifies the built source commit — same step; tag objects also inspected for this record.

**Preservation rule:** do not replace a published asset or move `v1.3.0`; fix binary defects in a new version. This documentation-only correction changes neither the original manifest nor any other published asset. GitHub reports `immutable=false`, so this is a repository rule, not a claim of platform-enforced immutability.

## Human novice usability gate

Attach or link a sanitized copy of [usability-test-results-template.md](usability-test-results-template.md) completed from real novice sessions. Automated journeys, screenshots, axe and an expert walkthrough do not satisfy this gate.

- Owner decision: **2026-09-12 — reviewed and passed**, explicitly supplied by the repository owner before the tag was created; [recorded approval](https://github.com/PureSaber/vault-unified/issues/30#issuecomment-5645979059).
- Real novice results: the owner reported completion of the results review. Participant count, underlying session results, success percentages and SUS scores were not supplied to Codex and are not inferred here.
- The separate [guided owner walkthrough](https://github.com/PureSaber/vault-unified/issues/30#issuecomment-5645806553) is formative evidence, not an independent novice study.

The checked line below transcribes that existing owner decision. It is not a new approval made by Codex or CI. Reusable plans and templates remain unchecked for future releases.

- [x] Repository owner reviewed real novice usability results

## Release authorization and correction boundary

v1.3.0 is complete as recorded in [issue #30](https://github.com/PureSaber/vault-unified/issues/30#issuecomment-5646056634). The historical documents at the tag remain unchanged. The packaged failed-restore coverage and schema-1 asset-kind limitations above remain explicit; this correction does not invent missing evidence or change the shipped artifacts.

Before any **future** formal tag is created, every applicable automated, packaged, artifact, issue and human gate must be checked by the responsible reviewer. A failed gate returns work to a small corrective PR and a new candidate build. Missing evidence must be obtained or explicitly handled by the responsible reviewer, not silently marked passed by automation.
