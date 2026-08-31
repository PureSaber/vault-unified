# Vault Unified v1.3 UX terminology

## Default-language contract

Default screens describe the user's object, location, outcome, and next action. Implementation terms may appear only after an explicit **Technical details**, **Advanced options**, **Manage backup history**, **Connection advanced settings**, or **Review sync details** action, or in technical error details needed for support.

| Internal term | Default user-facing term | Where the internal term may appear |
| --- | --- | --- |
| `local` | This device / 这台设备 | Technical sync details |
| `remote` | Connected service / 已连接的服务 | Technical sync details |
| `primary source` | Default sync location / 默认同步位置 | Connection advanced settings only |
| `dirty` | Waiting to sync / 等待同步 | Raw value never shown in normal status |
| `conflict` | Changed in both places / 两处都发生了修改 | “Conflict” may remain in support-oriented technical details |
| `sidecar` | Background service / 后台服务 | Technical error details only |
| `keyring` | Windows secure storage / Windows 安全存储 | Technical details |
| `tombstone` | Deleted, waiting to sync / 已删除、等待同步 | Technical sync details only |
| `preview token` | This review / 本次预览 | Technical diagnostics only; never show its value |
| `local_atomic` | Automatic recovery backup / 自动恢复备份 | Backup-history technical details only |
| `Share ID` | Service workspace identifier / 服务空间标识 | Connection advanced settings only |
| `Argon2id`, `AES-GCM`, `Vault Format v3` | Encrypted on this device / 在这台设备上加密保存 | First-run Technical details and security documentation |

## Action wording

- Prefer **Add password**, **Copy password**, **Back up now**, **Verify latest backup**, **Restore from backup**, and **Lock now**.
- Say which side a deletion affects: **Will be deleted from this device** or **Will be deleted from Bitwarden**, for example.
- A pending or unavailable result is never called success. State what remains unknown and the next action.
- Destructive confirmation states the object, count, destination, and consequence. Color is supplementary, not the only signal.
- TOTP is **Authenticator key** or **TOTP key**. Do not call it a built-in authenticator until the product actually generates and times codes.

## Entry labels

Internal entry enums are translated before display:

| Enum | English | 中文 |
| --- | --- | --- |
| `login` | Login | 登录信息 |
| `secure_note` | Secure note | 安全备注 |
| `card` | Card (compatibility) | 卡片（兼容） |
| `identity` | Identity (compatibility) | 身份信息（兼容） |
| `ssh_key` | SSH key (compatibility) | SSH 密钥（兼容） |
| `recovery_code` | Recovery code (compatibility) | 恢复代码（兼容） |

Compatibility types remain losslessly readable and editable, but are not offered as ordinary new-item choices before dedicated forms exist.

## Secret-safe wording and diagnostics

Messages, receipts, preview metadata, logs, screenshots, and traces must never include password values, TOTP secrets, recovery codes, attachment contents, custom-field secret values, bearer/browser tokens, or bootstrap secrets. A user-visible error should name the failed operation and safe next step. Technical details may include non-secret identifiers, source names, generations, digests, and field names, but never secret values.
