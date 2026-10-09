# Threat Model

## 受保护资产

系统希望判断“当前提交的位置是否具有足够可信度”，而不是证明某个坐标绝对真实。

## 实验覆盖

- Android Mock Location；
- Android 模拟器；
- Root 环境；
- 运行时 Hook/注入风险；
- GPS 与网络地理信号显著冲突；
- 极端跳点与不合理速度；
- 设备静止但坐标高速变化；
- 完整性信号失败。

## 非目标

本项目不提供：

- 隐藏 Mock Location 的 Hook；
- 修改第三方应用 API 返回值；
- framework.jar / LocationManagerService 清除 Mock 标记；
- Anti-Frida / Anti-Xposed 绕过；
- 对真实签到、金融、配送系统的规避方案。

## 误报控制

IP Geo、Wi-Fi、Cell 与 GPS 都可能出现合法偏差，因此这些信号不能单独作为封禁依据。

推荐策略：

- 低风险：直接通过；
- 中风险：提高采样频率或要求二次验证；
- 高风险：进入人工/额外验证；
- 极高风险：仅对位置敏感操作暂时拒绝，并保留申诉路径。
