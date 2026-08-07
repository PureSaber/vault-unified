# Vault Unified v1.0

本地加密密码库 + **Tauri 桌面应用** + Proton Pass / Bitwarden **双向同步**。

## 功能概览

| 功能 | 说明 |
|------|------|
| 本地加密库 | Scrypt + AES-GCM，`.vault/secrets.vault` |
| 桌面 App | Tauri + React 图形界面 |
| 双向同步 | 拉取 + 推送到 Proton Pass / Bitwarden |
| 主数据源 | 可设 local / proton_pass / bitwarden 为日常权威 |
| 冲突处理 | 弹窗对比，默认偏向主数据源 |
| CLI | `vault.cmd` 命令行仍可用 |

## 快速开始

### CLI（已有用户）

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
.\vault.cmd
```

### 桌面应用

```powershell
# 安装 API 依赖
.venv\Scripts\pip install -e ".[api]"

# 启动 API（调试）
vault-api

# 启动桌面 App（另开终端）
cd apps\desktop
npm install
npm run tauri dev
```

或一键脚本：

```powershell
powershell -ExecutionPolicy Bypass -File apps\desktop\start-desktop.ps1
```

## 同步命令

```powershell
.\vault.cmd sync              # 仅从外部拉取
.\vault.cmd sync -b           # 双向同步（拉取 + 推送 + 冲突检测）
.\vault.cmd push "GitHub"     # 推送单条到云端
.\vault.cmd push --all        # 推送所有 dirty 条目
.\vault.cmd conflicts list    # 查看冲突
.\vault.cmd conflicts resolve <id> --choice local
```

## 主数据源设置

在桌面 App **Settings** 页面或 `.vault/sync_prefs.json`：

```json
{
  "primary": "local",
  "auto_push_on_edit": true,
  "auto_pull_on_sync": true,
  "conflict_default": "primary"
}
```

- `primary=local`：本地修改后自动 push 到 Proton/Bitwarden
- 冲突时 UI 默认选中主数据源，可手动改选

## 外部 CLI 安装（Windows）

与 Proton Pass / Bitwarden 同步需要各自官方 CLI。它们是**系统级工具**，装在电脑上即可，**不需要也不应放进本仓库**。

| 工具 | 用途 | 安装 |
|------|------|------|
| Bitwarden CLI (`bw`) | Bitwarden 导入 / 同步 | `winget install Bitwarden.CLI` |
| Proton Pass CLI (`pass-cli`) | Proton Pass 导入 / 同步 | 见下方 PowerShell 命令 |

**Proton Pass CLI（官方脚本）：**

```powershell
Invoke-WebRequest -Uri https://proton.me/download/pass-cli/install.ps1 -OutFile install.ps1
.\install.ps1
```

若提示脚本无法执行，可用管理员 PowerShell 临时允许：`Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

**验证安装：**

```powershell
bw --version
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
| Proton Pass | [设置 → 访问令牌](https://pass.proton.me/)（需 **Pass Plus**） |
| Bitwarden | [Security → API Key](https://vault.bitwarden.com/#/settings/security/security-keys) + 主密码 |

**`.env` 示例：**

```env
PROTON_PASS_PERSONAL_ACCESS_TOKEN=pst_...
PROTON_PASS_SHARE_ID=...
PROTON_PASS_VAULT_NAME=Personal
BW_CLIENTID=user.xxx
BW_CLIENTSECRET=xxx
BW_PASSWORD=your_master_password
BW_SERVER=https://vault.bitwarden.com
```

配置完成后：`.\vault.cmd sync` 或 `.\launch-desktop.ps1`。

## 常见问题（FAQ）

### Proton Pass：找不到访问令牌 / 提示要升级？

- 正确位置：**设置 → 访问令牌**（API Tokens），不是「安全」。
- **免费版（Proton Free）无法创建访问令牌**；CLI 自动化同步需要 **Proton Pass Plus** 付费套餐。
- 免费用户可：只用本地库、只配 Bitwarden，或在 Proton Pass 网页/App 里手动管理密码。

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

```
Tauri Desktop (React)
       │ HTTP localhost:8765
       ▼
FastAPI ──► UnifiedVault ──► LocalVault (encrypted)
                │
                ├── SyncEngine (bidirectional)
                ├── Proton Pass (pass-cli)
                └── Bitwarden (bw CLI)
```

## 安全

- API 仅绑定 `127.0.0.1`
- `.vault/`、`.env`、`token.txt` 不提交 Git
- 密码 API 响应默认脱敏

## 版本

- v1.0.0 — Tauri GUI + 双向同步
- v0.2.0 — copy / edit / generate
- v0.1.0 — CLI + 单向导入

GitHub: https://github.com/PureSaber/vault-unified
