# v1.3.0 release readiness

Status: **not yet approved for release**. This checklist records evidence; it does not authorize a tag. The v1.3.0 version contract, release notes, final candidate artifacts, and owner usability sign-off are completed only after all implementation PRs merge.

## Candidate identity

- Candidate source commit:
- Version-contract output:
- Candidate build run:
- Release manifest SHA-256:
- Open P0/P1 data-integrity query reviewed at:

## Automated quality gates

Record an exact command, CI link, commit, and result for every item.

- [ ] Python full suite: `.\.venv\Scripts\pytest -q`
- [ ] Python dependency audit: `.\.venv\Scripts\python -m pip_audit --local --skip-editable --progress-spinner off`
- [ ] TypeScript typecheck: `npm run lint` in `apps\desktop`
- [ ] Vite production build: `npm run build` in `apps\desktop`
- [ ] Playwright full generated-data journeys: `npm run test:ui` in `apps\desktop`
- [ ] Axe checks have no critical or serious violations
- [ ] Rust unit tests: `cargo test --manifest-path apps\desktop\src-tauri\Cargo.toml --lib`
- [ ] RustSec audit passes with the reviewed risk register
- [ ] Repository secret scan: `.\.venv\Scripts\python scripts\scan_repository_secrets.py --repo-root .`
- [ ] UI screenshots, traces, logs, and artifacts pass the generated-secret marker scan

## Packaged Windows gates

These are real packaged-lifecycle tests; renderer-only Playwright results cannot satisfy them.

- [ ] Packaged sidecar generated-data smoke passes
- [ ] NSIS install / launch / create-use-lock / stop / uninstall passes
- [ ] MSI install / launch / create-use-lock / stop / uninstall passes
- [ ] Failed restore leaves the active encrypted vault bytes unchanged
- [ ] Browser-extension ZIP structure and permission contract pass
- [ ] Browser pairing, fill safety, and lock/revocation checks pass

## Artifact and publication gates

Required immutable assets:

- Vault Unified EXE
- Vault Unified MSI
- `Vault-Unified-Browser-Extension-v1.3.0.zip`
- `release-manifest-v1.3.0.json`

Before publication:

- [ ] All component versions equal `1.3.0`
- [ ] The tag name to be created is exactly `v1.3.0`
- [ ] Release notes exist at `docs/release-v1.3.0.md`
- [ ] The manifest records source commit, tag, filenames, byte sizes, SHA-256 values, and asset kinds
- [ ] Extension ZIP is deterministic and contains only its allowlisted runtime files and installation guide
- [ ] EXE, MSI, extension ZIP, and manifest hashes independently match the manifest
- [ ] No open P0/P1 issue concerns data loss, cancellation writes, partial success, stale preview execution, restore corruption, or secret exposure

After publication:

- [ ] Download all four assets into a fresh directory through the public release endpoint
- [ ] Recompute every byte size and SHA-256 and compare with the downloaded manifest
- [ ] Re-run extension ZIP structure/version/permission validation
- [ ] Resolve the published tag through any annotated-tag layers and confirm it identifies the built source commit
- [ ] Do not replace a published asset; fix a defect in a new version

## Human novice usability gate

Attach or link a sanitized copy of [`usability-test-results-template.md`](usability-test-results-template.md) completed from real novice sessions. Automated journeys, screenshots, axe, and an expert walkthrough do not satisfy this gate.

- Real novice results:
- Owner decision and unresolved limitations:

Codex and CI must leave this line unchecked:

- [ ] Repository owner reviewed real novice usability results

## Release authorization

Do not create the formal tag until every applicable automated, packaged, artifact, issue, and human gate above is checked by the responsible reviewer. A failed gate returns the work to a small corrective PR and a new candidate build.
