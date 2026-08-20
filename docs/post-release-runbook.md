# Post-release checks and rollback

This runbook covers public release metadata and tests with disposable fake vaults. It must never require production telemetry, passwords, real vault files, environment files, tokens, third-party password-manager data, or user logs containing secrets.

## Release record

Before announcing or promoting a release, record all of the following in the release PR or operating notes:

- version, immutable tag commit, release URL, publication time, and the successful release workflow run;
- every asset name, byte size, media type, and expected SHA-256;
- the source commit and clean build/test results used for the assets;
- the vault-format version and whether the release can write a format older clients cannot read.

Do not use the Release API's mutable `target_commitish` field as proof of the shipped commit. Resolve the tag itself and compare its commit with the workflow `headSha`.

## Post-release checklist

Run at publication, then repeat the public-signal checks after roughly 24 hours, 72 hours, and seven days.

1. **Release identity**
   - Confirm the tag still resolves to the approved release commit.
   - Confirm the Release is published, not a draft or prerelease unless that was explicitly intended.
   - Confirm no later workflow modified the tag or replaced an asset.
2. **Asset integrity**
   - Confirm every expected asset exists with state `uploaded`, a nonzero size, and the recorded GitHub digest.
   - When independently downloading an asset, use an isolated temporary directory, compute SHA-256 before doing anything else, and never execute a digest mismatch.
   - Do not overwrite an existing release asset. A changed artifact requires a new version and a new review trail.
3. **Workflow health**
   - Confirm the tag workflow completed for the tag commit and that all build prerequisites and the release job succeeded.
   - Confirm ordinary `main` pushes and pull requests skip the release job.
   - Review check annotations for runner/runtime deprecations even when the run is green.
4. **Disposable Windows smoke test**
   - Use a clean VM or temporary Windows account with no real password-manager integrations configured.
   - Test NSIS and MSI independently: install, launch, unlock a generated fake vault, create/update/delete a fake entry, restart, and uninstall.
   - Verify the desktop owns a fresh loopback sidecar, rejects unauthenticated API requests, and removes the sidecar process tree on exit.
   - Keep synchronization disabled unless the test uses isolated fake endpoints and generated fake records.
5. **Public regression signals**
   - Review new issues, pull requests, and public release feedback for installation failures, startup failures, sidecar authentication problems, data loss, corruption, or unexpected format changes.
   - Reproduce credible reports minimally with generated data. Record OS/build, installer type, exact steps, expected/actual result, and severity without asking for a user's vault.
   - Move suspected vulnerabilities to the repository's approved private security channel; never request secrets as evidence.

## Triage and rollback

Classify a confirmed regression before changing release state:

- **Critical:** plaintext/keys exposed, authentication bypass, destructive vault corruption, or a compromised artifact.
- **High:** repeatable data loss, unsafe migration, sidecar identity failure, or installation/startup failure affecting a broad supported configuration.
- **Moderate/low:** bounded functional or presentation issue with a safe workaround and no confidentiality, integrity, or availability impact on stored credentials.

For critical or high impact:

1. Pause promotion and publish a concise warning that does not disclose exploit details or user data. Preserve the tag, assets, digests, workflow run, and investigation evidence; do not silently replace or delete artifacts.
2. Disable an automated distribution path only through a separately reviewed, reversible change. Repository code rollback does not uninstall binaries already downloaded by users.
3. Prefer a forward security fix on a new branch and PR. Reverting v1.0.4 would reintroduce the fixed-port sidecar reuse weakness, so using an older installer requires explicit owner approval after comparing that known security exposure with the new regression.
4. If code rollback is justified, revert the offending merge in a dedicated PR, run the full Python/frontend/Rust/release-build gates, and keep any vault opened during validation disposable.
5. Publish corrected binaries only under a new version. Never retag or replace an artifact under an existing version.

Vault Unified v1.0.4 does not migrate or rewrite the encrypted vault format. That makes a code rollback technically format-compatible, but it does not make the older sidecar security model acceptable by default.

## v1.0.5 decision criteria

Create a v1.0.5 release candidate when at least one of these is true:

- a confirmed v1.0.4 security, data-integrity, installer, startup, or sidecar lifecycle regression has a reviewed minimal fix;
- an expected v1.0.4 asset is missing or its digest differs, requiring correctly versioned replacement artifacts;
- a reachable high/critical dependency advisory has a safe, tested remediation;
- accumulated maintenance changes materially improve supported users and have completed the same release gates.

Do not release v1.0.5 while any of these is true:

- the regression or dependency advisory is not reproducible/reachable and severity is still uncertain;
- CI, package audits, installer builds, or disposable smoke tests are failing;
- the change can irreversibly rewrite an old vault, lacks backup/dry-run/recovery, or has unresolved backward-compatibility questions;
- release provenance, tag commit, asset digests, or rollback instructions are incomplete.

The release decision must state the triggering criterion, fixed issues, remaining risk, compatibility result, exact asset digests, and rollback owner. Creating the tag or GitHub Release remains an explicit owner action.

## v1.0.4 observation baseline (2026-08-20 UTC)

- Release: <https://github.com/PureSaber/vault-unified/releases/tag/v1.0.4>, published `2026-08-20T09:26:08Z`, not draft or prerelease.
- Tag/workflow commit: `a0716785ebe65e70bb0eb136430c692955700a97`; release workflow [run 32352880282](https://github.com/PureSaber/vault-unified/actions/runs/32352880282) succeeded.
- NSIS `Vault.Unified_1.0.4_x64-setup.exe`: 24,447,026 bytes, `sha256:09a3114062e86d1a0f5e72ece2750e001e1062ad01fe0b929a93e4e8a0cdfa29`, state `uploaded`, download count 1.
- MSI `Vault.Unified_1.0.4_x64_en-US.msi`: 25,128,960 bytes, `sha256:c08af6fe2ed365e3f32c65373fe6d642000b6755b5abfbe522445367e285135b`, state `uploaded`, download count 1.
- No GitHub issues existed at observation time; the post-release pull requests were planned CI maintenance, not reported product regressions.
- The latest maintenance `main` workflow [run 32359559774](https://github.com/PureSaber/vault-unified/actions/runs/32359559774) succeeded, and its release job was skipped on the branch push.

Download counts are observational only. They are not product telemetry, a quality metric, or evidence that an installation succeeded.
