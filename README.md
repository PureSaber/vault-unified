# Vault Unified

本地加密密码库，并可选接入 **Proton Pass** 与 **Bitwarden**。

## 一键使用（推荐）

**第一次：**

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

脚本会自动：安装依赖 → 创建 `.env` → 运行初始化向导 → 导入 `token.txt`（如有）

**以后每次：**

```powershell
.\vault.cmd
```

或直接双击 `vault.cmd`，会打开交互菜单，无需再输入主密码（已保存到 Windows 凭据管理器）。

```
[1] List  [2] Search  [3] Add  [4] Get  [5] Sync  [6] Status  [0] Exit
```

## 架构

```
┌─────────────────────────────────────────────┐
│              vault CLI (统一入口)              │
└─────────────────────┬───────────────────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
   Local Vault   Proton Pass   Bitwarden
  (AES-GCM 加密)   (pass-cli)      (bw CLI)
```

- **本地存储（主库）**：使用 Scrypt + AES-GCM 加密，数据保存在 `.vault/secrets.vault`
- **Proton Pass**：通过官方 `pass-cli` 拉取条目（需 Personal Access Token）
- **Bitwarden**：通过官方 `bw` CLI 拉取条目（需 API Key + 主密码解锁）

导入时按 `source + external_id` 去重，重复同步会更新已有记录。

## 快速开始（手动）

若不想用一键脚本，也可手动安装：

```powershell
cd C:\develop\token&password
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

### 2. 初始化本地保险库

```powershell
vault init
```

### 3. 添加密码

```powershell
vault add --title "GitHub" --username "me@example.com"
```

### 4. 查看与搜索

```powershell
vault list
vault search github
vault get "GitHub" --show-password
```

## 外部源配置

复制 `.env.example` 为 `.env` 并填写（**不要提交 `.env`**）：

```powershell
copy .env.example .env
```

### Proton Pass

1. 安装 [Proton Pass CLI](https://protonpass.github.io/pass-cli/)
2. 在 Proton Pass 中创建 Personal Access Token
3. 设置环境变量：

```powershell
$env:PROTON_PASS_PERSONAL_ACCESS_TOKEN = "pst_..."
vault import proton
```

### Bitwarden

1. 安装 [Bitwarden CLI](https://bitwarden.com/help/cli/)
2. 在 Bitwarden 账户设置中生成 API Key
3. 设置环境变量：

```powershell
$env:BW_CLIENTID = "user.xxxxx"
$env:BW_CLIENTSECRET = "xxxxx"
$env:BW_PASSWORD = "your_master_password"
vault import bitwarden
```

### 一键同步所有可用源

```powershell
vault sync
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `vault` | 打开交互菜单（无参数时） |
| `vault setup` | 首次配置向导 |
| `vault forget` | 清除本机保存的主密码 |
| `vault status` | 查看本地库与外部集成状态 |
| `vault add` | 添加本地条目 |
| `vault list` | 列出条目（密码脱敏） |
| `vault get <title>` | 查看单条 |
| `vault search <query>` | 搜索 |
| `vault delete <id>` | 删除 |
| `vault import proton` | 从 Proton Pass 导入 |
| `vault import bitwarden` | 从 Bitwarden 导入 |
| `vault sync` | 同步所有可用外部源 |

## 安全说明

- `token.txt`、`.vault/`、`.env` 已在 `.gitignore` 中排除，可安全推到 private 仓库
- 主密码仅用于本地解密，不会上传
- Bitwarden / Proton Pass 凭证通过各自官方 CLI 在本地解密，本工具不实现其加密协议
- 自动化场景可设置 `VAULT_PASSWORD` 环境变量（仅限受信环境）

## 环境变量

| 变量 | 说明 |
|------|------|
| `VAULT_PASSWORD` | 本地库主密码（非交互模式） |
| `VAULT_FILE` | 自定义 vault 文件路径 |
| `PROTON_PASS_PERSONAL_ACCESS_TOKEN` | Proton Pass PAT |
| `BW_CLIENTID` / `BW_CLIENTSECRET` | Bitwarden API 凭证 |
| `BW_PASSWORD` | Bitwarden 主密码（解锁用） |

## 迁移现有 token.txt

若你有 `token.txt` 里的 GitHub token，可手动导入：

```powershell
vault add --title "GitHub Token" --username "repo" --password "ghp_..."
```

或保留 `token.txt` 作备份，但**不要**将其提交到 Git。
