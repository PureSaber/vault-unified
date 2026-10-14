# v1.4.0 个人版交付记录

七阶段、20 项功能的实现已合入 `main`。本次交付 Windows EXE／MSI、匹配的
Chrome／Edge 扩展和可部署的分享服务；普通本地使用无需云账号。
源码提交：`6c8846fc655526fe00a048ed2f850494538be9ef`（PR #82）。

## 交付文件

- `Vault-Unified-Personal-v1.4.0-Windows-x64.zip`：完整套件，含安装包、签名、扩展、服务和简短说明。
- `Vault-Unified-Browser-Extension-v1.4.0.zip`：覆盖原扩展目录后重新加载；新用户按说明加载。
- `Vault-Unified-Sharing-Service-v1.4.0.zip`：Python 和 Docker Compose 部署。
- EXE／MSI、各自 `.sig`、`latest.json` 及完成安装验证的发布清单单独提供。

安装和换机见 [开始使用](personal-edition-start.md)，完整能力见
[个人版指南](personal-edition.md)，操作核对见 [简短验收清单](personal-edition-acceptance.md)。

## 验证记录

| 验证层次 | 结果与证据 |
|---|---|
| 完整源码检查 | [CI 38571419009](https://github.com/PureSaber/vault-unified/actions/runs/38571419009)：592 项 Python、90 项界面流程、Rust、依赖和秘密扫描通过 |
| 原生 Windows | 同轮 CI 通过快捷搜索、托盘、单实例、自动输入、页面重载会话清理、锁屏／休眠通知与退出清理 |
| 实际安装 | [Personal delivery 38571419013](https://github.com/PureSaber/vault-unified/actions/runs/38571419013)：EXE／MSI 从公开 v1.3.0 升级，保留数据与备份，验证迁移取消、重装／修复及卸载清理 |
| 安装版浏览器 | 同轮安装验证通过 Chrome／Edge 保存、填充、改密、TOTP、Passkey 创建／登录／取消、重启重连和撤销 |
| 服务部署包 | [Sharing service 38571418946](https://github.com/PureSaber/vault-unified/actions/runs/38571418946)：实际解压服务 ZIP、Compose 构建与 HTTP 加密分享／权限验证通过 |
| 同步与恢复 | 两套隔离配置已验证文件夹／WebDAV、离线合并、同字段／删除冲突、重试和完整加密恢复；各阶段证据见 [开发记录](product-expansion-plan.md) |
| 生产签名文件 | 两种安装格式已通过真实 Tauri 下载与签名／版本校验；[下载验证 38575607343](https://github.com/PureSaber/vault-unified/actions/runs/38575607343)记录从公开预发布页重新下载这些文件的安装流程，最终文件结果见随附发布清单 |

安装流程只在一次性 CI Windows 环境中运行；本机检查使用生成的隔离数据。
正式交付清单记录每个文件的版本、大小、摘要和安装验证结果，复用既有发布清单格式。

## 本人验收与发布状态

- Windows Hello 的指纹／人脸／PIN 确认，以及本人设备的实际锁屏／休眠仍需按验收清单操作。
- 自动化结果不代替真实新用户可用性访谈；对应人工确认项保持未勾选。
- [v1.4.0 安装套件](https://github.com/PureSaber/vault-unified/releases/tag/v1.4.0)作为公开预发布候选版交付；当前稳定最新版仍为 v1.3.0。候选版不进入稳定版自动更新通道。
- 更新检查和其他联网功能默认关闭。候选版需从发布页手动下载；后续提升为稳定版时，配套 `latest.json` 与签名安装包一起进入更新通道。
- 发布签名私钥保存在本机受限目录，并已配置到仓库加密 Actions secret，未进入 Git 或交付 ZIP。

商业 Authenticode 签名、扩展商店上架、手机应用、外部 Passkey 格式转换及公网服务部署不在本轮范围。
