# Location Security Lab / 虚拟定位安全实验室

面向学校授权比赛与本地研究环境的位置可信度评估项目。项目把多种虚拟定位检测思路整合为统一的服务端风险评分流程，而不是依赖单个 `Location.isMock()` 结果。

## 当前能力

- 多源位置一致性：GPS、服务端观测 IP 地理位置、Wi-Fi/基站一致性信号。
- 设备环境：Mock Location、模拟器、Root、Hook/注入风险、Play Integrity 风格的完整性信号。
- 行为轨迹：相邻点距离、速度、时间间隔、传感器静止与高速位移冲突。
- 风险评分：输出 0-100 分、风险等级、命中原因和证据。
- 实验场景：正常移动、Mock Location、模拟器、跨城市瞬移、传感器冲突。
- FastAPI 接口与 pytest 单元测试。

## 安全边界

本项目用于授权测试、课程比赛和防御研究。它不包含隐藏 Mock 标志、绕过第三方应用完整性校验、修改 framework.jar、Anti-Frida 绕过或签到欺骗代码。

## 目录

```text
location-security-lab/
├─ location_security/
│  ├─ __init__.py
│  ├─ schemas.py
│  ├─ trajectory.py
│  ├─ risk_engine.py
│  └─ app.py
├─ lab/
│  └─ generate_scenarios.py
├─ tests/
│  └─ test_risk_engine.py
├─ docs/
│  ├─ architecture.md
│  └─ threat-model.md
├─ examples/
│  └─ suspicious_request.json
└─ pyproject.toml
```

## 快速启动

Python 3.11+：

```bash
cd location-security-lab
python -m venv .venv
# Windows:
.venv\Scripts\activate
python -m pip install -e ".[dev]"
uvicorn location_security.app:app --host 127.0.0.1 --port 8010 --reload
```

打开：

- `http://127.0.0.1:8010/health`
- `http://127.0.0.1:8010/docs`

运行测试：

```bash
pytest -q
```

生成实验请求：

```bash
python lab/generate_scenarios.py
```

## 风险评分思路

系统不会因为单一异常直接认定作弊。每类证据贡献不同权重：

| 信号 | 示例权重 |
|---|---:|
| Mock Location | +25 |
| 模拟器 | +20 |
| Root | +15 |
| Hook/注入风险 | +25 |
| 设备完整性失败 | +30 |
| GPS 与 IP 相距极远 | +5~15 |
| Wi-Fi/基站与声称区域冲突 | +10~15 |
| 不合理高速移动 | +10~35 |
| 传感器静止但位置高速变化 | +25 |

最终分数截断为 0-100：

- 0-29：low
- 30-59：medium
- 60-79：high
- 80-100：critical

这些阈值仅用于比赛演示，正式系统需要真实数据校准误报率、召回率和不同网络环境下的偏差。
