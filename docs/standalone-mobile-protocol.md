# 2.0 纯电脑手机协议后端

目标运行链路：

```text
QQ 宠物助手 -> 本机 Android QQ 会话服务 -> QQ SSO/OIDB -> QQ 宠物服务器
```

生产模式不依赖 MuMu、ADB、Frida 或 Hook。现有 Hook 只用于开发阶段确认命令与
protobuf 字段，确认后的业务指令由纯电脑协议服务直接发送。

## 本机服务契约（v1）

服务只能监听回环地址，且必须在 `/v1/health` 明确返回：

```json
{
  "ok": true,
  "protocol_family": "android_qq",
  "session_state": "online",
  "uin": "123456789"
}
```

助手会拒绝 NTQQ、Linux QQ 或无法确认客户端类型的会话，也不会在失败后退回
NapCat/MuMu。OIDB 接口为 `POST /v1/oidb`，请求与响应业务体使用 Base64。
二维码登录使用 `POST /v1/login/qr`，好友列表使用 `GET /v1/friends`。

登录会话不得写进 `config.yaml`。协议核心统一使用 Windows DPAPI 按当前 Windows
用户加密保存，复制到另一台电脑或切换用户后不可解密；用户可以在前端退出登录并
清除该文件。项目不会保存 QQ 密码。

## 迁移状态

- 已完成：调度器后端隔离、Android 会话类型校验、只读/写入命令白名单、本机接口
  契约、配置与设置页面入口。
- 进行中：二维码登录、设备身份、会话密钥、QSec 签名、SSO 长连接、心跳与续期。
- 验证顺序：登录态 -> `0x95e1_0` 只读状态 -> 课程/岗位目录 -> 喂食等单次写入。

在只读状态得到真实服务器响应前，不会把 2.0 标记为可用于主账号，也不会删除
1.5.4 的兼容代码。
