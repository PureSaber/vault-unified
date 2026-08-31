## Summary

<!-- What single, reviewable outcome does this PR deliver? -->

## User-visible behavior

<!-- Describe what users will notice. Write "None" for infrastructure-only changes. -->

## Threat / data-integrity scope

<!-- State affected trust boundaries, persistent writes, preview/confirmation rules, and why secrets cannot leak. -->

## Tests

<!-- List exact commands and results. Tests must use generated fake data and isolated directories. -->

## Screenshots or recordings

<!-- Required for user-visible UI changes. Confirm that artifacts were scanned and contain no test secrets. -->

## Remaining risks

<!-- State known gaps, deferred dependencies, and what is not proven by this PR. -->

## Rollback instructions

<!-- Explain how to revert this PR without losing user data or weakening security boundaries. -->

## Feature-freeze checklist

- [ ] 本 PR 不增加新密码源
- [ ] 本 PR 不增加新条目类型
- [ ] 本 PR 不削弱现有安全边界
- [ ] 本 PR 只使用生成的虚假测试数据

## Review checklist

- [ ] The diff is purpose-specific, reviewable, and independently reversible.
- [ ] Relevant regression tests and required full checks pass without weakened assertions.
- [ ] Logs, exceptions, screenshots, traces, fixtures, receipts, and metadata contain no passwords, TOTP keys, recovery codes, attachment content, or tokens.
- [ ] Data-format changes, if any, are additive, optional, namespaced, defaulted, backward-compatible, and include rollback/loss tests.
- [ ] The v1.3 tracking issue is updated with status, remaining dependencies, and CI result.
