# Passkey implementation

## Current increment

The portable credential and WebAuthn protocol layer is implemented. Browser
interception and the desktop approval flow are the next increment; this layer
alone does not enable website login. The released installer remains v1.3.0.

Credentials use ES256 (P-256), random 32-byte credential IDs and RP-provided user
handles. Private keys remain in the encrypted vault's optional
`vault_unified:passkeys` entry namespace. The namespace has version 1 and an
immutable credential list. Up to 100 credentials can belong to one account.
Old schema-2 vaults must complete the existing backed-up schema-3 upgrade first.

## Protocol and trust boundary

- The trusted extension worker must derive the origin from the browser's actual
  frame/document. The page cannot select a different origin. The backend requires
  a canonical HTTPS origin (HTTP localhost is supported for local applications),
  rejects IP addresses and enforces RP ancestry using the offline public/private
  suffix list. Cross-origin iframe support is not enabled by this layer.
- Every operation requires a fresh desktop user-verification decision. An
  unlocked vault or a website button is not verification. The integration must
  verify the master password before calling these internal functions and check
  cancellation, session validity and timeout before publishing a result.
- Registrations are discoverable, use `none` attestation and a zero AAGUID. The
  extension must persist the credential successfully before returning registration
  success. Other algorithms, roaming-key-only requests and unsupported extensions
  must fall through to another browser provider.
- The authenticator signs the exact authenticator data and client-data hash.
  Presence and verification are asserted only after desktop approval. Credentials
  are backup eligible. Registration does not assert that a backup already exists;
  assertions may set backup state only after a caller has evidence of a second
  durable copy. The signature counter is zero, as permitted for credentials
  synchronized across devices without a global monotonic counter.
- Private keys are absent from entry APIs, plaintext CSV/JSON export, ordinary
  history, and revealed conflict displays. Full encrypted backup, recovery kits
  and personal synchronization retain them. External password-source refresh and
  conflict choices preserve local Passkeys without accepting new ones from those
  connectors.

## Data lifecycle

Duplicate-account merge unions credential identities and refuses inconsistent
duplicates before writing. Personal synchronization merges independent additions
and removals; concurrent changes to one credential produce a conflict instead of
combining key fields. Trash/archive retain credentials but remain unavailable for
normal login. Restoring an account retains its credentials; permanent removal
scrubs them from the live entry. Previously created encrypted backups and remote
encrypted records retain their historical content under their existing policies.

Encrypted recovery can re-encrypt these credentials under a new master password,
and a second Vault Unified device can use the same credential. External password
manager Passkey conversion remains outside this release's migration scope.

Reverting the implementation leaves the optional namespace in encrypted data.
Keep an encrypted backup and avoid editing/merging Passkey accounts with a client
that does not support them; return to a supporting client for lossless operation.

## Verification

Generated-data tests use Yubico's `Fido2Server` as an independent RP verifier for
registration, allow-list and discoverable authentication. Negative cases cover RP
scope, public/private suffixes, exclusions, missing verification, malformed binary
values, unsupported requests and tampered/replayed responses. Storage tests cover
atomic rejection, encrypted restart, two-device folder synchronization, backup,
recovery under a new password, metadata preservation, conflict merge and public
redaction. Browser and installed acceptance belong to the following integration
and final delivery stages.

References: [WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/),
[Yubico python-fido2](https://developers.yubico.com/python-fido2/),
[Bitwarden extension provider architecture](https://contributing.bitwarden.com/architecture/deep-dives/passkeys/implementations/provider/browser-extension/).
