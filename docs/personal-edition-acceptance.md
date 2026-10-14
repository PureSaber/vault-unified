# 安装版简短验收 / Installed acceptance

用专门的新建测试库和虚构账号操作。每项完成后勾选；自动验证证据见仓库开发记录。

- [ ] 安装后创建测试库，添加账号、编辑、退出并重开，内容保留且需重新解锁。
- [ ] 导入一个浏览器 CSV，取消预览不写入；确认后核对字段，重复导入有提示。
- [ ] Chrome 和 Edge 各加载配套扩展：配对、保存、填充、改密；重启重连，撤销后拒绝访问。
- [ ] 开启测试网站建议：分步用户名／密码、验证码、多个账号选择；填充不自动提交。
- [ ] Passkey 在测试站点创建并登录；取消、锁定和撤销授权能中止请求。
- [ ] 收藏、筛选、批量标签、归档、误删恢复、重复合并及历史字段恢复可用。
- [ ] 二维码验证码有倒计时；生成的密码可找回；恢复码可标记已使用。
- [ ] 全局快捷搜索与托盘退出可用。应用自动输入只作用于确认窗口，换焦点立即停止。
- [ ] **本人操作 Windows Hello**：启动先输主密码，再验证指纹／人脸／PIN；取消后可用主密码。
- [ ] **本人锁屏／休眠**：回来后密码库锁定，未保存敏感草稿已清除。
- [ ] 两套独立配置同步：离线编辑恢复后合并；同字段及删除冲突需要选择。
- [ ] 创建迁移包，在隔离恢复演练中核对附件、历史、验证码与 Passkey。
- [ ] 分享链接到期／次数耗尽／撤销后拒绝读取；家庭只读成员不能写，移除后不能取新内容。
- [ ] 从旧版本升级保留测试库；更新检查默认关闭；手动更新失败仍可重开原库。
- [ ] 卸载后浏览器桥接注册消失，原库和备份仍在。

English: check the same flows in both languages where applicable. The two bold
Windows steps require the owner's physical device/session; an automated API or
window message check does not complete biometric or physical-session acceptance.
