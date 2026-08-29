# Vault Unified v1.1.5

本地加密密码库 + **Tauri 桌面应用** + 多密码源 **双向同步**（Bitwarden、KeePassXC、gopass；Proton Pass 需 Plus）。

## 功能概览

| 功能 | 说明 |
|------|------|
| 本地加密库 | 兼容 legacy Scrypt/AES-GCM；新建桌面库默认 Argon2id + KEK/DEK v3 |
| 桌面 App | Tauri + React 图形界面 |
| 双向同步 | 拉取 + 推送到已配置的外部源 |
| 主数据源 | 可设 local / bitwarden / keepassxc / gopass / proton_pass |
| 冲突处理 | 弹窗对比，默认偏向主数据源 |
| CLI | `vault.cmd` 命令行仍可用 |

## 快速开始

### CLI（已有用户）

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
.\vault.cmd
```

### 桌面应用

推荐使用一键脚本：

```powershell
powershell -ExecutionPolicy Bypass -File apps\desktop\start-desktop.ps1
```

源码开发也可以手动启动 Tauri；**不要预先启动固定端口 API**。Tauri 会独占启动 sidecar，由 sidecar 绑定系统分配的随机 loopback 端口并生成一次性启动密钥：

```powershell
.venv\Scripts\pip install -e ".[api]"
cd apps\desktop
npm install
npm run tauri dev
```

**发布安装包（含 API sidecar）：**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-desktop-release.ps1
```

仅构建 sidecar：`scripts\build-api-sidecar.ps1`（输出到 `apps/desktop/src-tauri/binaries/`）。安装版默认把库写在 `%LOCALAPPDATA%\VaultUnified\.vault\secrets.vault`（可用 `VAULT_DATA_DIR` / `VAULT_FILE` 覆盖）；源码开发时仍用仓库根目录 `.vault`。

桌面 sidecar 的身份验证、随机端口和会话令牌边界见 [`docs/sidecar-security.md`](docs/sidecar-security.md)。
本地文件的原子替换、备份和显式崩溃恢复见 [`docs/atomic-storage-recovery.md`](docs/atomic-storage-recovery.md)。
Vault Format v3 的兼容边界见 [`docs/vault-format-compatibility.md`](docs/vault-format-compatibility.md)，显式创建、加密与密钥轮换见 [`docs/vault-v3-cryptography.md`](docs/vault-v3-cryptography.md)。
Legacy → v3 的 dry-run、显式迁移、崩溃续作与逐字节回滚见 [`docs/vault-v3-migration.md`](docs/vault-v3-migration.md)。
V3 设备解锁、Windows keyring allowlist 与可选回滚锚点见 [`docs/vault-v3-keyring.md`](docs/vault-v3-keyring.md)。
多来源三方比较、durable saga、冲突快照与删除 tombstone 见 [`docs/sync-ledger.md`](docs/sync-ledger.md)。
个人自动备份、条目扩展、恢复包、浏览器填充与移动端边界见 [`docs/personal-edition.md`](docs/personal-edition.md)。

## 同步命令

```powershell
.\vault.cmd sync              # 仅从外部拉取
.\vault.cmd sync -b           # 双向同步（拉取 + 推送 + 冲突检测）
.\vault.cmd push "GitHub"     # 推送单条到已启用的外部源
.\vault.cmd push --all        # 推送所有 dirty 条目
.\vault.cmd sources list      # 查看外源启用状态
.\vault.cmd sources enable bitwarden
.\vault.cmd sources disable proton_pass
.\vault.cmd conflicts list    # 查看冲突
.\vault.cmd conflicts resolve <id> --choice local
.\vault.cmd import keepassxc  # 从 KeePassXC 拉取
.\vault.cmd import gopass
.\vault.cmd desktop           # 启动桌面开发模式
```

## 主数据源设置

在桌面 App **Settings** 页面或 `.vault/sync_prefs.json`：

```json
{
  "primary": "local",
  "enabled_sources": ["bitwarden", "keepassxc"],
  "auto_push_on_edit": true,
  "auto_pull_on_sync": true,
  "conflict_default": "primary"
}
```

- `enabled_sources`：缺省或 `[]` 表示仅本地库；显式 `null` 仅为旧配置兼容，表示四个外源全部启用
- 取消勾选某源会**停止**对该源的 pull/push，但保留本地 `linked_sources`
- 桌面 App **Settings → Enabled external sources** 或 CLI：`vault sources list|enable|disable`
- `primary=local`：只有在 `auto_push_on_edit=true` 且目标源已显式启用时，本地修改后才会自动 push

## 外部 CLI 安装（Windows）

与外部密码源同步需要各自官方 CLI。它们是**系统级工具**，装在电脑上即可，**不需要也不应放进本仓库**。

