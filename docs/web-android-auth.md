# 本地网页 Android 授权

运行 `start-web-auth.bat` 后会打开 `http://127.0.0.1:17891/`。

网页只负责导入已经授权的 Android 会话 JSON。会话由本机协议服务校验后使用 Windows DPAPI 加密保存，网页不会接收 QQ 密码，也不会提供伪造 Android signer 或绕过登录的功能。

协议服务启动后，网页的状态面板会显示账号、会话状态和 signer 状态。只有服务显示 `session_state=online` 且 `signer=已配置` 时，纯电脑端才具备进行 QQ 宠物协议调用的前置条件。

此功能使用独立的 `profiles/standalone/` 版本和本机端口，不修改旧版 MuMu 配置。
