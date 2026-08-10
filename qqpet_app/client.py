from __future__ import annotations

import base64
import encodings.idna  # Register the codec explicitly in frozen Windows builds.
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .proto import (
    field_bytes,
    field_string,
    field_varint,
    first_bytes,
    first_float,
    first_string,
    first_varint,
    oidb_request,
    parse_message,
)


class QQPetError(RuntimeError):
    pass


@dataclass(frozen=True)
class OidbResponse:
    command: int
    sub_command: int
    error_code: int
    body: bytes
    raw: bytes


@dataclass(frozen=True)
class PetValues:
    feel: float = 0.0
    hunger: float = 0.0
    clean: float = 0.0
    total: float = 0.0
    gold: float = 0.0


@dataclass(frozen=True)
class QQFriend:
    user_id: str
    nickname: str = ""
    remark: str = ""
    category_id: int = 0


@dataclass(frozen=True)
class OwnPetProfile:
    user_id: str
    pet_id: str
    pet_name: str = ""


@dataclass(frozen=True)
class PKOpponent:
    user_id: str
    pet_id: str
    nickname: str = ""
    pet_name: str = ""
    power: int = 0
    dominant_type: int = 0
    pet_status: int = 0


@dataclass(frozen=True)
class FoodInventory:
    """Food counts returned by PetFeed_GetFeedTimesInfo.

    Android QQ 9.3.25's food exchange sheet confirms field 1 is biscuits and
    field 2 is shrimp.  Older code incorrectly labelled these as a remaining
    allowance and a recovery value.
    """

    biscuits: int = 0
    shrimp: int = 0

    @property
    def total(self) -> int:
        return self.biscuits + self.shrimp


@dataclass(frozen=True)
class BathItem:
    item_id: str
    name: str
    gold_price: int
    clean_gain: int
    mood_gain: int
    description: str = ""
    default_count: int = 1
    step: int = 1
    minimum: int = 1
    maximum: int = 99


@dataclass(frozen=True)
class BathInventory:
    counts: tuple[tuple[str, int], ...] = ()

    def count(self, item_id: str) -> int:
        return next((count for key, count in self.counts if key == item_id), 0)

    @property
    def soap(self) -> int:
        return self.count("1")

    @property
    def bath_ball(self) -> int:
        return self.count("2")


@dataclass(frozen=True)
class FoodPurchaseResult:
    balance: int = 0
    gold: int = 0
    bought: int = 0
    cost_gold: int = 0


@dataclass(frozen=True)
class BathPurchaseResult:
    result: int = 0
    order_id: str = ""

    @property
    def succeeded(self) -> bool:
        return self.result == 0 and bool(self.order_id)


@dataclass(frozen=True)
class WashResult:
    clean: int = 0
    mood: int = 0
    remaining: int = 0
    completed: bool = False
    extra_1: int = 0
    extra_2: int = 0


@dataclass(frozen=True)
class StoryStatus:
    story_id: str = ""
    state_code: int = 0
    remaining_seconds: int = 0
    duration_seconds: int = 0
    started_at: int = 0
    recallable: bool = False
    raw_body: bytes = b""

    @property
    def finished(self) -> bool:
        return bool(
            self.story_id
            and self.duration_seconds > 0
            and self.remaining_seconds <= 0
        )

    @property
    def elapsed_seconds(self) -> int:
        return max(0, self.duration_seconds - self.remaining_seconds)


@dataclass(frozen=True)
class SchoolCourse:
    name: str
    sub_event_type: int
    reward: str = ""
    duration: str = ""
    cost: str = ""
    description: str = ""
    can_do: bool = False

    @property
    def reward_value(self) -> int:
        values = [int(value) for value in re.findall(r"\d+", self.reward)]
        return max(values, default=0)


@dataclass(frozen=True)
class SchoolStartResult:
    course: SchoolCourse
    story_id: str = ""
    response: OidbResponse | None = None


@dataclass(frozen=True)
class WorkCareer:
    career_type: int
    name: str
    available: bool = False
    status_code: int = 0
    message: str = ""


@dataclass(frozen=True)
class WorkOverview:
    careers: tuple[WorkCareer, ...] = ()
    current_career_type: int = 0
    last_sub_event_type: int = 0


@dataclass(frozen=True)
class WorkJob:
    career_type: int
    career_name: str
    name: str
    sub_event_type: int
    reward: str = ""
    duration: str = ""
    cost: str = ""
    description: str = ""
    can_do: bool = False

    @property
    def reward_value(self) -> int:
        # The official client embeds an image URL before the actual reward.
        # The URL contains large numeric identifiers, while the displayed
        # amount is the final number in the string.
        values = [int(value) for value in re.findall(r"\d+", self.reward)]
        return values[-1] if values else 0


@dataclass(frozen=True)
class WorkStartResult:
    job: WorkJob
    story_id: str = ""
    hired_friend: bool = False
    response: OidbResponse | None = None


@dataclass(frozen=True)
class AdventureOption:
    name: str
    sub_event_type: int = 0
    reward: str = ""
    duration: str = ""
    cost: str = ""
    description: str = ""
    can_do: bool = False
    unavailable_reason: str = ""


@dataclass(frozen=True)
class AdventureStartResult:
    option: AdventureOption
    story_id: str = ""
    hired_friend: bool = False
    response: OidbResponse | None = None