| 工具 | 费用 | 安装 |
|------|------|------|
| Bitwarden CLI (`bw`) | 免费 | `winget install Bitwarden.CLI` |
| KeePassXC (`keepassxc-cli`) | 免费 | `winget install KeePassXCTeam.KeePassXC` |
| gopass | 免费 | `winget install Git.Git GnuPG.Gpg4win gopass.gopass` |
| Proton Pass CLI (`pass-cli`) | Plus 需付费 token | 见下方脚本 |

**一键初始化（推荐）：**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-keepassxc.ps1
powershell -ExecutionPolicy Bypass -File scripts\setup-gopass.ps1
powershell -ExecutionPolicy Bypass -File configure-integrations.ps1
```

**Proton Pass CLI（官方脚本）：**

```powershell
Invoke-WebRequest -Uri https://proton.me/download/pass-cli/install.ps1 -OutFile install.ps1
.\install.ps1
```

若提示脚本无法执行，可用管理员 PowerShell 临时允许：`Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

**验证安装：**

```powershell
bw --version
keepassxc-cli --version
gopass version
pass-cli --version
.\vault.cmd status
```

`status` 中应显示 `CLI found`；若仍提示 `credentials missing`，请在桌面端 Settings → External password-manager connections 中保存并测试凭证。

## 外部源配置（Windows Credential Manager）

推荐在桌面 App **Settings → External password-manager connections** 中配置。敏感值保存在 Windows Credential Manager；数据库路径、服务器地址、Vault 名称等非敏感配置保存在：

```text
%LOCALAPPDATA%\VaultUnified\config\integrations.json
```

桌面 API 只返回“是否已保存”和来源，不会把主密码、client secret 或 token 回填到界面。

```powershell
powershell -ExecutionPolicy Bypass -File configure-integrations.ps1
```

该脚本只负责启动桌面配置页，**不会收集密码或把 token 写入 `.env`**。

**需要准备：**

| 服务 | 需要的信息 |
|------|------------|
| Bitwarden | Security → API Key 的 Client ID / Client Secret + 主密码；可选自建服务器地址 |
| KeePassXC | `.kdbx` 路径 + 库主密码；可选 key file 与 group |
| gopass | 已初始化的 store；可选 mount、store 路径与前缀 |
| Proton Pass | Personal Access Token（需 Pass Plus）；可选 Share ID / Vault 名称 |

`.env` 和环境变量仅保留给明确的源码开发或无界面自动化场景。它们不会被桌面端自动迁移进凭据管理器，也不应提交到 GitHub。

## 常见问题（FAQ）

### Proton Pass：找不到访问令牌 / 提示要升级？

- 正确位置：**设置 → 访问令牌**（API Tokens），不是「安全」。
- **免费版（Proton Free）无法创建访问令牌**；CLI 自动化同步需要 **Proton Pass Plus** 付费套餐。
- 免费用户可：用 **Bitwarden + KeePassXC + gopass**（均免费 CLI），或纯本地库。

### KeePassXC：网盘同步注意什么？

- `.kdbx` 是加密文件，可放在 OneDrive/Dropbox 等同步文件夹。
- **同步前关闭 KeePassXC GUI**，避免文件锁；等网盘同步完成再在另一台打开。
- 主密码泄露则库可被解开；可选 `KEEPASSXC_KEY_FILE` 增加第二因子。

### gopass：需要什么前提？

- 需 **GPG 密钥** + 已 `gopass setup` 的 store（可用 git 同步）。
- 运行 `scripts/setup-gopass.ps1` 安装依赖并初始化。

### 免费源对比（替代 Proton Plus）

| 源 | CLI | 免费自动化 | 同步方式 |
|----|-----|------------|----------|
| Bitwarden | `bw` | 是 | 官方云 API |
| KeePassXC | `keepassxc-cli` | 是 | 加密文件 + 网盘 |
| gopass | `gopass` | 是 | GPG + git |
| Proton Pass | `pass-cli` | 需 Plus | 访问令牌 |

### Bitwarden：加密密钥设置 vs API 密钥？

- **加密密钥设置**（KDF / 迭代次数）：vault 加密参数，**与 CLI 同步无关**，默认不要改。
- **API 密钥**（OAuth client_id / client_secret）：**设置 → 安全 → API 密钥**，在桌面端 Bitwarden 连接设置中保存。
- `scope`、`grant_type` 由 Bitwarden 固定，无需配置；主密码也通过桌面连接设置写入 Windows Credential Manager。

### `sync` 显示 `0 added, 0 updated`？

- 连接可能已成功，但**云端保险库是空的**（例如 Proton / Bitwarden 都还没有条目）。
- 先在对应网页里添加或导入密码，再运行 `.\vault.cmd sync`。

