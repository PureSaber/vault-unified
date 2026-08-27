# Synchronization field support

Vault Unified has a small portable entry model. A remote manager can contain fields that do
not have a portable equivalent. The synchronization layer must preserve those fields inside
the encrypted local vault or refuse a write that would require reconstructing them.

## Current support matrix

| Field or item type | Bitwarden | KeePassXC | gopass | Proton Pass |
|---|---|---|---|---|
| Login username/password | Read/write | Read/write | Read/write | Read/write |
| Primary URL | Read/write | Read/write | Adapter mapping | Read/write |
| Additional URLs and match rules | Preserved; first URL is editable | Not yet modeled | Not portable | Not yet modeled |
| Notes | Read/write | Read/write | Read/write | Read/write |
| Vault Unified tags | Local-only; preserved on pull | Local-only; preserved on pull | Local-only; preserved on pull | Local-only; preserved on pull |
| Secure Note | Read/write without mapping notes into password | Not yet modeled | Adapter mapping | Not yet modeled |
| TOTP seed | Preserved on existing and safely recreated personal items | Not yet modeled | Not yet modeled | Not yet modeled |
| Custom fields | Preserved on existing and safely recreated personal items | Not yet modeled | Not yet modeled | Not yet modeled |
| Attachments | Preserved when updating an existing item; recreation is blocked | Unsupported | Unsupported | Unsupported |
| Organization/collection membership | Preserved on existing items; recreation is blocked | Not applicable | Not applicable | Not yet modeled |
| Card and Identity item types | Not imported or written | Not modeled | Not modeled | Not modeled |

## Bitwarden behavior

Bitwarden login and Secure Note items keep source-specific metadata under
`SecretEntry.source_metadata["bitwarden"]`. The metadata is encrypted with the rest of the
local vault and is not returned by the desktop API.

Updating an existing item first fetches the current Bitwarden object and changes only the
portable fields. Secondary URLs, URI match rules, TOTP, custom fields, attachments, folder,
favorite state, reprompt settings, and other untouched remote properties therefore remain in
the submitted object.

Creating a replacement item is refused when the local metadata says the original contained
attachments, organization ownership, or collection membership. Those properties cannot be
reconstructed safely by this adapter and silently dropping them would be data loss.

Source-specific metadata is deliberately not part of cross-manager conflict comparison. It
is refreshed on successful Bitwarden pulls but is never pushed to a different password
manager as though it were portable data.

Vault Unified tags are also local metadata because none of the current external adapters has
a lossless native tag mapping. They are excluded from remote read-back conflict comparison
and are retained when a remote update is accepted.
