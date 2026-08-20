# Vault Unified v1.0

本地加密密码库 + **Tauri 桌面应用** + 多密码源 **双向同步**（Bitwarden、KeePassXC、gopass；Proton Pass 需 Plus）。

## 功能概览

| 功能 | 说明 |
|------|------|
| 本地加密库 | 兼容 Scrypt + AES-GCM；显式可选 Argon2id + KEK/DEK v3 |
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

- `enabled_sources`：勾选参与同步的外源；缺省或 `null` 表示四个外源全部启用；`[]` 表示仅本地库
- 取消勾选某源会**停止**对该源的 pull/push，但保留本地 `linked_sources`
- 桌面 App **Settings → Enabled external sources** 或 CLI：`vault sources list|enable|disable`
- `primary=local`：本地修改后自动 push 到**已启用**的外部源

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

`status` 中应显示 `CLI found`；若仍提示 `credentials missing`，继续下一步配置 `.env`。

## 外部源配置（`.env`）

凭证只保存在本机 `.env`（已在 `.gitignore` 中，**不要提交 Git**）。可复制模板后手动编辑：

```powershell
copy .env.example .env
```

或运行交互式配置脚本（会写入 `.env` 并测试连接）：

```powershell
powershell -ExecutionPolicy Bypass -File configure-integrations.ps1
```

**需要准备：**

| 服务 | 获取方式 |
|------|----------|
| Bitwarden | [Security → API Key](https://vault.bitwarden.com/#/settings/security/security-keys) + 主密码 |
| KeePassXC | `.kdbx` 路径 + 库主密码（可放 OneDrive 同步文件夹） |
| gopass | `gopass setup` + GPG 密钥（见 `scripts/setup-gopass.ps1`） |
| Proton Pass | [设置 → 访问令牌](https://pass.proton.me/)（需 **Pass Plus**） |

**`.env` 示例：**

```env
BW_CLIENTID=user.xxx
BW_CLIENTSECRET=xxx
BW_PASSWORD=your_master_password
KEEPASSXC_DATABASE=C:\Users\you\OneDrive\Passwords\vault.kdbx
KEEPASSXC_PASSWORD=kdbx_master_password
GOPASS_PATH_PREFIX=vault
PROTON_PASS_PERSONAL_ACCESS_TOKEN=
```

配置完成后：`.\vault.cmd sync` 或 `.\launch-desktop.ps1`。

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
- **API 密钥**（OAuth client_id / client_secret）：**设置 → 安全 → API 密钥**，用于填 `.env` 的 `BW_CLIENTID` / `BW_CLIENTSECRET`。
- `scope`、`grant_type` 由 Bitwarden 固定，**不用写进 `.env`**；还需本机填 `BW_PASSWORD`（登录主密码）。

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

**v1.0.4** — 当前版，包含：

- 本地加密库 + CLI（`vault.cmd`）+ Tauri 桌面（中英切换）
- **PyInstaller API sidecar** 打进安装包（`scripts/build-desktop-release.ps1`）
- 外部源：Bitwarden、KeePassXC、gopass、Proton Pass（Plus）
- 双向同步、冲突持久化、主数据源、`enabled_sources`
- 安全加固：loopback 绑定、unlock-keyring / generate 鉴权、冲突密码脱敏、剪贴板自动清空
- 同步正确性：无时间戳外源不再覆盖 dirty 本地；部分 push / 删除失败不误标干净
- 桌面端不再复用固定端口服务；每次启动均由 Tauri 拥有随机 loopback 端口的 sidecar
- 每个 API 请求均需携带本次启动生成的 bootstrap secret，Tauri 同时验证实例 ID
- Bearer Session Token 仅保存在渲染进程内存中；Windows 进程树随桌面应用一同退出

v1.0.4 不迁移或改写现有加密保险库格式。

GitHub: https://github.com/PureSaber/vault-unified
