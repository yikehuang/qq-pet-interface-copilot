# TCP 模块重写说明

`鱼刺私用户TCP客户端.ec` 这类模块，本质上是一个 HPSocket 风格的 TCP 客户端壳：

- `Connect` / `Disconnect`
- `Send` / `SendText` / `SendPart` / `SendPackets`
- `OnConnect` / `OnReceive` / `OnClose`
- 异步连接与后台接收线程

它不是 QQ 协议本身，只是负责把 socket 连接、线程、回调和分包收包包起来。

## 你现在可以直接用的 Python 版本

新增实现：`qqpet_app/tcp_client.py`

如果你想要更像原来易语言的写法，也可以直接用 `HPSocketAgentCompat`。

核心调用方式：

```python
from qqpet_app.tcp_client import HPSocketAgentCompat, LengthPrefixedFramer

client = HPSocketAgentCompat("127.0.0.1", 12345, framer=LengthPrefixedFramer())
client.OnConnect = lambda c: print("connected")
client.OnReceive = lambda c, data: print("recv", data)
client.OnClose = lambda c, reason: print("closed", reason)
client.Connect()
client.SendText("hello")
client.SendPacket(b"binary payload")
client.Disconnect()
```

## 和原模块的对应关系

| 原易语言调用 | Python 重写 |
| --- | --- |
| `Connect` | `connect()` |
| `Disconnect` | `disconnect()` / `close()` |
| `Send` | `send()` |
| `SendText` | `send_text()` |
| `SendPart` | `send_part()` |
| `SendPackets` | `send_packets()` |
| `OnConnect` | `on_connect` |
| `OnReceive` | `on_receive` |
| `OnClose` | `on_close` |

## 重要边界

我能帮你重写的是“TCP 客户端能力”和“调用形态”。
如果你要的是原易语言模块里某个 QQ 专用协议的封包规则，那部分还得再单独按业务协议接着拆。