@dataclass(frozen=True)
class PKPower:
    pet_id: str
    power: int = 0
    dominant_type: int = 0
    raw_body: bytes = b""


@dataclass(frozen=True)
class PKStartResult:
    opponent_uin: str
    opponent_pet_id: str
    story_id: str = ""
    response: OidbResponse | None = None


@dataclass(frozen=True)
class PKResult:
    opponent_uin: str
    opponent_pet_id: str
    story_id: str
    before: PetValues
    after: PetValues
    settlement: OidbResponse

    @property
    def gold_delta(self) -> float:
        return self.after.gold - self.before.gold

    @property
    def mood_delta(self) -> float:
        return self.after.feel - self.before.feel

    @property
    def hunger_cost(self) -> float:
        return max(0.0, self.before.hunger - self.after.hunger)

    @property
    def clean_cost(self) -> float:
        return max(0.0, self.before.clean - self.after.clean)

    @property
    def verified(self) -> bool:
        return bool(
            self.story_id
            and (
                self.gold_delta != 0
                or self.mood_delta != 0
                or self.hunger_cost > 0
                or self.clean_cost > 0
            )
        )


@dataclass(frozen=True)
class PageRules:
    trace: str = ""
    paths: tuple[tuple[int, int, int], ...] = ()
    declared_count: int | None = None

    def allows(self, path: tuple[int, int, int]) -> bool:
        return path in self.paths


Transport = Callable[[str, str], dict]


