# v1.3 novice usability test plan

## Purpose and evidence boundary

This study checks whether a person who has not read the README and does not know password-manager implementation details can complete the main Windows workflow. Automation may verify controls, accessibility rules, timing mechanics, and regressions, but it is not evidence of human comprehension. Only sessions observed with real novice participants count toward the release's novice-usability targets.

Every session must use an isolated Windows test account or disposable directory and newly generated fake data. Do not use an existing vault, personal password, real account, external-service token, recovery code, or personal browser profile. Do not record a screen until the participant and moderator have confirmed that only generated values are visible.

## Participants

- Recruit people who have not read this repository's README or implementation documentation.
- Prefer participants who do not work on this project and cannot explain its storage or synchronization internals.
- Record only an anonymous participant code and relevant experience band; do not record names, email addresses, account identifiers, or employer details.
- Aim for at least five formative sessions. Report the actual sample size and uncertainty; do not present a small sample as proof for all users.

## Test environment

1. Use the exact unsigned/signed release candidate asset recorded in the results template.
2. Verify its SHA-256 against the candidate release manifest before the session.
3. Start from a clean test account or VM with no Vault Unified data.
4. Provide a printed/generated fake account card, for example an `example.invalid` website, invented username, and disposable password.
5. Do not pre-open README, source files, command prompts, or developer documentation.
6. Record Windows version, display scaling, app language, installer type, and whether assistive technology is used.

## Moderator script

Say: “We are testing the product, not you. Please think aloud. Use only the fake information on this card. I will not teach the interface unless you are blocked; any help I give will be counted.”

Give one task at a time without naming the required button. Do not explain encryption, backup, recovery, or browser-pairing terminology before the participant answers. If the participant is blocked, first ask “What would you look for next?”; then give the smallest useful hint and record it verbatim.

Stop a task immediately if the participant is about to use real credentials, overwrite non-test data, disclose personal information, or install into a non-test browser profile.

## Tasks

1. Install Vault Unified from the provided Windows installer.
2. Create a new vault.
3. Add the first account using the generated account card.
4. Find that account and copy its password.
5. Set up automatic encrypted backup to the provided empty test folder.
6. Close and reopen the application, then unlock the vault.
7. Explain in their own words the difference between an everyday encrypted backup and an emergency recovery kit.
8. Find where to install the browser extension; stop before using a personal browser profile.

For each task record success without help, success with help, failure, elapsed time, number of help interventions, observed hesitation, and the control or wording that caused it. Never record the password or recovery code itself.

## Post-session questions

- Where do you believe your passwords are saved?
- What would you use if the vault file or computer were lost?
- How is that different from the emergency recovery kit?
- What, if anything, did you expect to happen automatically?
- Which words or screens felt technical or unsafe?
- Administer the standard ten-item System Usability Scale without modifying its scoring.

## Suggested acceptance targets

- At least 90% complete vault creation without documentation.
- At least 90% add the first password without documentation.
- Median time for the core first-use path is no more than five minutes.
- The core path does not require understanding implementation terms.
- Mean unsolicited moderator help is no more than one intervention per participant.
- At least 80% correctly explain everyday backup versus recovery kit.
- At least 80% find the browser-extension installation entry.
- Suggested aggregate SUS is at least 75.

These are decision targets, not claims. Record sample size, confidence limitations, failures, accessibility observations, and unresolved severe issues. A missed data-integrity or security boundary blocks release regardless of the average score.

## Evidence handling

- Prefer notes and task timings over recordings.
- If recording is necessary, obtain consent and keep it outside GitHub.
- Review every screenshot or excerpt before sharing; crop or redact participant and generated secret values.
- Do not upload Playwright traces, browser profiles, vault files, exports, installer logs, or full application logs from a human session.
- Use [`usability-test-results-template.md`](usability-test-results-template.md) for the sanitized aggregate.

## Release decision

The repository owner reviews the sanitized results, open usability issues, and deviations from the targets. Codex and CI may prepare evidence but must not check the final line:

- [ ] Repository owner reviewed real novice usability results
