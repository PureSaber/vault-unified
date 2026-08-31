# Vault Unified v1.3 功能冻结契约

本冻结从 v1.2.0 基线 `48442fb6ef6e5a9a34887f0115a3713f910cdb12` 开始，持续到 v1.3.0 的全部可靠性、可用性、安装包和人工验收门槛通过。总跟踪见 [GitHub issue #30](https://github.com/PureSaber/vault-unified/issues/30)。

## 冻结目的

v1.3.0 是功能冻结后的产品化与可靠性改造，不是扩展产品边界的版本。实现必须采用纵向小步 PR，保留现有 Vault Format v3、认证 sidecar、同步账本、备份和发布流程的安全价值，不进行前端整体重写。

## 禁止事项

冻结期间不得：

1. 新增密码管理器来源；
2. 新增条目类型；
3. 新增移动端协议；
4. 新增局域网 API；
5. 新增共享保险库、团队、组织或多人协作；
6. 新增遥测、分析 SDK、崩溃上传或用户追踪；
7. 扩大浏览器扩展权限；
8. 为易用性削弱同步预览、删除确认、加密或认证边界；
9. 对现有保险库执行隐式、不可逆迁移；
10. 顺便重写无关后端、密码学模块或适配器。

## 不可破坏的数据与安全边界

- 只使用每次运行动态生成的虚假凭据和隔离目录；不得读取、请求或使用真实保险库、主密码、token、恢复码或外部账号。
- 密码、TOTP 密钥、恢复码、附件内容、bearer/browser/bootstrap token 不得进入日志、exception、PR 文本、截图、trace、CI artifact、receipt 或同步 preview metadata。
- bearer token、browser token 和 bootstrap secret 不得写入持久化浏览器存储。
- 不降低 v3 KDF、AEAD、设备安全存储、认证 sidecar 或原子写入保证。
- 格式变化只能是 additive、optional、namespaced、具备默认值，并附向后兼容与无提示丢失回归测试。
- 批量、删除、覆盖和恢复必须先只读预览，再明确确认；执行绑定当前 session 和数据 digest/generation；状态变化后拒绝旧预览；重试不得重复执行。
- 取消必须等于零持久化；保存失败不得留下未说明的部分状态。该保证必须由后端原子提交边界实现，不能只靠 React 调用顺序。
- 自动锁定是安全边界。未保存表单可以获得一次明显倒计时警告，但不得永久阻止锁定，也不得把明文草稿写入 localStorage、sessionStorage 或普通临时文件。

## PR 约束

- 所有修改从已 fetch 的 `origin/main` 创建独立分支，经 PR 合并；禁止直接推送或 force-push `main`。
- 每个 PR 目的单一、规模可审查、可独立回滚；依赖 PR 合并前不得启动下一阶段，stacked PR 必须明确 base。
- 每个修复 PR 同时添加对应回归测试，不把验证全部推迟到 PR 8。
- 每个 PR 必须填写 Summary、User-visible behavior、Threat/data-integrity scope、Tests、适用的截图/录像、Remaining risks 和 Rollback instructions。
- 合并前必须自审 diff、运行相应回归与必要全量测试、扫描秘密并更新 issue #30；不得隐藏错误或放宽断言来获得绿色 CI。

## 人工验收

Playwright、axe、截图、响应式检查和模拟任务不能代替真实新手研究。以下 gate 只能由仓库所有者在查看真实测试结果后勾选，自动化或 Codex 不得代勾：

- [ ] Repository owner reviewed real novice usability results

在该项和其他发布门槛全部通过前，不得声称“已证明普通用户可用”，也不得创建正式 v1.3.0 tag。
