# Acidify Android protocol bridge

这是 2.0 纯电脑后端的下一代实验桥，固定使用 GPL-3.0-only 的
`@acidify/core` 1.6.3 和 Android Phone 9.2.80。它只接受已授权 Android 会话，
不提供 QQ 密码登录，也不会把密码写入文件。

助手首次启用时会从 Node.js 官方源安装固定版本 v22.23.2，并用项目内置 SHA-256
校验压缩包；随后严格按 `package-lock.json` 安装 Acidify 1.6.3。运行组件保存在
当前 Windows 用户的 `%LOCALAPPDATA%\QQPetInterfaceCopilot\runtime`，无需 MuMu、ADB
或 Root。

当前完成：

- Android 会话恢复；
- 原始 SSO/OIDB 收发；
- 好友列表读取；
- 可选的运行时 Android Sign Provider 地址；
- OIDB 业务体封装与服务器错误解析。

签名地址只允许通过启动参数或环境变量注入，不应写入公开配置。没有签名服务时，
桥会尝试无签名的只读请求；若服务器要求 QSec，会明确返回失败，不会伪造成功。
本组件不包含签名器，也不会自动下载已被作者标记为高封号风险的第三方签名器。

开发环境：

```powershell
pnpm install --frozen-lockfile
pnpm test
```

此目录尚未作为默认 Release 后端。必须先完成本机 DPAPI 会话导入和真实
`OidbSvcTrpcTcp.0x95e1_0` 只读验证。
