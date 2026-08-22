# dulu 源码协议解析与电脑端适配计划

## 源码结构

`dulu源码.zip` 是易语言工程与易语言模块集合。`dulu.e` / `Pro.e` 里混有界面、资源、字符串和封包常量，不是可直接导入 Python 的源码。可复用价值主要来自协议边界：

| 文件 | 作用 | 可复用方式 |
| --- | --- | --- |
| `dulu.e` / `Pro.e` | 主程序、UI、内嵌资源、接口调用点 | 提取字符串、命令名、行为路径 |
| `protobuf.ec` / `pb.ec` / `newProtobuf.ec` | protobuf 编解码 | 已由 `qqpet_app/proto.py` 等价实现 |
| `zyJson4.1.3.ec` | JSON 解析 | Python 原生 `json` 替代 |
| `miniblink.ec` | WebView/UI 宿主 | 不进入纯电脑协议层 |
| `鱼刺私用户TCP客户端.ec` | TCP 客户端封装 | 只作为网络封装线索，不直接移植 |
| `鱼刺类.多线程6.ec` | 多线程封装 | Python 线程/进程模型替代 |

## 协议封装模型

QQ 宠物请求不是公开 HTTP API。有效链路是：

```text
业务请求 protobuf
  -> OIDB/SSO 命令
  -> QQ 已登录会话封包、签名、加密
  -> QQ 宠物服务器
```

在 Android QQ 内部，已确认入口为 `PetPbDelegate`：

| 入口 | 作用 |
| --- | --- |
| `com.tencent.mobileqq.qqpet.delegate.l.a(data, cmd, observer)` | 发送 SSO/TRPC |
| `com.tencent.mobileqq.qqpet.delegate.l.c(data, oidbName, command, subCommand, observer)` | 发送 OIDB |
| `PetPbDelegate$a.onResult(code, data, bundle)` | 接收回包 |

纯电脑端不能只复制固定封包，必须保留当前账号登录态、签名、动态规则、`petId`、`storyId` 和服务端下发扩展字段。

## 命令表

| 作用 | SSO/TRPC | OIDB | 请求字段要点 |
| --- | --- | --- | --- |
| 获取本人宠物 | `Sso_PetCache_GetUserPet` | `OidbSvcTrpcTcp.0x95e1_0` / 38369 / 0 | 空请求；响应 `pet.field101 = petId` |
| 查询展示值 | `Sso_PetGrowth_GetDisPlayValue` | `OidbSvcTrpcTcp.0x96f2_1` / 38642 / 1 | `petId`、展示值类型 |
| 查询喂食次数/库存 | `Sso_PetFeed_GetFeedTimesInfo` | `OidbSvcTrpcTcp.0x9949_1` / 39241 / 1 | self 查询时 field 4 为空字符串 |
| 喂食 | `Sso_PetFeed_Feeding` | `OidbSvcTrpcTcp.0x992d_1` / 39213 / 1 | 主人信息、`petId`、喂食类型、扩展字段 |
| 购买食物 | `Sso_PetFeed_BuyFood` | `OidbSvcTrpcTcp.0x99df_1` / 39391 / 1 | `count`、`foodId` |
| 查询洗护配置 | `Sso_PetBath_GetItemConfig` | `OidbSvcTrpcTcp.0x9bf1_1` / 39921 / 1 | 道具配置请求 |
| 查询洗护库存 | `Sso_PetBath_GetInventory` | `OidbSvcTrpcTcp.0x9bf2_1` / 39922 / 1 | 道具库存请求 |
| 使用洗护道具 | `Sso_PetBath_DoBath` | `OidbSvcTrpcTcp.0x9bf3_1` / 39923 / 1 | `petId`、道具、目标清洁 |
| 购买洗护道具 | `Sso_PetBath_BuyItem` | `OidbSvcTrpcTcp.0x9bd0_0` / 39888 / 0 | `itemId`、`count` |
| 获取行为规则 | `Sso_PetBehavior_GetPageRules` | `OidbSvcTrpcTcp.0x96a4_1` / 38564 / 1 | 页面、来源、扩展字段 |
| 上报行为 | `Sso_PetBehavior_ReportEvent` | `OidbSvcTrpcTcp.0x96a6_1` / 38566 / 1 | `petId`、路径、执行扩展、上下文 |
| 查询故事状态 | `Sso_PetOutdoor_GetPetStoryStatus` | `OidbSvcTrpcTcp.0x975a_1` / 38746 / 1 | `petId`、查询类型 0 |
| 启动故事 | `Sso_PetOutdoor_DoStoryInfo` | `OidbSvcTrpcTcp.0x975e_1` / 38750 / 1 | 页面、事件、子事件、动态扩展 |
| 结算故事 | `Sso_PetOutdoor_DoAfterStoryInfo` | `OidbSvcTrpcTcp.0x9760_1` / 38752 / 1 | `storyId`、action 1000、`petId` |
| 鼓励宠物 | `Sso_PetEncourage_Encourage` | `OidbSvcTrpcTcp.0x9c44_1` / 40004 / 1 | `storyId`、`petId` |
| 查询好友宠物 | `Sso_PetFriend_GetOtherUserPet` | `OidbSvcTrpcTcp.0x976c_0` / 38764 / 0 | 好友 UIN、`petId` |
| 好友踩踩 | `Sso_PetFriend_Poke` | `OidbSvcTrpcTcp.0x985b_0` / 39003 / 0 | 好友 UIN |
| 查询 PK 好友池 | `Sso_PetPK_GetFriendList` | `OidbSvcTrpcTcp.0x985d_0` / 39005 / 0 | 分页与筛选 |
| 查询战力 | `Sso_PetPK_GetPower` | `OidbSvcTrpcTcp.0x9ad4_1` / 39636 / 1 | `petId` |
| 查询 PK 状态 | `Sso_PetPK_GetStatus` | `OidbSvcTrpcTcp.0x975f_1` / 38751 / 1 | `storyId` |

## 行为路径

| 动作 | page | eventType | subEvent |
| --- | ---: | ---: | ---: |
| 洗澡进度 | 5000 | 500 | 501 |
| 洗澡中断 | 5000 | 500 | 502 |
| 手动擦洗 | 5000 | 500 | 503 |
| 学习：文化 | 6000 | 6100 | 6101 |
| 学习：体能 | 6000 | 6100 | 6201 |
| 学习：艺术 | 6000 | 6100 | 6301 |
| 打工：文化 | 6000 | 6400 | 6401 |
| 打工：体能 | 6000 | 6400 | 6501 |
| 打工：艺术 | 6000 | 6400 | 6601 |
| 冒险 | 6000 | 6700 | 服务器下发 |

## 已落地的适配层

新增 `qqpet_app/protocol_catalog.py` 保存命令表，新增 `qqpet_app/protocol_adapter.py` 作为纯电脑协议适配边界。现阶段适配层只抽出元数据与现有客户端桥接，不改变旧 MuMu 兼容链路。

后续接入顺序：

1. 只读：本人宠物、展示值、故事状态；
2. 动态规则：`GetPageRules` 与课程/岗位/冒险目录；
3. 单次写入：喂食、洗澡；
4. 主任务写入：学习、打工、冒险、结算；
5. 好友与 PK：好友资料、战力、PK 状态和结算。

