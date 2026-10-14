# Personal synchronization protocol — implementation in progress

Stage 5 uses immutable authenticated per-device records, transported identically
through a user-selected folder or WebDAV collection. This document describes the
implementation contract; no connected product workflow is delivered yet.

Each space has a random 256-bit AES-GCM key and random identifier. Each installation
has a separate random device identifier. A change filename contains only the device
and monotonic sequence. AEAD associated data binds protocol version, space and
filename. Records contain the causal vector, object identity, previous and new
values and an explicit resolution flag. Schema/identity/size/depth/finite-JSON
checks precede use. Device announcements cannot name another device.

Files are immutable. Folder uploads use a temporary ciphertext file followed by
atomic no-replace rename (Windows) or hard-link creation (POSIX). WebDAV uses
conditional `PUT` with `If-None-Match: *`; a repeated sequence must contain exactly
the same ciphertext. Persist the random nonce/ciphertext in the encrypted outbox
before upload so an acknowledgement loss does not create a different retry body.
No distributed lock file is used. WebDAV must implement conditional creation.
TLS is required except for explicit loopback test/local services. Credentials must
be held in the approved Windows Credential Manager, never in URLs or settings.
Redirects are refused, response sizes/time are bounded and listing paths cannot
redirect a download to another location. Lists use `PROPFIND Depth: 1`.

Local encrypted replication state must commit atomically with reconciled entries.
It contains the last synchronized view, received vectors, per-object causal
versions, outbox, conflicts, device announcements and retained deletion identities.
The view is needed to find offline edits and perform three-way merge; it replaces
no user backup. The reserved replication namespace never replicates recursively.
External-connector bookkeeping and local Windows/browser grants remain local;
portable credential fields, extensions, attachments, authenticator data, histories
and other user metadata replicate.

Before network access, capture offline edits as durable sequenced outbox records.
Publish idempotently, download unseen changes and process only records whose
sequence predecessor and causal dependencies are present. A partial listing or
connection failure leaves outstanding records pending, never skips a sequence.
Require the captured vault generation when committing a merge so an editor change
made during I/O cannot be overwritten.

Different fields merge automatically. Same-field conflicts retain base, local and
remote values. Concurrent trash/delete and edit is an object-level conflict.
Retained deletion identities prevent an old offline device's create record from
reviving a removed entry. Ordinary and merged histories combine immutable version
IDs; overflow moves to the existing merged-history namespace instead of being
silently discarded. User resolution creates an explicit causal resolution record,
even if the chosen value equals the already-visible local value. A later ordinary
edit must not implicitly acknowledge or clear an unresolved field conflict.

Device announcement records include their received causal context. A deletion
remains retained until every known authorized device has acknowledged it; the first
implementation may keep it longer. No early record garbage collection is allowed.
New installations receive a fresh device identity rather than reusing the identity
inside a recovered backup. Group joining and conflict application require the
existing preview/confirmation and stale-state safeguards. Normal non-conflicting
background synchronization is authorized by enabling that connection.

Reference semantics: [WebDAV methods and collection listings](https://www.rfc-editor.org/rfc/rfc4918#section-9),
[HTTP conditional requests](https://www.rfc-editor.org/rfc/rfc9110#section-13).
