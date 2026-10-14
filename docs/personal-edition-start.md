# 开始使用 Vault Unified / Getting started

## Windows 安装

1. 选 `*-setup.exe` 安装；使用 MSI 的电脑请选择 `*.msi`。两种格式无需同时安装。
2. 首次打开创建密码库，记好主密码。在“安全与恢复”设置独立位置的加密备份。
3. “密码 → 从浏览器导入”选择 Chrome／Edge 导出的 CSV，检查预览后确认。
   导入成功后删除该明文 CSV。也可以直接添加账号。
4. 解压配套 `Vault-Unified-Browser-Extension-v1.4.0.zip` 到长期保留的目录。
   打开 `chrome://extensions` 或 `edge://extensions`，开启开发者模式并加载此目录。
5. 在桌面“连接”生成配对码，在扩展输入本机地址和配对码。勾选长期授权后，
   下次解锁桌面即可恢复连接。按网站开启输入框建议或 Passkey 支持。

## 从 v1.3.0 升级

先创建并验证一份加密备份，退出托盘中的应用，再运行同种格式的新安装包。
密码库和偏好保留在原位置。首次启用新功能时，按界面预览升级数据结构；
确认前可取消，确认后会保留加密旧格式备份。

扩展更新：退出扩展弹窗，把新版 ZIP 内容覆盖到原解压目录，在扩展管理页点击
“重新加载”。沿用目录能保留扩展身份；若移到新目录，请重新配对。
移除或关闭旧的重复扩展，避免两个版本同时承接网站请求。

以后可在“设置 → 应用更新”检查更新。自动检查默认关闭，安装始终需要确认。
下载通过签名和版本验证后，才创建并保留加密备份、锁定并安装。失败后可重试，
备份保留在“安全与恢复”。安装中断时重新运行同版本安装包；不要删除原密码库。

换电脑请用“安全与恢复”的迁移包及隔离恢复演练，或连接同一加密同步文件夹／WebDAV。
主密码和恢复码应分开离线保存。新电脑的浏览器授权和 Windows Hello 需重新设置。

卸载会移除该安装的浏览器桥接注册，保留密码库和加密备份。需要重新使用时安装并配对。

## 可选分享服务

解压 `Vault-Unified-Sharing-Service-v1.4.0.zip`，按其中 `docs/encrypted-sharing.md`
配置管理凭据并用 Python 或 Docker Compose 运行。桌面“分享”连接该服务。
公网使用配置 HTTPS；本地开发可用回环地址。服务保存密文，链接密钥留在链接片段中。

## English quick start

Install either the EXE or MSI, create a vault, and configure an encrypted backup.
Import a browser CSV with preview, or add accounts directly. Extract the matching
extension ZIP, load it in Chrome/Edge developer mode, then pair it in Connections.
Authorize each website before enabling inline suggestions or passkeys.

For a v1.3 upgrade, retain a verified encrypted backup, quit from the tray and use
the same installer type. Review the in-app payload upgrade; it retains an old-format
backup. Replace extension files in the existing directory and reload the extension.
Update checks are optional; installation verifies signatures and retains a backup.
If interrupted, rerun the same installer without deleting your vault. For a new PC,
use migration/recovery rehearsal or encrypted folder/WebDAV sync, then authorize
the browser and Windows Hello again. Uninstall preserves vaults and backups.

The optional sharing-service ZIP includes Python and Docker Compose instructions
in `docs/encrypted-sharing.md`. Use HTTPS outside localhost. See `ACCEPTANCE.md`
for the short installed-version checklist.
