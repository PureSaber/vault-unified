# Security policy

Vault Unified handles credentials, so vulnerability reports must minimize both disclosure and test data.

## Supported versions

| Version | Support status |
| --- | --- |
| Latest stable release | Security fixes supported |
| Immediately previous minor release | Critical fixes considered when a safe backport is practical |
| Older releases | Not supported |
| Unreleased branches and pull requests | Tested during development; not promised as stable releases |

The current stable version is listed on the [GitHub Releases page](https://github.com/PureSaber/vault-unified/releases/latest). Upgrade to the latest stable release before reporting a problem that may already be fixed.

## Report a vulnerability privately

Use a [GitHub Security Advisory](https://github.com/PureSaber/vault-unified/security/advisories/new). Do not open a public issue for a suspected zero-day, authentication bypass, secret disclosure, vault corruption, or other exploitable weakness.

Send only the minimum information needed to reproduce the problem:

- affected version, operating system, and installation type;
- expected and observed behavior;
- a small reproduction using a newly generated disposable vault and fake credentials;
- relevant sanitized stack frames or filenames;
- an impact explanation and, if known, a safe mitigation.

Never upload or send a real vault, master password, browser or bearer token, bootstrap secret, recovery code, TOTP key, attachment, plaintext export, full log, or unredacted trace. Replace sensitive values with obvious placeholders and verify screenshots and archives before attaching them.

Maintainers will acknowledge and triage reports as availability permits, coordinate a fix and disclosure when warranted, and avoid publishing exploit details before users can update. This volunteer project does not promise a fixed response or resolution time.

For ordinary bugs that contain no security-sensitive information, use the public bug-report template.
