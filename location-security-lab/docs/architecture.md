# Architecture

## 1. 目标

项目把位置可信度问题拆成三层：

1. 客户端采集：位置、网络环境、设备完整性与传感器摘要。
2. 服务端特征：计算跨来源一致性与时间序列特征。
3. 风险引擎：依据多个独立证据给出可解释风险分数。

## 2. 数据流

```text
Android / MuMu lab client
        |
        | signed request
        v
API ingress
        |
        +---- server-observed IP / geo
        |
        v
Feature extraction
  |     |      |
  |     |      +-- device / integrity
  |     +--------- network consistency
  +--------------- trajectory / sensors
        |
        v
Risk engine
        |
        +-- score
        +-- level
        +-- findings
        +-- metrics
```

## 3. 为什么不依赖单一 Mock 标记

`Location.isMock()` 对开发测试很有价值，但单一客户端布尔值不适合作为高价值决策的唯一依据。客户端数据可能被修改，合法开发设备也可能开启 Mock Location。

系统因此采用多源证据融合：

- 服务端可独立观察的 IP 信号；
- Android 完整性/环境信号；
- Wi-Fi 和蜂窝区域一致性摘要；
- 连续轨迹速度；
- 传感器运动与位移的一致性。

## 4. 权重原则

权重不是概率。第一版权重只服务于比赛演示。

正式版本需要：

- 用标注数据拟合或校准；
- 分设备、网络、国家/地区测误报；
- 单独分析 VPN、校园网、运营商 NAT；
- 使用 ROC、PR 曲线与成本函数选择阈值；
- 保留人工复核或二次验证路径。