class NapCatClient:
    OWN_PROFILE = ("OidbSvcTrpcTcp.0x99f2_1", 39410, 1)
    DISPLAY = ("OidbSvcTrpcTcp.0x96f2_1", 38642, 1)
    FEED = ("OidbSvcTrpcTcp.0x992d_1", 39213, 1)
    FEED_TIMES = ("OidbSvcTrpcTcp.0x9949_1", 39241, 1)
    BUY_FOOD = ("OidbSvcTrpcTcp.0x99df_1", 39391, 1)
    BATH_ITEM_CONFIG = ("OidbSvcTrpcTcp.0x9bf1_1", 39921, 1)
    BATH_INVENTORY = ("OidbSvcTrpcTcp.0x9bf2_1", 39922, 1)
    DO_BATH = ("OidbSvcTrpcTcp.0x9bf3_1", 39923, 1)
    BUY_BATH_ITEM = ("OidbSvcTrpcTcp.0x9bd0_0", 39888, 0)
    REPORT_EVENT = ("OidbSvcTrpcTcp.0x96a6_1", 38566, 1)
    PAGE_RULES = ("OidbSvcTrpcTcp.0x96a4_1", 38564, 1)
    FRIEND_PROFILE = ("OidbSvcTrpcTcp.0x976c_0", 38764, 0)
    FRIEND_POKE = ("OidbSvcTrpcTcp.0x985b_0", 39003, 0)
    FRIEND_VISIT_PATH = (1000, 100, 101)
    STORY_STATUS = ("OidbSvcTrpcTcp.0x975a_1", 38746, 1)
    STORY_SETTLE = ("OidbSvcTrpcTcp.0x9760_1", 38752, 1)
    SCHOOL_OVERVIEW = ("OidbSvcTrpcTcp.0x9b60_1", 39776, 1)
    SCHOOL_COURSES = ("OidbSvcTrpcTcp.0x9ab2_1", 39602, 1)
    SCHOOL_START = ("OidbSvcTrpcTcp.0x975e_1", 38750, 1)
    WORK_OVERVIEW = ("OidbSvcTrpcTcp.0x9b60_1", 39776, 1)
    WORK_JOBS = ("OidbSvcTrpcTcp.0x9ab2_1", 39602, 1)
    WORK_START = ("OidbSvcTrpcTcp.0x975e_1", 38750, 1)
    ADVENTURE_OPTIONS = ("OidbSvcTrpcTcp.0x9ab2_1", 39602, 1)
    ADVENTURE_START = ("OidbSvcTrpcTcp.0x975e_1", 38750, 1)
    PK_POWER = ("OidbSvcTrpcTcp.0x9ad4_1", 39636, 1)
    PK_FRIEND_LIST = ("OidbSvcTrpcTcp.0x985d_0", 39005, 0)
    PK_START = ("OidbSvcTrpcTcp.0x975e_1", 38750, 1)
    PK_STATUS = ("OidbSvcTrpcTcp.0x975f_1", 38751, 1)
    PK_SETTLE = ("OidbSvcTrpcTcp.0x9760_1", 38752, 1)

    SCENES = {
        "school": {
            "culture": (6000, 6100, 6101),
            "physical": (6000, 6100, 6201),
            "art": (6000, 6100, 6301),
        },
        "work": {
            "culture": (6000, 6400, 6401),
            "physical": (6000, 6400, 6501),
            "art": (6000, 6400, 6601),
        },
    }

    def __init__(
        self,
        base_url: str,
        token: str,
        pet_id: str,
        timeout: float = 15.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.pet_id = pet_id
        self.timeout = timeout
        self._transport = transport

    def _http_transport(self, command: str, data_hex: str) -> dict:
        return self._onebot_action("send_packet", {"cmd": command, "data": data_hex})

    def _onebot_action(self, action: str, params: dict | None = None) -> dict:
        body = json.dumps(params or {}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/{action}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise QQPetError(f"无法连接本机 NapCat：{exc}") from exc

    def query_friend_list(self) -> tuple[QQFriend, ...]:
        result = self._onebot_action("get_friend_list")
        if result.get("retcode") != 0 or result.get("status") != "ok":
            raise QQPetError(f"NapCat 好友列表请求失败：{result}")
        rows = result.get("data") or []
        friends: list[QQFriend] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("user_id"):
                continue
            friends.append(
                QQFriend(
                    user_id=str(row["user_id"]),
                    nickname=str(row.get("nickname") or ""),
                    remark=str(row.get("remark") or ""),
                    category_id=int(row.get("category_id") or 0),
                )
            )
        return tuple(friends)

    def check_connection(self) -> str:
        """Verify that NapCat is reachable and has a logged-in QQ session."""
        result = self._onebot_action("get_login_info")
        if result.get("retcode") != 0 or result.get("status") != "ok":
            raise QQPetError(f"NapCat 登录会话尚未就绪：{result}")
        data = result.get("data") or {}
        uin = str(data.get("user_id") or "")
        if not uin.isdigit():
            raise QQPetError("NapCat 已连接，但尚未取得有效 QQ 登录会话")
        return uin

    def query_own_pet_profile(self, expected_uin: str = "") -> OwnPetProfile:
        """Read the logged-in account's pet identity without a pre-known petId."""
        response = self.send_oidb(*self.OWN_PROFILE, b"").body
        profile_raw = first_bytes(parse_message(response), 1)
        if not profile_raw:
            raise QQPetError("服务器未返回本人宠物资料，账号可能尚未开通 QQ 宠物")
        profile = parse_message(profile_raw)
        user_id = first_string(profile, 5).strip()
        pet_id = first_string(profile, 8).strip()
        pet_name = first_string(profile, 1).strip()
        if not user_id or not pet_id:
            raise QQPetError("服务器返回的本人宠物资料缺少 QQ 号或宠物 ID")
        if expected_uin and user_id != str(expected_uin):
            raise QQPetError(
                f"服务器宠物资料属于 QQ {user_id}，与当前登录 QQ {expected_uin} 不一致"
            )
        try:
            padding = "=" * (-len(pet_id) % 4)
            decoded = base64.b64decode(pet_id + padding, validate=True).decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise QQPetError("服务器返回的宠物 ID 格式无效") from exc
        if not decoded.startswith(f"{user_id}-"):
            raise QQPetError("服务器返回的宠物 ID 与 QQ 号不匹配")
        return OwnPetProfile(user_id=user_id, pet_id=pet_id, pet_name=pet_name)

    def query_pk_friend_candidates(
        self, source: int = 6, max_pages: int = 20
    ) -> tuple[PKOpponent, ...]:
        """Return the server's pet-owning friend list used by outdoor scenes.

        Source 6 is the value used by the downloaded pet play/PK module.  The
        response is paginated and already contains the friend's UIN, petId and
        PK power, so callers never need to manufacture a petId from a QQ UIN.
        """
        cursor = ""
        opponents: list[PKOpponent] = []
        seen: set[tuple[str, str]] = set()
        for _ in range(max(1, int(max_pages))):
            body = field_varint(2, int(source))
            if cursor:
                body = field_string(1, cursor) + body
            response = self.send_oidb(*self.PK_FRIEND_LIST, body).body
            root = parse_message(response)
            for value in root.get(1, []):
                if value.wire_type != 2:
                    continue
                friend = parse_message(bytes(value.value))
                profile_raw = first_bytes(friend, 1)
                user_raw = first_bytes(friend, 2)
                power_raw = first_bytes(friend, 14)
                if not profile_raw or not user_raw:
                    continue
                profile = parse_message(profile_raw)
                user = parse_message(user_raw)
                power_info = parse_message(power_raw) if power_raw else {}
                pet_id = first_string(profile, 8)
                user_id = str(first_varint(user, 1) or "")
                key = (user_id, pet_id)
                if not user_id or not pet_id or key in seen:
                    continue
                seen.add(key)
                opponents.append(
                    PKOpponent(
                        user_id=user_id,
                        pet_id=pet_id,
                        nickname=first_string(user, 2),
                        pet_name=first_string(profile, 1),
                        power=first_varint(power_info, 4),
                        dominant_type=first_varint(power_info, 3),
                        pet_status=first_varint(friend, 3),
                    )
                )
            next_cursor = first_string(root, 2)
            has_more = bool(first_varint(root, 3))
            if not has_more or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return tuple(opponents)

    def resolve_pk_opponent(
        self, opponent_uin: str, fallback: PKOpponent | None = None
    ) -> PKOpponent:
        """Resolve one QQ friend to a real pet ID and current PK power."""
        target_uin = str(opponent_uin).strip()
        if not target_uin.isdigit():
            raise QQPetError("对手 QQ 号必须是数字")
        if fallback is not None and fallback.user_id != target_uin:
            fallback = None
        try:
            candidates = self.query_pk_friend_candidates()
        except QQPetError:
            if fallback is None or not fallback.pet_id:
                raise
            candidates = ()
        opponent = next(
            (item for item in candidates if item.user_id == target_uin),
            fallback,
        )
        if opponent is None:
            raise QQPetError(f"好友 {target_uin} 未出现在服务器宠物好友列表中")
        try:
            friends = self.query_friend_list()
        except QQPetError:
            friends = ()
        friend = next((item for item in friends if item.user_id == target_uin), None)
        display_name = (
            (friend.remark or friend.nickname)
            if friend is not None
            else opponent.nickname
        )
        latest_power = self.query_pk_power(opponent.pet_id)
        return PKOpponent(
            user_id=opponent.user_id,
            pet_id=opponent.pet_id,
            nickname=display_name or opponent.nickname,
            pet_name=opponent.pet_name,
            power=latest_power.power or opponent.power,
            dominant_type=latest_power.dominant_type or opponent.dominant_type,
            pet_status=opponent.pet_status,
        )

    def send_oidb(self, command_name: str, command: int, sub_command: int, body: bytes) -> OidbResponse:
        request = oidb_request(command, sub_command, body)
        result = (self._transport or self._http_transport)(command_name, request.hex())
        if result.get("retcode") != 0 or result.get("status") != "ok":
            raise QQPetError(f"NapCat 请求失败：{result}")
        data_hex = result.get("data") or ""
        if not data_hex:
            raise QQPetError(f"{command_name} 返回空响应")
        try:
            raw = bytes.fromhex(data_hex)
            outer = parse_message(raw)
        except (ValueError, TypeError) as exc:
            raise QQPetError(f"{command_name} 响应无法解析") from exc
        error_code = first_varint(outer, 3)
        response_body = first_bytes(outer, 4)
        if error_code != 0:
            raise QQPetError(f"{command_name} OIDB errorCode={error_code}")
        return OidbResponse(command, sub_command, error_code, response_body, raw)

    def query_values(self) -> PetValues:
        # 类型 1~5 均返回完整四项状态；类型 6 单独返回金币。
        common_request = field_string(1, self.pet_id) + field_bytes(2, b"\x01")
        common = self.send_oidb(*self.DISPLAY, common_request).body
        common_root = parse_message(first_bytes(parse_message(common), 1))

        def current(field: int) -> float:
            return first_float(parse_message(first_bytes(common_root, field)), 3)

        gold_request = field_string(1, self.pet_id) + field_bytes(2, b"\x06")
        gold = self.send_oidb(*self.DISPLAY, gold_request).body
        gold_root = parse_message(first_bytes(parse_message(gold), 1))
        gold_value = first_float(parse_message(first_bytes(gold_root, 5)), 3)
        return PetValues(current(1), current(2), current(3), current(4), gold_value)

    def feed(self) -> OidbResponse:
        return self.send_oidb(*self.FEED, field_string(4, self.pet_id))

    def query_food_inventory(self) -> FoodInventory:
        # 手机 QQ 9.3.25 的“兑换食物/背包”页已实测：字段 1=饼干，字段 2=虾仁。
        response = self.send_oidb(*self.FEED_TIMES, b"").body
        root = parse_message(response)
        return FoodInventory(
            biscuits=first_varint(root, 1),
            shrimp=first_varint(root, 2),
        )

    def query_feed_allowance(self) -> FoodInventory:
        """Compatibility wrapper; use query_food_inventory in new code."""
        return self.query_food_inventory()

    def buy_food(self, count: int) -> FoodPurchaseResult:
        """Buy biscuits with gold through PetFeed_BuyFood (0x99df_1)."""
        if count <= 0:
            raise QQPetError("购买饼干数量必须大于 0")
        response = self.send_oidb(*self.BUY_FOOD, field_varint(1, count)).body
        root = parse_message(response)
        return FoodPurchaseResult(
            balance=first_varint(root, 1),
            gold=first_varint(root, 2),
            bought=first_varint(root, 3),
            cost_gold=first_varint(root, 4),
        )

    def query_bath_items(self) -> tuple[BathItem, ...]:
        # itemType=1 requests the complete wash-item shop configuration.
        response = self.send_oidb(*self.BATH_ITEM_CONFIG, field_varint(1, 1)).body
        root = parse_message(response)
        items: list[BathItem] = []
        for value in root.get(1, []):
            if value.wire_type != 2:
                continue
            item = parse_message(bytes(value.value))
            items.append(
                BathItem(
                    item_id=first_string(item, 2),
                    name=first_string(item, 1),
                    gold_price=first_varint(item, 5),
                    clean_gain=first_varint(item, 6),
                    mood_gain=first_varint(item, 12),
                    description=first_string(item, 7),
                    default_count=first_varint(item, 8),
                    step=first_varint(item, 9),
                    minimum=first_varint(item, 10),
                    maximum=first_varint(item, 11),
                )
            )
        return tuple(items)

    def query_bath_inventory(self) -> BathInventory:
        response = self.send_oidb(*self.BATH_INVENTORY, field_varint(1, 1)).body
        root = parse_message(response)
        info_raw = first_bytes(root, 1)
        info = parse_message(info_raw) if info_raw else {}
        counts: list[tuple[str, int]] = []
        for value in info.get(1, []):
            if value.wire_type != 2:
                continue
            item = parse_message(bytes(value.value))
            counts.append((first_string(item, 1), first_varint(item, 2)))
        return BathInventory(tuple(counts))

    def buy_bath_item(self, item_id: str, count: int) -> BathPurchaseResult:
        """Buy soap (1) or bath balls (2) through common-pay 0x9bd0_0."""
        if item_id not in {"1", "2"}:
            raise QQPetError(f"未知洗护道具：{item_id}")
        if count <= 0:
            raise QQPetError("购买洗护道具数量必须大于 0")

        # Android QQ uses platform=1/accessAppId=1001. Mall category 355 and
        # purchase scene 21 are fixed by ai_pet_home 6530's buyBathItem flow.
        user = field_varint(1, 1) + field_varint(2, 1001) + field_string(3, self.pet_id)
        mall_item = (
            field_varint(1, 355)
            + field_varint(2, int(item_id))
            + field_varint(3, count)
        )
        body = (
            field_bytes(1, user)
            + field_varint(2, 1001)
            + field_bytes(3, mall_item)
            + field_varint(4, 21)
        )
        response = self.send_oidb(*self.BUY_BATH_ITEM, body).body
        root = parse_message(response)
        return BathPurchaseResult(
            result=first_varint(root, 1),
            order_id=first_string(root, 2),
        )

    def use_bath_item(self, item_id: str, pet_uin: str = "") -> WashResult:
        if item_id not in {"1", "2"}:
            raise QQPetError(f"未知洗护道具：{item_id}")
        body = (
            field_string(1, self.pet_id)
            + field_string(2, item_id)
            + field_varint(3, 1)
            + field_string(4, pet_uin)
        )
        response = self.send_oidb(*self.DO_BATH, body).body
        root = parse_message(response)
        return WashResult(
            clean=first_varint(root, 1),
            mood=first_varint(root, 2),
            remaining=first_varint(root, 3),
            completed=bool(first_varint(root, 4)),
            extra_1=first_varint(root, 5),
            extra_2=first_varint(root, 6),
        )

    def report_event(self, page: int, event_type: int, sub_event: int, business_ext: bytes = b"") -> OidbResponse:
        path = field_varint(1, page) + field_varint(2, event_type) + field_varint(3, sub_event)
        body = field_string(1, self.pet_id) + field_bytes(3, path) + field_bytes(4, b"")
        if business_ext:
            body += field_bytes(5, business_ext)
        return self.send_oidb(*self.REPORT_EVENT, body)

    def query_page_rules(
        self,
        page: int = 6000,
        *,
        pet_id: str = "",
        execute_ext_info: bytes = b"",
        request_from: int | None = None,
        platform: int | None = None,
    ) -> PageRules:
        # si5.m: trace(1), petId(2), page(3), executeExtInfo(4), from(10), platform(99)
        body = (
            field_string(2, pet_id or self.pet_id)
            + field_varint(3, page)
            + field_bytes(4, execute_ext_info)
        )
        if request_from is not None:
            body += field_varint(10, request_from)
        if platform is not None:
            body += field_varint(99, platform)
        response = self.send_oidb(*self.PAGE_RULES, body).body
        root = parse_message(response)
        trace = first_string(root, 1)
        declared_count: int | None = None
        if trace:
            try:
                trace_data = json.loads(trace)
                if isinstance(trace_data, dict) and isinstance(trace_data.get("count"), int):
                    declared_count = int(trace_data["count"])
            except json.JSONDecodeError:
                pass

        paths: list[tuple[int, int, int]] = []
        for item in root.get(2, []):
            if item.wire_type != 2:
                continue
            event = parse_message(bytes(item.value))
            path_raw = first_bytes(event, 1)
            if not path_raw:
                continue
            path = parse_message(path_raw)
            paths.append(
                (
                    first_varint(path, 1),
                    first_varint(path, 2),
                    first_varint(path, 3),
                )
            )
        return PageRules(trace=trace, paths=tuple(paths), declared_count=declared_count)

    def query_friend_visit_rules(
        self, friend_pet_id: str, execute_ext_info: bytes = b""
    ) -> PageRules:
        """Read the friend-home rules using the real Android request shape.

        A Windows/NapCat session currently returns count=0 even when the full
        Android payload is replayed. Callers must treat that as unsupported,
        not as a completed visit.
        """
        return self.query_page_rules(
            self.FRIEND_VISIT_PATH[0],
            pet_id=friend_pet_id,
            execute_ext_info=execute_ext_info,
            request_from=0,
            platform=0,
        )

    def report_friend_visit(
        self,
        friend_uin: str,
        friend_pet_id: str,
        execute_ext_info: bytes = b"",
    ) -> OidbResponse:
        page, event_type, sub_event = self.FRIEND_VISIT_PATH
        path = (
            field_varint(1, page)
            + field_varint(2, event_type)
            + field_varint(3, sub_event)
        )
        body = (
            field_string(1, friend_pet_id)
            + field_string(2, str(friend_uin))
            + field_bytes(3, path)
            + field_bytes(4, execute_ext_info)
        )
        return self.send_oidb(*self.REPORT_EVENT, body)

    def poke_friend(self, friend_uin: str) -> OidbResponse:
        try:
            numeric_uin = int(str(friend_uin))
        except ValueError as exc:
            raise QQPetError(f"好友 QQ 号无效：{friend_uin}") from exc
        return self.send_oidb(*self.FRIEND_POKE, field_varint(1, numeric_uin))

    def wash(self, target_clean: int = 100) -> OidbResponse:
        return self.report_event(5000, 500, 501, field_varint(5, target_clean))

    def scene_path(self, scene: str, option: str) -> tuple[int, int, int]:
        try:
            return self.SCENES[scene][option]
        except KeyError as exc:
            raise QQPetError(f"未知场景选项：{scene}.{option}") from exc

    def query_school_stage(self) -> int:
        body = (
            field_varint(1, 6100)
            + field_string(2, self.pet_id)
            + field_varint(100, 2)
        )
        root = parse_message(self.send_oidb(*self.SCHOOL_OVERVIEW, body).body)
        stage = first_varint(root, 4)
        if stage not in {0, 1, 2, 3, 4}:
            raise QQPetError(f"服务器返回未知学习阶段：{stage}")
        return stage

    def query_school_courses(self, stage: int | None = None) -> tuple[SchoolCourse, ...]:
        stage = self.query_school_stage() if stage is None else int(stage)
        body = (
            field_varint(1, 6100)
            + field_string(2, self.pet_id)
            + field_string(3, "")
            + field_varint(11, stage)
            + field_varint(100, 2)
        )
        root = parse_message(self.send_oidb(*self.SCHOOL_COURSES, body).body)
        courses: list[SchoolCourse] = []
        for value in root.get(1, []):
            if value.wire_type != 2:
                continue
            item = parse_message(bytes(value.value))
            courses.append(
                SchoolCourse(
                    name=first_string(item, 1),
                    sub_event_type=first_varint(item, 52),
                    cost=first_string(item, 6),
                    duration=first_string(item, 7),
                    reward=first_string(item, 8),
                    description=first_string(item, 14),
                    can_do=bool(first_varint(item, 50)),
                )
            )
        return tuple(courses)

    def select_school_course(
        self, attribute: str, preferred_sub_event: int = 0
    ) -> SchoolCourse:
        keyword = {"physical": "力量", "culture": "智力", "art": "魅力"}.get(attribute)
        if not keyword:
            raise QQPetError(f"未知学习属性：{attribute}")
        courses = self.query_school_courses()
        if preferred_sub_event:
            selected = next(
                (
                    course
                    for course in courses
                    if course.can_do
                    and course.sub_event_type == int(preferred_sub_event)
                ),
                None,
            )
            if selected is None:
                raise QQPetError(
                    f"指定课程 {preferred_sub_event} 不属于当前阶段或暂不可用"
                )
            return selected
        candidates = [
            course
            for course in courses
            if course.can_do
            and course.sub_event_type > 0
            and keyword in course.reward
        ]
        if not candidates:
            raise QQPetError(f"当前学习阶段暂无可用的{keyword}课程")
        return max(candidates, key=lambda course: (course.reward_value, course.sub_event_type))

    def start_school(
        self, attribute: str, preferred_sub_event: int = 0
    ) -> SchoolStartResult:
        course = self.select_school_course(attribute, preferred_sub_event)
        body = (
            field_varint(1, 6100)
            + field_string(2, self.pet_id)
            + field_string(3, "")
            + field_string(6, course.name)
            + field_varint(7, course.sub_event_type)
            + field_varint(100, 2)
        )
        response = self.send_oidb(*self.SCHOOL_START, body)
        story_id = first_string(parse_message(response.body), 1)
        return SchoolStartResult(course=course, story_id=story_id, response=response)

    def query_work_overview(self) -> WorkOverview:
        body = (
            field_varint(1, 6400)
            + field_string(2, self.pet_id)
            + field_varint(100, 2)
        )
        root = parse_message(self.send_oidb(*self.WORK_OVERVIEW, body).body)
        careers: list[WorkCareer] = []
        for value in root.get(1, []):
            if value.wire_type != 2:
                continue
            item = parse_message(bytes(value.value))
            career_type = first_varint(item, 20)
            if career_type <= 0:
                continue
            status_code = first_varint(item, 4)
            name = first_string(item, 1)
            careers.append(
                WorkCareer(
                    career_type=career_type,
                    name=name,
                    available=status_code != 3 and name != "???",
                    status_code=status_code,
                    message=first_string(item, 5),
                )
            )
        return WorkOverview(
            careers=tuple(careers),
            current_career_type=first_varint(root, 3),
            last_sub_event_type=first_varint(root, 5),
        )

    def query_work_jobs(
        self, career_type: int, hired_pet_id: str = ""
    ) -> tuple[WorkJob, ...]:
        career_type = int(career_type)
        if career_type <= 0:
            raise QQPetError("职业类型必须大于 0")
        body = (
            field_varint(1, 6400)
            + field_string(2, self.pet_id)
            + field_string(3, hired_pet_id)
            + field_varint(10, career_type)
            + field_varint(100, 2)
        )
        root = parse_message(self.send_oidb(*self.WORK_JOBS, body).body)
        career_name = first_string(root, 2)
        jobs: list[WorkJob] = []
        for value in root.get(1, []):
            if value.wire_type != 2:
                continue
            item = parse_message(bytes(value.value))
            jobs.append(
                WorkJob(
                    career_type=career_type,
                    career_name=career_name,
                    name=first_string(item, 1),
                    sub_event_type=first_varint(item, 52),
                    cost=first_string(item, 6),
                    duration=first_string(item, 7),
                    reward=first_string(item, 8),
                    description=first_string(item, 14),
                    can_do=bool(first_varint(item, 50)),
                )
            )
        return tuple(jobs)

    def select_work_job(
        self,
        career_type: int = 0,
        preferred_sub_event: int = 0,
        strategy: str = "highest_total",
        hired_pet_id: str = "",
    ) -> WorkJob:
        if strategy != "highest_total":
            raise QQPetError(f"未知岗位选择策略：{strategy}")
        overview = self.query_work_overview()
        available = [career for career in overview.careers if career.available]
        if career_type:
            available = [
                career for career in available if career.career_type == int(career_type)
            ]
            if not available:
                raise QQPetError(f"职业 {career_type} 尚未开放")
        if not available:
            raise QQPetError("服务器当前没有开放的职业")

        jobs = [
            job
            for career in available
            for job in self.query_work_jobs(career.career_type, hired_pet_id)
            if job.can_do and job.sub_event_type > 0
        ]
        if preferred_sub_event:
            selected = next(
                (
                    job
                    for job in jobs
                    if job.sub_event_type == int(preferred_sub_event)
                ),
                None,
            )
            if selected is None:
                raise QQPetError(
                    f"指定岗位 {preferred_sub_event} 不属于开放职业或暂不可用"
                )
            return selected
        if not jobs:
            raise QQPetError("服务器当前没有可执行的打工岗位")

        # On equal total reward, keep the current career when possible.  The
        # final key is deterministic so automatic runs do not jump careers.
        return max(
            jobs,
            key=lambda job: (
                job.reward_value,
                job.career_type == overview.current_career_type,
                -job.career_type,
                job.sub_event_type,
            ),
        )

    def start_work(
        self,
        career_type: int = 0,
        preferred_sub_event: int = 0,
        strategy: str = "highest_total",
        hired_user_id: str = "",
        hired_pet_id: str = "",
    ) -> WorkStartResult:
        if bool(hired_user_id) != bool(hired_pet_id):
            raise QQPetError("雇佣好友时必须同时提供好友账号和宠物 ID")
        job = self.select_work_job(
            career_type,
            preferred_sub_event,
            strategy,
            hired_pet_id,
        )
        body = (
            field_varint(1, 6400)
            + field_string(2, self.pet_id)
            + field_string(3, "")
        )
        if hired_user_id and hired_pet_id:
            friend = field_string(1, hired_user_id) + field_string(2, hired_pet_id)
            body += field_bytes(4, friend)
        body += (
            field_string(6, job.name)
            + field_varint(7, job.sub_event_type)
            + field_varint(100, 2)
        )
        response = self.send_oidb(*self.WORK_START, body)
        story_id = first_string(parse_message(response.body), 1)
        return WorkStartResult(
            job=job,
            story_id=story_id,
            hired_friend=bool(hired_user_id and hired_pet_id),
            response=response,
        )

    def query_adventure_options(
        self, hired_pet_id: str = ""
    ) -> tuple[AdventureOption, ...]:
        body = (
            field_varint(1, 6700)
            + field_string(2, self.pet_id)
            + field_string(3, hired_pet_id)
            + field_varint(100, 2)
        )
        root = parse_message(self.send_oidb(*self.ADVENTURE_OPTIONS, body).body)
        options: list[AdventureOption] = []
        for value in root.get(1, []):
            if value.wire_type != 2:
                continue
            item = parse_message(bytes(value.value))
            options.append(
                AdventureOption(
                    name=first_string(item, 1),
                    sub_event_type=first_varint(item, 52),
                    cost=first_string(item, 6),
                    duration=first_string(item, 7),
                    reward=first_string(item, 8),
                    description=first_string(item, 10) or first_string(item, 14),
                    can_do=bool(first_varint(item, 50)),
                    unavailable_reason=first_string(item, 51),
                )
            )
        return tuple(options)

    def select_adventure_option(
        self, preferred_name: str = "", hired_pet_id: str = ""
    ) -> AdventureOption:
        options = [
            option
            for option in self.query_adventure_options(hired_pet_id)
            if option.can_do and option.name
        ]
        if preferred_name:
            selected = next(
                (option for option in options if option.name == preferred_name),
                None,
            )
            if selected is None:
                raise QQPetError(f"指定冒险“{preferred_name}”当前不可用")
            return selected
        if not options:
            raise QQPetError("服务器当前没有可执行的冒险")
        return options[0]

    def start_adventure(
        self,
        preferred_name: str = "",
        hired_user_id: str = "",
        hired_pet_id: str = "",
    ) -> AdventureStartResult:
        if bool(hired_user_id) != bool(hired_pet_id):
            raise QQPetError("冒险雇佣好友时必须同时提供好友账号和宠物 ID")
        option = self.select_adventure_option(preferred_name, hired_pet_id)
        body = (
            field_varint(1, 6700)
            + field_string(2, self.pet_id)
            + field_string(3, "")
        )
        if hired_user_id and hired_pet_id:
            friend = field_string(1, hired_user_id) + field_string(2, hired_pet_id)
            body += field_bytes(4, friend)
        body += field_string(6, option.name)
        if option.sub_event_type > 0:
            body += field_varint(7, option.sub_event_type)
        body += field_varint(100, 2)
        response = self.send_oidb(*self.ADVENTURE_START, body)
        story_id = first_string(parse_message(response.body), 1)
        return AdventureStartResult(
            option=option,
            story_id=story_id,
            hired_friend=bool(hired_user_id and hired_pet_id),
            response=response,
        )

    def query_pk_power(self, pet_id: str = "") -> PKPower:
        target_pet_id = pet_id or self.pet_id
        body = field_string(1, target_pet_id) + field_varint(100, 2)
        response = self.send_oidb(*self.PK_POWER, body).body
        root = parse_message(response)
        info_raw = first_bytes(root, 1)
        info = parse_message(info_raw) if info_raw else {}
        # Own-pet responses carry dominant type in field 3 and total power in
        # field 4.  Friend responses observed on QQ 9.3.35 omit field 4 and
        # place the displayed opponent power in field 3.
        if info.get(4):
            power = first_varint(info, 4)
            dominant_type = first_varint(info, 3)
        else:
            power = first_varint(info, 3)
            dominant_type = 0
        return PKPower(target_pet_id, power, dominant_type, response)

    def start_pk(
        self,
        opponent_uin: str,
        opponent_pet_id: str,
    ) -> PKStartResult:
        if not opponent_uin or not opponent_pet_id:
            raise QQPetError("自动 PK 必须同时提供对手 QQ 和宠物 ID")
        opponent = (
            field_string(1, opponent_pet_id)
            + field_string(2, opponent_uin)
        )
        # Captured from pet_pk 1.0.713 / Android QQ 9.3.35.  Page 6900 is
        # PK, 6901 is the direct battle event and 75 is the no-bodyguard mode.
        body = (
            field_varint(1, 6900)
            + field_string(2, self.pet_id)
            + field_bytes(4, opponent)
            + field_bytes(6, field_varint(10, 75))
            + field_varint(7, 6901)
            + field_varint(100, 2)
        )
        response = self.send_oidb(*self.PK_START, body)
        story_id = first_string(parse_message(response.body), 1)
        if not story_id.startswith("6900_"):
            raise QQPetError("PK 开始接口未返回有效 storyId")
        return PKStartResult(
            opponent_uin=opponent_uin,
            opponent_pet_id=opponent_pet_id,
            story_id=story_id,
            response=response,
        )

    def query_pk_status(self, story_id: str) -> OidbResponse:
        body = field_string(1, story_id) + field_string(2, self.pet_id)
        return self.send_oidb(*self.PK_STATUS, body)

    def settle_pk(self, story_id: str) -> OidbResponse:
        # PK settlement differs from long-running outdoor stories: field 2 is
        # page 6000 and field 4 is the normal-completion source.
        body = (
            field_string(1, story_id)
            + field_varint(2, 6000)
            + field_string(3, self.pet_id)
            + field_varint(4, 0)
            + field_varint(100, 2)
        )
        return self.send_oidb(*self.PK_SETTLE, body)

    def perform_pk(
        self,
        opponent_uin: str,
        opponent_pet_id: str,
        wait_seconds: float = 9.0,
    ) -> PKResult:
        before = self.query_values()
        started = self.start_pk(opponent_uin, opponent_pet_id)
        time.sleep(max(8.0, float(wait_seconds)))
        # The desktop bridge currently returns an empty status body, which is
        # valid for this short story.  The settlement and state delta below
        # are the authoritative success checks.
        self.query_pk_status(started.story_id)
        settlement = self.settle_pk(started.story_id)
        after = self.query_values()
        result = PKResult(
            opponent_uin=opponent_uin,
            opponent_pet_id=opponent_pet_id,
            story_id=started.story_id,
            before=before,
            after=after,
            settlement=settlement,
        )
        if not result.verified:
            raise QQPetError("PK 已返回结算包，但金币、心情、体力和清洁均未变化")
        return result

    def start_scene(self, scene: str, option: str, rules: PageRules | None = None) -> OidbResponse:
        if scene == "school":
            result = self.start_school(option)
            if result.response is None:  # pragma: no cover - dataclass invariant
                raise QQPetError("开课接口未返回响应")
            return result.response
        if scene == "work":
            result = self.start_work()
            if result.response is None:  # pragma: no cover - dataclass invariant
                raise QQPetError("开工接口未返回响应")
            return result.response
        if scene == "adventure":
            result = self.start_adventure()
            if result.response is None:  # pragma: no cover - dataclass invariant
                raise QQPetError("冒险接口未返回响应")
            return result.response
        page, event_type, sub_event = self.scene_path(scene, option)
        if rules is not None and not rules.allows((page, event_type, sub_event)):
            raise QQPetError(f"服务器当前未开放场景选项：{scene}.{option}")
        return self.report_event(page, event_type, sub_event)

    def query_story(self) -> StoryStatus:
        # PetOutDoorVM queries the same protocol version used by settlement.
        # Without field 100 the server can keep returning a stale completed
        # story even after DoAfterStoryInfo has already produced its result.
        request = field_string(1, self.pet_id) + field_varint(100, 2)
        response = self.send_oidb(*self.STORY_STATUS, request).body
        root = parse_message(response)
        detail_raw = first_bytes(root, 1)
        detail = parse_message(detail_raw) if detail_raw else {}
        return StoryStatus(
            story_id=first_string(root, 2),
            state_code=first_varint(detail, 1),
            remaining_seconds=first_varint(detail, 2),
            duration_seconds=first_varint(detail, 3),
            started_at=first_varint(detail, 4),
            recallable=bool(first_varint(detail, 5)),
            raw_body=response,
        )

    def settle_story(self, story_id: str, outdoor_version: int = 2) -> OidbResponse:
        # QQ 9.3.25's PetOutDoorVM writes OutdoorVersion to protobuf field 100.
        # Omitting it makes the OIDB request look successful while leaving the
        # story untouched, which in turn causes an endless settlement loop.
        body = (
            field_string(1, story_id)
            + field_varint(2, 1000)
            + field_string(3, self.pet_id)
            + field_varint(100, outdoor_version)
        )
        return self.send_oidb(*self.STORY_SETTLE, body)
