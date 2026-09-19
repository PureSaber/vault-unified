# Install the browser extension

The browser extension is an optional release download for Chrome and Edge on
the same Windows computer as Vault Unified.

1. Open the latest Vault Unified release and download
   `Vault-Unified-Browser-Extension-v<version>.zip` beside the EXE or MSI.
2. Extract the ZIP. In `chrome://extensions` or `edge://extensions`, enable
   **Developer mode**, choose **Load unpacked**, and select the extracted
   directory containing `manifest.json`.
3. Unlock Vault Unified and open **Connections → Browser extension**.
4. Copy the local address and one-time pairing code into the extension popup
   before the five-minute countdown ends.

The token is session-only. Locking or exiting Vault Unified, cancelling or
regenerating pairing, or waiting for expiry invalidates it. The extension does
not silently fill ambiguous multi-form, change-password, iframe, or Shadow DOM
pages.

## 开发分支新增功能（尚未包含在 v1.3.0 发布包中）

配合相同分支的桌面端，可主动读取当前页面账号或手动录入，核对网站、
用户名和保存目标后确认新增／更新。更新保留历史及其他字段，暂不自动
推送到外部密码服务。中英文可在扩展窗口顶部切换。

注册或改密时，先选择「用独立窗口完成注册／改密」。独立窗口在你操作
网站时保持打开，可以生成并填入标有新密码用途的字段，再回来确认保存。
网站是否接受密码需要你确认；单击网站提交按钮不会自动覆盖保险库。
关闭窗口或检测到锁定、断连、跨站跳转会清除内存草稿。

新建 v3 保险库可选择在两端本次运行期间记住连接：锁定撤销读取和写入
权限，解锁同一保险库后可重新连接，无需再次输入配对码。最多保留
12 小时；任一端重启、重新生成配对码或解除连接后，需要重新配对。
旧格式保险库仍使用原有配对方式。状态检查不会延长自动锁定计时。

这轮复用已有扩展权限、加密格式、原子保存和历史机制；长期设备信任、
重启后的自动发现、后台自动捕获和移动端不属于本次交付。
