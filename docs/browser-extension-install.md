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

新建 v3 保险库可选择长期授权浏览器，并为设备命名。锁定撤销读取和写入
权限；即使重启任一端，解锁同一保险库后也可重新连接，无需新的配对码。
扩展通过不可导出的签名密钥证明设备身份，访问令牌仍只存在会话中，
最多有效 12 小时。桌面端「已授权浏览器」可以查看和撤销设备。
旧格式保险库及取消勾选长期授权时仍使用临时配对。状态检查不延长锁定计时。

配合桌面可执行程序，首次配对会注册 Chrome／Edge Native Messaging。
它只返回正在运行的桌面服务的本机地址及实例标识，使重启后的动态端口
可以自动发现。它不传输保险库或访问令牌，也不会自动解锁桌面。
仅启动 Python API 不会注册该通道。详见[设备授权边界](trusted-browser-connections.md)。
