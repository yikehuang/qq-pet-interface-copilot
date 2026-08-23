# ICQQ 接口参考

本目录只服务于 ICQQ 实验链路，不属于 MUMU 或纯电脑 Acidify 链路。

## 当前已验证的版本

| 项目 | 值 | 状态 |
| --- | --- | --- |
| ICQQ npm 包 | 0.6.10 | 旧实现，公开源码主要停留在 2024 年 |
| 扫码平台 | Watch | ICQQ 文档明确支持扫码 |
| Watch 版本 | 2.1.7 | 仅供实验，不代表最新 QQ 客户端 |
| 本地 signer | Android 8.9.63 | 不能视为 iPad signer |
| 本地地址 | `http://127.0.0.1:8081/` | 仅本机监听 |

## signer 请求格式

ICQQ 通过 `sign_api_addr` 拼接以下路径。请求体使用
`application/x-www-form-urlencoded`。

| 路径 | HTTP 方法 | 字段 |
| --- | --- | --- |
| `/` | GET | 无；成功时可返回协议版本信息 |
| `/energy` | GET | `ver`, `uin`, `data`, `android_id`, `qimei36`, `guid`, `version` |
| `/sign` | POST | `qua`, `uin`, `cmd`, `seq`, `android_id`, `qimei36`, `guid`, `buffer` |
| `/request_token` | GET | `uin`, `android_id`, `qimei36`, `guid` |
| `/register` | GET | `uin`, `android_id`, `qimei36`, `guid` |
| `/submit` | GET | `ver`, `qua`, `uin`, `cmd`, `callback_id`, `buffer`, `guid` |

## 返回格式

成功通常是 `code: 0`：

```json
{
  "code": 0,
  "data": {
    "sign": "hex-string",
    "token": "hex-string",
    "extra": "hex-string",
    "ssoPacketList": []
  }
}
```

`/energy` 的 `data` 也可能直接是十六进制字符串，或者放在
`data.sign` 中。异步回调兼容 `ssoPacketList` 和 `requestCallback` 两种字段名。

## 当前故障的判断方式

- `ECONNREFUSED`: signer 没有监听，或端口不是 `8081`。
- `/energy` 返回 `405`: 客户端和 signer 对该路径使用了不同 HTTP 方法，属于接口版本不匹配。
- `Parameter 'phone' is missing`: signer 进程在运行，但它要求额外字段；不能通过随意改字段名解决版本或签名问题。
- QQ 错误码 `45`: QQ 服务端拒绝当前协议/版本组合；修好本地 HTTP 通信后仍可能出现。

## 来源

- [ICQQ 公开镜像](https://github.com/wuliya336/icqq)
- [ICQQ qsign 源码](https://github.com/wuliya336/icqq/blob/1343184a5a4885aea37d934340fe609b9700bc4f/src/core/qsign.ts)
- [ICQQ README](https://github.com/wuliya336/icqq/blob/1343184a5a4885aea37d934340fe609b9700bc4f/README.md)

公开源码不是 QQ 官方客户端或官方 signer。不要把 Android 8.9.63 signer 用于 iPad，也不要把它接入其他协议链路。
