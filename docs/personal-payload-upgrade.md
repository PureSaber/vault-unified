# Personal payload upgrade

Open **Security & recovery → Personal vault data format → Review upgrade**.
Review the entry count and choose **Back up and upgrade**. Cancel leaves the
vault untouched. On success, unlock again. The backup list contains a pinned,
authenticated copy of the complete pre-upgrade encrypted file.

升级入口：**安全与恢复 → 个人版数据格式 → 查看升级**。确认条目数量后选择
**备份并升级**，完成后重新解锁。取消不会写入。升级前备份可在下方的
**管理历史备份**中找到，默认固定保留。

## Compatibility

The encrypted container remains format v3. Its authenticated `payload_schema`
now accepts 2 or 3 and must equal the decrypted payload's `version`. Schema 3
contains `version`, `entries`, and an encrypted `metadata` object. Empty metadata
is the default; feature-specific namespaced records are added by later increments.
All entry transactions retain it, as do import undo, recovery kits and password
rotation. This increment enables the structure; it does not itself implement sync,
generated-password history or passkeys.

Schema 2 known-answer crypto vectors remain unchanged. A v1.3 client rejects
schema 3 in the container parser before attempting decryption. Normal writes
cannot downgrade schema 3 or put it in an unframed legacy file. Legacy vaults
can upgrade in the same explicit flow using their master password. Framed vaults
keep their vault identity and existing key slots, including device unlock.

The upgrade reuses the existing session-scoped, expiring, one-use preview store,
backup catalog and atomic writer. Changed previews are refused. A backup or pin
failure prevents the replacement; a pre-commit write failure keeps old memory
and disk contents. Existing atomic-write recovery handles interrupted commits.
Every session is locked after a successful upgrade so no stale editor keeps the
previous schema in memory.

## Restore and acceptance

1. Use a generated old vault with entries, custom fields, attachments and history.
2. Preview, cancel and reopen it; confirm the original file is unchanged.
3. Upgrade and unlock; verify all entries and the pinned pre-upgrade backup.
4. Edit and import data, undo the import, create a recovery kit, and restore into
   an isolated directory; confirm all personal metadata remains intact.
5. Open the pre-upgrade backup in the old client. Opening the upgraded vault in
   the old client must report an unsupported payload schema.

To roll back before further edits, restore the pinned pre-upgrade backup through
the existing preview/confirm flow, then reopen with the previous client. For
changes made after upgrading, first retain a current encrypted backup: those
changes remain available to the new client and are not present in the older copy.

Validation uses generated data only. Backend checks cover legacy/framed upgrade,
old-reader rejection, stale and cancelled previews, backup/write failures,
preserved device slots, metadata round trips and schema/header mismatch rejection.
The English and Chinese renderer journeys use the real isolated API, test cancel,
upgrade, unlock and retained backup, and include accessibility inspection.
