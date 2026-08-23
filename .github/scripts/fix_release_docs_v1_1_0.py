from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
THREAT = ROOT / "docs" / "vault-v3-threat-model.md"


def replace_exact(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label}; found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    readme = README.read_text(encoding="utf-8")
    readme = replace_exact(
        readme,
        "# Vault Unified v1.0",
        "# Vault Unified v1.1.0",
        label="README heading",
    )
    readme = replace_exact(
        readme,
        "| 本地加密库 | 兼容 Scrypt + AES-GCM；显式可选 Argon2id + KEK/DEK v3 |",
        "| 本地加密库 | 兼容 legacy Scrypt/AES-GCM；新建桌面库默认 Argon2id + KEK/DEK v3 |",
        label="local-vault overview row",
    )
    readme = replace_exact(
        readme,
        "- `enabled_sources`：勾选参与同步的外源；缺省或 `null` 表示四个外源全部启用；`[]` 表示仅本地库",
        "- `enabled_sources`：缺省或 `[]` 表示仅本地库；显式 `null` 仅为旧配置兼容，表示四个外源全部启用",
        label="enabled_sources documentation",
    )
    readme = replace_exact(
        readme,
        "- `primary=local`：本地修改后自动 push 到**已启用**的外部源",
        "- `primary=local`：只有在 `auto_push_on_edit=true` 且目标源已显式启用时，本地修改后才会自动 push",
        label="auto-push documentation",
    )
    readme = replace_exact(
        readme,
        "`status` 中应显示 `CLI found`；若仍提示 `credentials missing`，继续下一步配置 `.env`。",
        "`status` 中应显示 `CLI found`；若仍提示 `credentials missing`，请在桌面端 Settings → External password-manager connections 中保存并测试凭证。",
        label="status credential guidance",
    )

    start = readme.find("## 外部源配置（`.env`）")
    end = readme.find("## 常见问题（FAQ）")
    if start < 0 or end < 0 or end <= start:
        raise SystemExit("Could not locate the legacy integration-configuration section")
    secure_section = """## 外部源配置（Windows Credential Manager）

推荐在桌面 App **Settings → External password-manager connections** 中配置。敏感值保存在 Windows Credential Manager；数据库路径、服务器地址、Vault 名称等非敏感配置保存在：

```text
%LOCALAPPDATA%\\VaultUnified\\config\\integrations.json
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

"""
    readme = readme[:start] + secure_section + readme[end:]

    readme = replace_exact(
        readme,
        "- **API 密钥**（OAuth client_id / client_secret）：**设置 → 安全 → API 密钥**，用于填 `.env` 的 `BW_CLIENTID` / `BW_CLIENTSECRET`。",
        "- **API 密钥**（OAuth client_id / client_secret）：**设置 → 安全 → API 密钥**，在桌面端 Bitwarden 连接设置中保存。",
        label="Bitwarden API-key FAQ",
    )
    readme = replace_exact(
        readme,
        "- `scope`、`grant_type` 由 Bitwarden 固定，**不用写进 `.env`**；还需本机填 `BW_PASSWORD`（登录主密码）。",
        "- `scope`、`grant_type` 由 Bitwarden 固定，无需配置；主密码也通过桌面连接设置写入 Windows Credential Manager。",
        label="Bitwarden password FAQ",
    )
    readme = replace_exact(
        readme,
        "- 显式 opt-in 的 Vault Format v3：Argon2id、KEK/DEK envelope encryption、密钥轮换和测试向量",
        "- 桌面新库默认 Vault Format v3；CLI 创建、迁移与密钥轮换仍为显式操作",
        label="v3 release bullet",
    )
    readme = replace_exact(
        readme,
        "v1.0.5 保持 legacy v1/v2 为默认格式，不会自动迁移现有保险库。V3 创建、迁移、\n设备解锁和回滚均需显式操作；降级前必须按运行手册恢复兼容备份。",
        "v1.1.0 不会自动改写现有 v1/v2/v3 保险库；新建桌面保险库默认使用 v3，legacy CLI/setup 创建路径继续保持兼容。迁移、设备解锁、密钥轮换和回滚仍需显式操作；降级前必须按运行手册恢复兼容备份。",
        label="v1.1 compatibility paragraph",
    )
    README.write_text(readme, encoding="utf-8", newline="\n")

    threat = THREAT.read_text(encoding="utf-8")
    threat = replace_exact(
        threat,
        "existing vaults are never migrated automatically. No\nimplementation PR may weaken a `MUST` without a new design review.",
        "existing vaults are never migrated automatically. No implementation PR may weaken a `MUST` without a new design review.",
        label="threat-model paragraph wrap",
    )
    THREAT.write_text(threat, encoding="utf-8", newline="\n")

    print("Updated v1.1.0 README and threat-model compatibility guidance")


if __name__ == "__main__":
    main()