### 什么该进 GitHub，什么不该？

| 可提交 | 不可提交 |
|--------|----------|
| README、`.env.example`、`configure-integrations.ps1` | `.env`、`.vault/`、`token.txt` |
| 源代码、安装说明 | API secret、主密码、真实 token |

凭证泄露后：轮换 Bitwarden API 密钥 / 主密码；Proton token 在控制台撤销并重建。

## 架构

```text
Tauri Desktop (React)
       │ Tauri IPC：获取本次运行的 endpoint + bootstrap secret
       ▼
FastAPI sidecar（127.0.0.1 随机端口；每次启动新实例）
       │
       └──► UnifiedVault ──► LocalVault (encrypted)
                    │
                    ├── SyncEngine (bidirectional)
                    ├── Bitwarden (bw)
                    ├── KeePassXC (keepassxc-cli)
                    ├── gopass
                    └── Proton Pass (pass-cli, Plus)
```

## 安全

- Tauri 每次启动自己拥有的 API sidecar，不复用固定 localhost 端口上的已有进程
- sidecar 先绑定系统分配的随机 `127.0.0.1` 端口，再通过私有 stdout pipe 返回实例 ID 和高熵 bootstrap secret
- 所有 API 请求（包括 health 与 unlock）必须携带 `X-Vault-Bootstrap`，父进程还会核对实例 ID
- Bearer Session 仅保存在渲染进程内存；刷新、锁定或退出后失效，不写入 `localStorage`
- `.vault/`、`.env`、`token.txt` 不提交 Git
- 密码 API 响应默认脱敏

## 版本

**v1.1.5** — 当前版，包含：

- 本地加密库 + CLI（`vault.cmd`）+ Tauri 桌面（中英切换）
- **PyInstaller API sidecar** 打进安装包（`scripts/build-desktop-release.ps1`）
- 外部源：Bitwarden、KeePassXC、gopass、Proton Pass（Plus）
- 双向同步、冲突持久化、主数据源、`enabled_sources`
- 安全加固：loopback 绑定、unlock-keyring / generate 鉴权、冲突密码脱敏、剪贴板自动清空
- 同步正确性：无时间戳外源不再覆盖 dirty 本地；部分 push / 删除失败不误标干净
- 桌面端不再复用固定端口服务；每次启动均由 Tauri 拥有随机 loopback 端口的 sidecar
- 每个 API 请求均需携带本次启动生成的 bootstrap secret，Tauri 同时验证实例 ID
- Bearer Session Token 仅保存在渲染进程内存中；Windows 进程树随桌面应用一同退出
- 新建桌面保险库默认使用 Vault Format v3，并要求两次确认主密码
- 外部服务秘密使用 Windows Credential Manager，普通配置写入 LocalAppData
- 提供可验证、可固定、预览清理和原子恢复的备份中心
- 桌面同步采用只读预览 + 一次性确认令牌，默认不启用任何远端源
- CLI 与桌面版在显式数据目录下共享同一集成配置和备份目录
- 剪贴板仅在内容仍为刚复制的密码时自动清空，不覆盖用户后续复制内容
- 备份清理使用会话绑定、单次有效的预览令牌，只执行预览中的精确候选集
- 发布后来源校验可正确解引用注释标签，同时保持标签和发布资产不可变
- 外部源往返比较不再把本地 tag 误判为远端差异；远端更新保留本地 tag
- 接受远端冲突版本会同时确认对应挂起操作，不再残留无效 dirty 状态
- Bitwarden 回收站条目按已删除确认；已完成远端确认的保留 tombstone 不计入 dirty
- KeePassXC 2.7.x 的连接检查、读取参数与分组路径均与官方 CLI 输出保持一致
- KeePassXC 回收站按已删除处理：同步会保留其原生可恢复副本，但不会重新导入或卡住 tombstone 确认
- gopass 1.16.x 的 Store path 通过官方运行时配置生效，且写入后保留原始标题
- 原子写入、崩溃恢复和非覆盖式备份；异常事务默认 fail closed
- 桌面新库默认 Vault Format v3；CLI 创建、迁移与密钥轮换仍为显式操作
- dry-run 优先的 legacy → v3 迁移、逐字节备份、恢复续作和显式回滚
- Windows Credential Manager 设备解锁边界和可选回滚锚点
- 多来源三方同步 ledger、durable operation saga、加密冲突快照和保留式删除 tombstone

v1.1.5 不会自动改写现有 v1/v2/v3 保险库；新建桌面保险库默认使用 v3，legacy CLI/setup 创建路径继续保持兼容。迁移、设备解锁、密钥轮换和回滚仍需显式操作；降级前必须按运行手册恢复兼容备份。

GitHub: https://github.com/PureSaber/vault-unified
