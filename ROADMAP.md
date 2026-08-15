# QQ Pet Interface Copilot — Roadmap / 路线图

> Updated: 2026-08-15

## 下一版本研究方向：ICQQ 后端

当前版本继续以 Android 手机 QQ 协议作为已验证链路。下一版本将把 **ICQQ 作为重点研究方向之一**，探索在不依赖 MuMu 模拟器长期在线的情况下，直接复用 ICQQ 的登录会话、SSO、签名能力与底层封包通道，向 QQ 宠物 OIDB 接口发送请求。

计划优先验证以下内容：

- ICQQ 登录态、设备参数与会话持久化是否能够满足 QQ 宠物接口要求；
- 当前 `OidbSvcTrpcTcp.*` 宠物命令能否通过 ICQQ 的底层发送通道稳定收发；
- ICQQ 与本地 QSign / Sign Provider 的兼容方式；
- 现有 Python 宠物协议层能否通过独立 `ICQQTransport` / `icqq-bridge` 复用，而不重写已经验证的 protobuf、任务调度和宠物业务逻辑；
- 手机协议与 ICQQ 两种后端的结果一致性，以及登录、签名、AppID/规则类型变化时的容错策略。

现阶段该方案属于 **研究计划，不代表已经可用或已经替代手机协议**。项目会先从只读接口开始验证，例如宠物身份、状态和目录读取；只有在只读链路稳定后，才会逐步测试喂食、洗澡、学习、打工、冒险和 PK 等写操作。

### 致谢

特别感谢用户 **QQ云** 提出 ICQQ 方向的建议。该方案为项目从“依赖模拟器中的官方 Android QQ”进一步探索“独立 QQ 协议后端”提供了新的技术路线，后续版本会围绕这一方向开展验证。

---

## 关于后续源码公开与发行方式的重要说明

项目维护过程中已经发现，闲鱼等平台存在未经授权搬运、复制、重新打包本项目成果并收费转售的情况。部分内容甚至直接使用本项目公开代码、界面或研究成果进行二次售卖，但没有保留项目来源、贡献说明或原始开发信息。

这类行为已经明显增加维护成本，也削弱了继续完整公开所有实现细节的意愿。

因此，从后续版本开始，**QQ Pet Interface Copilot 将大幅收紧源码公开范围**。未来发行计划将逐步调整为：

- GitHub 继续保留项目介绍、更新日志、协议研究结论、必要文档和部分可公开组件；
- 核心自动化逻辑、关键接口适配、后续协议兼容实现及部分新功能将不再默认完整公开；
- 在许可证允许且相关代码具备独立重新许可条件的前提下，后续版本将主要提供经过保护/加固的 Windows EXE 发行包，而不是同步公开全部实现源码；
- 项目会进一步减少可被直接复制、改名后重新售卖的完整成品代码；
- 项目仍然坚持免费研究与个人使用定位，不支持任何第三方以本项目名义收费倒卖。

### 关于现有 GPL-3.0 历史代码

当前仓库已经以 **GNU GPL-3.0** 发布的历史版本不会因为未来发行策略变化而被追溯性“收回”授权。已经按照 GPL-3.0 获得的代码仍然受对应版本许可证约束。

未来项目如果继续分发包含或衍生自 GPL-3.0 覆盖代码的二进制文件，也会遵守相应的源码提供义务。计划中的闭源/加密 EXE 策略主要适用于后续重新设计、重写，且维护者拥有完整许可权、第三方依赖许可证也允许闭源发行的新增组件。

换言之，项目的方向是 **从未来版本开始显著减少新增核心实现的公开范围**，而不是试图撤销已经公开版本所授予的权利。

---

## English Summary

The next version will investigate **ICQQ as an alternative QQ protocol backend**, with a focus on session reuse, SSO/raw OIDB transport, signing integration, and compatibility with the existing QQ Pet protocol layer. Special thanks to **QQ云** for proposing this direction.

Due to repeated unauthorized copying, repackaging and paid resale of this project on second-hand marketplaces such as Xianyu, future development will substantially reduce the amount of newly developed core source code published publicly. Where licensing permits, future releases are expected to focus on protected Windows executable distributions while keeping public documentation, research results and selected components on GitHub.

Previously released GPL-3.0 code remains governed by GPL-3.0. Any future binary distribution that still contains GPL-covered code will continue to comply with the corresponding source requirements; closed-source distribution will be limited to newly written or separately licensable components where the applicable licenses allow it.
