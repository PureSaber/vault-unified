# Account organization

New desktop vaults use the personal data format immediately. For an existing
vault, first use the backed-up upgrade in **Security & recovery**.

The password list now offers **Vault / Archived / Trash**. Open **Filters and bulk
organization** to filter favorites, tags and types, sort by name or recent changes,
and select up to 500 entries. Review the named selection before archiving,
restoring, moving to trash, permanently deleting or applying tags. Favourite
toggles are available in each entry's **More actions** menu.

中文入口：密码列表中的 **密码库 / 归档 / 回收站**，以及 **筛选与批量整理**。
条目的 **更多操作**中也可以收藏、归档或恢复。已有密码库可先在
**安全与恢复**中升级；新建库直接启用。

Trash keeps complete entries, attachments and history for 30 days. They can be
restored during that time. The next unlocked maintenance pass removes expired
credential content, including old external-sync base snapshots. A minimal deletion
record retains identifiers and sync acknowledgements. Archive has no expiry.
Neither archived nor trashed entries appears in browser fill or save candidates.
External-service metadata refreshes preserve the local organization state.

Plaintext JSON/CSV export includes active entries only, preventing deleted items
from reappearing as active accounts on import. The interface explains this scope.
Encrypted backups and recovery kits retain organization and history. The existing
CSV writer now excludes attachment data from its declared columns correctly.

Bulk previews are read-only, session-bound and single-use; changed selection or
vault contents requires a new preview. The existing transaction writer commits
the whole selection once. A failed write does not partially change memory or disk.
Switching categories during an operation always refreshes the currently selected
category, not a stale request's category.

## Acceptance

1. Add generated accounts, favorite one and filter by favorite/tag/type.
2. Select both, preview archive, cancel and confirm both remain active.
3. Archive both; confirm normal list and browser matching exclude them.
4. Move one archived item to trash, then restore it and verify its original secret.
5. Lock/reopen; confirm the retained archive and favorite states.
6. In an isolated generated-data test, advance a trash item's date past 30 days;
   run maintenance and verify active credential content is removed while archive
   and unexpired trash remain.
7. Prepare a bulk preview, edit an entry elsewhere and attempt apply; it must
   reject the stale preview without changing the other entries.

Duplicate merging, field-level history restoration and additional templates are
separate remaining increments of stage 2.
