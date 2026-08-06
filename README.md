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

## 外部源配置（`.env`）

```env
PROTON_PASS_PERSONAL_ACCESS_TOKEN=pst_...
PROTON_PASS_SHARE_ID=...
BW_CLIENTID=user.xxx
BW_CLIENTSECRET=xxx
BW_PASSWORD=your_master_password
```

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
