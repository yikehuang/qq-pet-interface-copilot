from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProtocolSpec:
    key: str
    oidb_name: str
    command: int
    sub_command: int
    sso_name: str
    purpose: str
    request_fields: tuple[str, ...] = ()
    status: str = "verified"


PROTOCOL_SPECS: tuple[ProtocolSpec, ...] = (
    ProtocolSpec(
        key="own_pet",
        oidb_name="OidbSvcTrpcTcp.0x95e1_0",
        command=38369,
        sub_command=0,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetCache_GetUserPet",
        purpose="读取本人宠物 ID 与基础档案",
        request_fields=("空请求", "响应 pet.field101 为 petId"),
    ),
    ProtocolSpec(
        key="feed_times",
        oidb_name="OidbSvcTrpcTcp.0x9949_1",
        command=39241,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetFeed_GetFeedTimesInfo",
        purpose="查询喂食次数与食物库存",
        request_fields=("self 查询时 field 4 为空字符串", "响应含食物计数"),
    ),
    ProtocolSpec(
        key="feed",
        oidb_name="OidbSvcTrpcTcp.0x992d_1",
        command=39213,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetFeed_Feeding",
        purpose="执行喂食",
        request_fields=("主人信息", "petId", "喂食类型", "扩展字段"),
    ),
    ProtocolSpec(
        key="display_value",
        oidb_name="OidbSvcTrpcTcp.0x96f2_1",
        command=38642,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetGrowth_GetDisPlayValue",
        purpose="读取心情、体力、清洁、总分和金币",
        request_fields=("petId", "展示值类型"),
    ),
    ProtocolSpec(
        key="page_rules",
        oidb_name="OidbSvcTrpcTcp.0x96a4_1",
        command=38564,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetBehavior_GetPageRules",
        purpose="获取页面行为规则",
        request_fields=("页面", "来源", "扩展字段"),
    ),
    ProtocolSpec(
        key="report_event",
        oidb_name="OidbSvcTrpcTcp.0x96a6_1",
        command=38566,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetBehavior_ReportEvent",
        purpose="上报学习、打工、冒险等行为",
        request_fields=("petId", "好友 UIN", "执行路径", "扩展字段"),
    ),
    ProtocolSpec(
        key="story_status",
        oidb_name="OidbSvcTrpcTcp.0x975a_1",
        command=38746,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetOutdoor_GetPetStoryStatus",
        purpose="查询学习/打工/冒险等故事状态",
        request_fields=("petId", "查询类型 0"),
    ),
    ProtocolSpec(
        key="story_settle",
        oidb_name="OidbSvcTrpcTcp.0x9760_1",
        command=38752,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetOutdoor_DoAfterStoryInfo",
        purpose="结算故事结果",
        request_fields=("storyId", "action 1000", "petId"),
    ),
    ProtocolSpec(
        key="story_start",
        oidb_name="OidbSvcTrpcTcp.0x975e_1",
        command=38750,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetOutdoor_DoStoryInfo",
        purpose="启动学习、打工、冒险或 PK 故事",
        request_fields=("page", "eventType", "subEvent", "扩展字段"),
    ),
    ProtocolSpec(
        key="encourage",
        oidb_name="OidbSvcTrpcTcp.0x9c44_1",
        command=40004,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetEncourage_Encourage",
        purpose="执行鼓励宠物",
        request_fields=("storyId", "petId"),
        status="partial",
    ),
    ProtocolSpec(
        key="friend_profile",
        oidb_name="OidbSvcTrpcTcp.0x976c_0",
        command=38764,
        sub_command=0,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetFriend_GetOtherUserPet",
        purpose="读取好友宠物资料",
        request_fields=("好友 UIN", "petId"),
    ),
    ProtocolSpec(
        key="pk_friend_list",
        oidb_name="OidbSvcTrpcTcp.0x985d_0",
        command=39005,
        sub_command=0,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetPK_GetFriendList",
        purpose="读取 PK 可选好友池",
        request_fields=("分页参数", "筛选条件"),
    ),
    ProtocolSpec(
        key="pk_power",
        oidb_name="OidbSvcTrpcTcp.0x9ad4_1",
        command=39636,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetPK_GetPower",
        purpose="查询自身或对手战力",
        request_fields=("petId"),
    ),
    ProtocolSpec(
        key="pk_status",
        oidb_name="OidbSvcTrpcTcp.0x975f_1",
        command=38751,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetPK_GetStatus",
        purpose="查询 PK 故事状态",
        request_fields=("storyId"),
    ),
    ProtocolSpec(
        key="start_school",
        oidb_name="OidbSvcTrpcTcp.0x975e_1",
        command=38750,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetOutdoor_DoStoryInfo",
        purpose="启动学习",
        request_fields=("petId", "page 6000", "eventType 6100", "subEvent"),
    ),
    ProtocolSpec(
        key="start_work",
        oidb_name="OidbSvcTrpcTcp.0x975e_1",
        command=38750,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetOutdoor_DoStoryInfo",
        purpose="启动打工",
        request_fields=("petId", "page 6000", "eventType 6400", "subEvent"),
    ),
    ProtocolSpec(
        key="start_adventure",
        oidb_name="OidbSvcTrpcTcp.0x975e_1",
        command=38750,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetOutdoor_DoStoryInfo",
        purpose="启动冒险",
        request_fields=("petId", "page 6000", "eventType 6700", "subEvent"),
    ),
    ProtocolSpec(
        key="buy_food",
        oidb_name="OidbSvcTrpcTcp.0x99df_1",
        command=39391,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetFeed_BuyFood",
        purpose="购买饼干或食物",
        request_fields=("count", "foodId"),
    ),
    ProtocolSpec(
        key="buy_bath_item",
        oidb_name="OidbSvcTrpcTcp.0x9bd0_0",
        command=39888,
        sub_command=0,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetBath_BuyItem",
        purpose="购买洗护道具",
        request_fields=("itemId", "count"),
    ),
    ProtocolSpec(
        key="do_bath",
        oidb_name="OidbSvcTrpcTcp.0x9bf3_1",
        command=39923,
        sub_command=1,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetBath_DoBath",
        purpose="执行洗澡/清洁",
        request_fields=("petId", "道具信息", "目标清洁值"),
    ),
    ProtocolSpec(
        key="poke_friend",
        oidb_name="OidbSvcTrpcTcp.0x985b_0",
        command=39003,
        sub_command=0,
        sso_name="trpc.qqone.gateway.Gateway.Sso_PetFriend_Poke",
        purpose="好友踩踩",
        request_fields=("friendUin"),
    ),
)


PROTOCOL_BY_KEY = {spec.key: spec for spec in PROTOCOL_SPECS}
PROTOCOL_BY_OIDB = {spec.oidb_name: spec for spec in PROTOCOL_SPECS}


def protocol_rows() -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            spec.sso_name,
            spec.oidb_name,
            spec.purpose,
            "；".join(spec.request_fields),
        )
        for spec in PROTOCOL_SPECS
    )

