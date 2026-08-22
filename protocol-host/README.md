# QQPetProtocolHost

QQ 宠物助手 2.0 的纯电脑 Android QQ 会话服务实验。服务只监听回环地址，不接收
或保存 QQ 密码；快速登录令牌和设备信息使用 Windows DPAPI 加密。

协议主机通过 MiraiGo 的 Android SSO 会话发送项目已确认的宠物 OIDB 指令。版本
描述必须与本机 qsign 运行时完全一致；可用 `--protocol-json` 指定经过核验的
`android_phone.json`。MiraiGo 使用 AGPL-3.0，本目录及编译后的协议主机按
AGPL-3.0 分发。

运行：

```powershell
$env:QQPET_QSIGN_URL = "http://127.0.0.1:8080"
.\QQPetProtocolHost.exe
```

切换协议描述的示例：

```powershell
.\QQPetProtocolHost.exe --qsign-url http://127.0.0.1:8080 `
  --protocol-json C:\path\to\android_phone.json
```

签名服务必须与所选 Android QQ 协议匹配。签名服务缺失时仍可启动健康检查，
但不会假装登录成功。默认监听 `127.0.0.1:17890`，拒绝局域网和公网访问。

协议主机默认禁止所有写操作。只有只读验证完成后，用户显式添加
`--enable-writes` 才会开放助手和主机双方白名单中重合的写指令。

首次验证只允许调用 `OidbSvcTrpcTcp.0x95e1_0` 读取自身宠物状态。确认 AppID 与
服务器规则兼容后，才逐项启用其他只读请求和单次写操作。

## 当前验证状态

- 回环限制、Windows DPAPI 会话仓库、OIDB 白名单、版本描述加载和离线构建均已验证。
- Android Phone 8.9.63 与 8.9.90 均能启动对应的本机签名服务。
- 2026-08-22 的真实二维码探测中，QQ 登录服务器对两套版本都返回
  `wtlogin.trans_emp sub cmd 0x31 error: 1`，因此尚未取得在线会话，也尚未执行
  `0x95e1_0` 只读宠物请求。
- 默认关闭已经确认失效的 MiraiGo 二维码入口，并通过 `/v1/health` 的
  `login_capabilities.qr=false` 告知前端停止扫码循环。`--enable-legacy-qr` 只用于
  协议研究，不应提供给普通用户。

在二维码登录得到真实在线结果前，此组件属于实验性后端，不应替换当前可用版本，
更不能将健康检查成功描述为“QQ 已登录”或“宠物接口已可用”。
