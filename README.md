# Vault Unified

Vault Unified 是面向个人使用的 Windows 密码管理器。密码加密保存在这台设备上；你可以添加、搜索和复制密码，设置自动加密备份，并按需连接已有的外部密码服务。

**v1.2.0** — 当前版。v1.3.0 正在进行可靠性与新手体验验收，尚未发布。

## 开始使用

### 1. 下载 Windows 安装包

前往 [最新版本下载页](https://github.com/PureSaber/vault-unified/releases/latest)，下载以下任一种文件：

- `*-setup.exe`：常用安装方式；
- `*.msi`：适合偏好 Windows Installer 的用户。

Vault Unified 当前正式支持 Windows。请只从本仓库的 GitHub Releases 下载，并保留安装包直到确认新版本能正常解锁和备份。

### 2. 创建保险库

打开 Vault Unified，选择“创建新保险库”，设置并确认主密码。密码会在这台设备上加密保存。主密码无法由项目维护者找回，请把它记录在安全的离线位置。

创建完成后会进入空的“密码”页面；不需要先连接其他服务。

### 3. 添加第一条密码

在“密码”页面选择“添加密码”，填写网站或应用名称、用户名和密码，然后保存。需要时可填写网站地址和备注；标签、验证器密钥、自定义字段、附件和历史信息位于“更多选项”。

返回密码列表后，可以搜索条目并直接复制密码。显示的密码会自动隐藏，切换页面或窗口失焦时也会隐藏。

### 4. 设置备份

进入“安全与恢复”，选择一个独立的备份文件夹，测试该位置，再启用自动加密备份。建议立即创建并验证一次备份。

- **加密备份**用于电脑或保险库文件损坏后的日常恢复。
- **紧急恢复包**用于忘记主密码或迁移等特殊情况；恢复码应与恢复包文件分开、离线保存。
- **明文导出**只适合短期迁移，不是备份；使用后应立即删除。

### 5. 安装浏览器扩展

在同一 [GitHub Release](https://github.com/PureSaber/vault-unified/releases/latest) 下载 `Vault-Unified-Browser-Extension-v<版本>.zip`：

1. 解压 ZIP；
2. 在 Chrome 或 Edge 打开扩展管理页并启用开发者模式；
3. 选择“加载已解压的扩展程序”，选中解压目录；
4. 回到桌面端“连接”页面，生成一次性配对码；
5. 在扩展中输入配对信息。

扩展只在用户打开扩展并明确选择条目后填充。多表单、改密页面、iframe 或其他无法安全判断的页面会拒绝静默填充。完整步骤见 [浏览器扩展安装说明](docs/browser-extension-install.md)。

## 日常使用

桌面端默认只有五个主要入口：

- **密码**：添加、搜索、复制和编辑条目；
- **安全与恢复**：自动锁定、备份、验证和恢复；
- **连接**：可选外部密码服务、同步状态和浏览器配对；
- **设置**：语言、通用偏好、版本信息；
- **立即锁定**：立即清除当前会话和内存草稿。

外部密码服务完全可选。无冲突时不会显示冲突入口；正常同步状态不会占用主要界面。任何导入、删除、同步覆盖或恢复操作都应先显示预览并要求明确确认。

## 隐私与安全边界

- 项目不包含遥测、分析、崩溃上传或用户追踪 SDK；
- 主密码、恢复码和令牌不会写入普通浏览器持久化存储；
- 外部服务秘密通过 Windows Credential Manager 保存；
- 浏览器扩展配对令牌只保存在浏览器会话存储中，锁定、退出、到期或重新配对后失效；
- 项目测试只使用生成的虚假数据和隔离目录。

请勿在公开 issue、PR、日志、截图或 trace 中提供真实保险库、主密码、令牌、恢复码、验证器密钥或附件。安全问题请按 [安全报告政策](SECURITY.md) 私下报告。更完整的数据说明见 [隐私与数据边界](docs/privacy-and-data-boundaries.md)。

## 可选的外部连接

“连接”页面可按需配置 Bitwarden、KeePassXC、gopass 或 Proton Pass。每个来源都有安装检查、缺少项提示、配置、连接测试和首次导入预览。默认不会启用任何来源，也不会把新导入条目自动推送到外部服务。

这些服务可能需要各自的官方命令行工具、账户或付费方案。普通本地使用无需安装它们。高级安装与凭据边界见 [集成凭据说明](docs/integration-credentials.md) 和 [同步字段支持](docs/sync-field-support.md)。

## 面向开发者

只有参与源码开发时才需要克隆仓库、安装 Python/Node/Rust 或使用命令行。Windows 环境、依赖安装、完整测试命令、PR 规则和安全要求统一记录在 [CONTRIBUTING.md](CONTRIBUTING.md)。

最小源码测试流程：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\pytest -q

Set-Location apps\desktop
npm ci
npm run lint
npm run build
npm run test:ui:install
npm run test:ui
```

CLI、外部适配器、存储格式、加密实现和后台服务属于高级维护内容。主要技术文档：

- [功能冻结与安全契约](docs/feature-freeze-v1.3.md)
- [产品信息架构](docs/product-information-architecture.md)
- [术语规范](docs/ux-terminology.md)
- [Vault 格式兼容](docs/vault-format-compatibility.md)
- [加密与密钥管理](docs/vault-v3-cryptography.md)
- [原子写入和崩溃恢复](docs/atomic-storage-recovery.md)
- [安全同步预览](docs/safe-sync-preview.md)
- [导入预览与撤销](docs/import-preview-and-undo.md)
- [备份保留与恢复](docs/backup-retention-and-restore.md)
- [浏览器扩展安装](docs/browser-extension-install.md)

## 发布与项目治理

- 许可证：[MIT](LICENSE)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全政策：[SECURITY.md](SECURITY.md)
- v1.3 发布门槛：[docs/release-readiness-v1.3.md](docs/release-readiness-v1.3.md)
- 真实新手测试计划：[docs/usability-test-plan.md](docs/usability-test-plan.md)

自动化测试不能替代真实新手研究。v1.3.0 的最终发布必须由仓库所有者审阅真实新手体验结果；在此之前，项目不会声称已经证明普通用户可用。

GitHub: https://github.com/PureSaber/vault-unified
