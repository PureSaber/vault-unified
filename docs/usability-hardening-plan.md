# Vault Unified v1.3 可用性与数据完整性加固计划

## 基线与结论

2026-08-31 已完成 `git fetch --prune origin`。审计基线为 `origin/main@48442fb6ef6e5a9a34887f0115a3713f910cdb12`（v1.2.0），本地 `main` 与远端一致，开始时工作区干净，GitHub 没有开放 PR。完整审计、风险和状态清单维护在 [issue #30](https://github.com/PureSaber/vault-unified/issues/30)。

当前安全底座有保留价值：v3 加密、设备安全存储、loopback authenticated sidecar、仅内存 session、同步账本、一次性同步预览、原子文件替换、加密备份和安装包复验均已存在。本轮不整体重写前端或密码学/适配器层，而是以小型纵向 PR 完成用户闭环。

## 已确认的主要缺口

- 条目字段、附件增加、附件删除和历史恢复跨多个 API/写入边界，当前取消与失败不能提供完整事务语义。
- 导入只有直接应用，没有只读预览、确定性去重、digest/generation 绑定、秘密安全 receipt 和整批撤销。
- 同步预览只给汇总数量，没有逐条操作、字段变化和准确删除端。
- 永久导航暴露添加、同步、冲突，设置聚合过多技术配置，正常列表显示内部来源与同步状态。
- 缺少 Playwright renderer 旅程、axe、窄窗口/缩放/键盘覆盖和失败产物秘密扫描。
- 浏览器扩展不是 release asset；治理、隐私和新手研究文档不完整。

## 测试分层

### A. Renderer E2E

Playwright 访问真实 Vite renderer，通过隔离的 mock authenticated sidecar 覆盖真实按钮、表单、前端路由和请求边界。每次测试动态生成虚假密码与 token。失败截图和 trace 在上传前逐文件（含 ZIP 内容）扫描；命中本次测试凭据的文件从可上传集合删除。

这层测试不读取真实用户数据，也不声称验证了 Tauri 生命周期、Windows Credential Manager 或真实安装行为。

### B. Packaged Windows smoke

现有 sidecar、NSIS、MSI 构建与验证继续独立运行。后续在安装版上增加生成数据核心路径，明确验证 install / launch / use / stop / uninstall。Playwright 结果不能替代这一层。

### C. 真实新手研究

自动化只能发现可重复的交互和可访问性问题，不能证明首次使用是否可理解。PR 9 提供任务脚本和记录模板；正式发布仍由仓库所有者审阅真实新手结果。

## PR 顺序

1. **PR 0 — UI journey foundation**：Playwright、axe、隔离 mock API、CI job、失败产物扫描、冻结契约与 PR 模板；不改业务行为。
2. **PR 1 — Transactional entry editor**：original snapshot + draft、稳定 client ID、未保存保护和一个后端原子提交边界，覆盖字段/附件/历史；取消零写入。
3. **PR 2 — Import preview and undo**：只读预览、确定性去重、原子应用、秘密安全 receipt、导入前加密备份和受 digest/generation 保护的整批撤销。
4. **PR 3 — Item-level sync preview**：秘密安全的逐条 operation、删除端/字段变化、明确破坏性确认、旧预览拒绝和执行集合一致性。
5. **PR 4 — Beginner-first navigation**：密码、安全与恢复、连接、设置、立即锁定；冲突和异常仅上下文出现，补 IA 与术语文档。
6. **PR 5 — Progressive entry editor**：基础字段优先、高级字段渐进展示、标签编辑、安全备注专用表单、原生选择器、响应式与键盘改进。
7. **PR 6 — Security & recovery center**：状态结论优先，整合自动锁定、备份、验证、恢复、历史和恢复包，持久显示失败并提供安全重试。
8. **PR 7 — Browser extension release package**：确定性 ZIP、版本/权限 contract、manifest 哈希、release 上传/复验、配对体验和扩展行为测试；不增加权限。
9. **PR 8 — Full journey coverage**：记录规模、语言、视口、缩放、键盘、强制颜色、长内容、竞态/故障、axe、DOM、console、焦点和秘密扫描矩阵。
10. **PR 9 — Open-source governance**：MIT、SECURITY、CONTRIBUTING、行为准则、issue forms、隐私边界、新手 README、真实研究材料和发布检查表。

每个 PR 只在依赖 PR 合并或明确建立 stacked base 后开始；前一阶段 CI 未全绿时不进入下一阶段。

## 发布门槛

发布前必须通过 Python 全量与依赖审计、TypeScript、Vite、Playwright/axe、Rust/RustSec、packaged sidecar、NSIS/MSI 生命周期、扩展 ZIP/权限、release manifest、独立下载复验和秘密扫描；没有开放 P0/P1 数据完整性问题。资产应为 EXE、MSI、Browser Extension ZIP 和 release manifest。

以下 gate 保持人工、默认未完成：

- [ ] Repository owner reviewed real novice usability results

所有 gate 完成前不创建正式 tag；已发布资产不可替换，发现问题后以新版本修复。
