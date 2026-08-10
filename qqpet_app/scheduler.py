from __future__ import annotations

import copy
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .client import NapCatClient, PetValues, PKOpponent, QQPetError, StoryStatus
from .config import ConfigStore
from .friend_visits import FriendVisitProgress, eligible_friends, parse_uin_list
from .pk_progress import PKProgress
from .progress import DailyProgress
from .notifications import NotificationManager


LogCallback = Callable[[str], None]
StatusCallback = Callable[[PetValues | None, StoryStatus | None, dict], None]
ActivityCallback = Callable[[str], None]


class Scheduler:
    def __init__(
        self,
        config_path: str | Path,
        progress_path: str | Path,
        log: LogCallback | None = None,
        status_callback: StatusCallback | None = None,
        activity_callback: ActivityCallback | None = None,
        client_factory: Callable[[dict], NapCatClient] | None = None,
    ) -> None:
        self.config_store = ConfigStore(config_path)
        self.progress = DailyProgress(progress_path)
        self.friend_progress = FriendVisitProgress(Path(progress_path).parent)
        self.pk_progress = PKProgress(Path(progress_path).parent)
        self.log_callback = log or print
        self.status_callback = status_callback
        self.activity_callback = activity_callback
        self.client_factory = client_factory or self._make_client
        self._stop = threading.Event()
        self._pk_candidate_cache: tuple[PKOpponent, ...] = ()
        self._pk_candidate_cache_until = 0.0
        self._pk_candidate_error_until = 0.0
        self._consecutive_failures = 0
        self._last_alert_at = 0.0
        self._failure_alerted = False
        self._last_friend_care_check = 0.0

    @staticmethod
    def _make_client(config: dict) -> NapCatClient:
        return NapCatClient(
            config["napcat"]["url"],
            config["napcat"]["token"],
            config["account"]["pet_id"],
            float(config["napcat"]["timeout_seconds"]),
        )

    def log(self, message: str) -> None:
        self.log_callback(f"[{datetime.now():%H:%M:%S}] {message}")

    def activity(self, message: str) -> None:
        if self.activity_callback:
            self.activity_callback(message)

    @staticmethod
    def _action_name(kind: str | None) -> str:
        return {
            "school": "学习",
            "work": "打工",
            "adventure": "冒险",
            "employed": "被雇佣任务",
            "pk": "PK",
        }.get(kind or "", "任务")

    def _run_pk_if_due(
        self,
        client: NapCatClient,
        config: dict,
        values: PetValues,
        now: datetime | None = None,
    ) -> str | None:
        pk = config["pk"]
        now = now or datetime.now()
        if not pk["enabled"] or now.strftime("%H:%M") < str(pk["start_time"]):
            return None
        limit = int(pk["max_per_day"])
        if limit > 0 and self.pk_progress.succeeded() >= limit:
            return None
        mode = str(pk.get("opponent_mode", "fixed"))
        if mode == "fixed" and self.pk_progress.retry_blocked():
            return None
        if values.hunger < float(pk["minimum_hunger"]):
            self.activity("等待体力恢复后自动 PK")
            return None
        if values.clean < float(pk["minimum_clean"]):
            self.activity("等待清洁恢复后自动 PK")
            return None
        if self._safe_or_blocked(config, "自动 PK"):
            self.activity("安全模式：已计划自动 PK")
            return "pk"

        self.activity("正在比较双方战力")
        opponent_uin = ""
        opponent_pet_id = ""
        try:
            self_power = client.query_pk_power().power
            opponent = self._select_pk_opponent(client, pk, self_power, now)
            if opponent is None:
                self.activity("暂无可挑战的好友宠物")
                return None
            opponent_uin = opponent.user_id
            opponent_pet_id = opponent.pet_id
            queried_opponent_power = client.query_pk_power(opponent_pet_id).power
            opponent_power = queried_opponent_power or opponent.power
            if (
                pk.get("only_weaker", True)
                and self_power > 0
                and opponent_power > 0
                and opponent_power >= self_power
            ):
                self.log(
                    f"跳过 PK：自身战力 {self_power}，对手战力 {opponent_power}，"
                    "已开启仅挑战更弱对手"
                )
                return None

            self.activity(
                f"正在 PK：{opponent.nickname or opponent.pet_name or opponent_uin} "
                f"（{self_power} 对 {opponent_power or '未知'}）"
            )
            result = client.perform_pk(
                opponent_uin,
                opponent_pet_id,
                float(pk["wait_seconds"]),
            )
        except QQPetError as exc:
            if opponent_uin and opponent_pet_id:
                self.pk_progress.record_failure(
                    opponent_uin,
                    opponent_pet_id,
                    str(exc),
                    float(pk["retry_cooldown_seconds"]),
                    block_all=mode == "fixed",
                )
            self.log(f"自动 PK 失败：{exc}；已进入重试冷却")
            self.activity("PK 失败，等待冷却后重试")
            return "pk_failed"

        self.pk_progress.record_success(
            result,
            opponent.nickname or opponent.pet_name,
            self_power,
            opponent_power,
        )
        self.progress.increment("pk")
        self.log(
            f"PK 已由服务器验证：金币 {result.gold_delta:+.0f}，"
            f"心情 {result.mood_delta:+.0f}，体力 -{result.hunger_cost:.0f}，"
            f"清洁 -{result.clean_cost:.0f}，storyId={result.story_id}；"
            f"今日成功 {self.pk_progress.succeeded()} 次"
        )
        self.activity("PK 结算完成，等待下一轮")
        return "pk"

    def _select_pk_opponent(
        self,
        client: NapCatClient,
        pk: dict,
        self_power: int,
        now: datetime,
    ) -> PKOpponent | None:
        mode = str(pk.get("opponent_mode", "fixed"))
        fallback = PKOpponent(
            user_id=str(pk.get("opponent_uin", "")).strip(),
            pet_id=str(pk.get("opponent_pet_id", "")).strip(),
            nickname=str(pk.get("opponent_name", "")).strip(),
            power=int(pk.get("opponent_power", 0)),
        )
        if mode == "fixed":
            if not fallback.user_id or not fallback.pet_id:
                self.log("自动 PK 已启用，但尚未填写固定对手 QQ 和 petId")
                return None
            return fallback

        timestamp = now.timestamp()
        if timestamp >= self._pk_candidate_cache_until and timestamp >= self._pk_candidate_error_until:
            try:
                self._pk_candidate_cache = client.query_pk_friend_candidates()
                self._pk_candidate_cache_until = timestamp + float(
                    pk.get("friend_refresh_seconds", 1800)
                )
                self.log(
                    f"PK 好友池已从服务器更新：发现 {len(self._pk_candidate_cache)} 只好友宠物"
                )
            except QQPetError as exc:
                self._pk_candidate_error_until = timestamp + min(
                    300.0, float(pk.get("friend_refresh_seconds", 1800))
                )
                self.log(f"PK 好友池暂时无法更新：{exc}")

        candidates = list(self._pk_candidate_cache)
        if not candidates and fallback.user_id and fallback.pet_id:
            # Keep an already verified opponent available when desktop QQ does
            # not expose the friend-list packet, but never describe it as a
            # successful full-friend scan.
            candidates = [fallback]
            self.log("本轮使用已验证的备用对手；好友宠物池尚未由电脑端返回")

        whitelist = parse_uin_list(str(pk.get("friend_whitelist", "")))
        excluded = parse_uin_list(str(pk.get("friend_exclude", "")))
        filtered = []
        for opponent in candidates:
            if whitelist and opponent.user_id not in whitelist:
                continue
            if opponent.user_id in excluded:
                continue
            if self.pk_progress.opponent_retry_blocked(
                opponent.user_id, opponent.pet_id
            ):
                continue
            if (
                pk.get("only_weaker", True)
                and self_power > 0
                and opponent.power > 0
                and opponent.power >= self_power
            ):
                continue
            filtered.append(opponent)
        if not filtered:
            return None

        used = self.pk_progress.opponent_success_counts()
        per_friend_limit = int(pk.get("per_friend_limit", 3))
        filtered = [
            item
            for item in filtered
            if used.get((item.user_id, item.pet_id), 0) < per_friend_limit
        ]
        if not filtered:
            self.log(f"今日每位好友已完成 {per_friend_limit} 次 PK，等待新的可挑战好友")
            return None
        # Keep fighting the selected friend until that friend's quota is used,
        # then move to the next stable candidate. A lower known power wins the
        # tie-breaker so the sequence remains safe and deterministic.
        filtered.sort(
            key=lambda item: (
                item.power if item.power > 0 else 2**31,
                item.user_id,
            )
        )
        return filtered[0]

    def stop(self) -> None:
        self._stop.set()

    def decide(self, config: dict, values: PetValues, now: datetime | None = None) -> str | None:
        now = now or datetime.now()
        counts = self.progress.snapshot()["counts"]
        adventure = config["adventure"]
        due = now.strftime("%H:%M") >= adventure["start_time"]
        adventure_limit = int(adventure["times_per_day"])
        if adventure["enabled"] and due and (adventure_limit == 0 or counts["adventure"] < adventure_limit):
            return "adventure"

        if values.gold >= float(config["scheduler"]["coin_threshold"]):
            if self._under_limit(config, counts, "school"):
                return "school"
            return "work" if self._under_limit(config, counts, "work") else None
        return "work" if self._under_limit(config, counts, "work") else None

    @staticmethod
    def _under_limit(config: dict, counts: dict, kind: str) -> bool:
        if not config[kind]["enabled"]:
            return False
        if kind == "school":
            return True
        limit = int(config[kind]["times_per_day"])
        return limit == 0 or counts[kind] < limit

    def _safe_or_blocked(self, config: dict, action: str, experimental: bool = False) -> bool:
        if config["safety"]["safe_mode"]:
            self.log(f"安全模式：计划执行 {action}，本轮不发送写请求")
            return True
        if experimental and not config["safety"]["allow_experimental_scene_actions"]:
            self.log(f"已阻止实验性动作 {action}；请在设置中明确开启")
            return True
        return False

    def _handle_story(self, client: NapCatClient, config: dict, story: StoryStatus) -> bool:
        state = self.progress.snapshot()
        pending = state.get("pending")
        if story.story_id:
            if self.progress.story_was_settled(story.story_id):
                self.activity("上次任务已结算，正在准备下一项")
                return False
            if story.recallable and not pending:
                mode = str(config["story"].get("employed_recall_mode", "best_split"))
                progress = (
                    story.elapsed_seconds / story.duration_seconds
                    if story.duration_seconds > 0
                    else 0.0
                )
                if mode == "best_split" and progress < 0.25:
                    percent = max(0.0, min(100.0, progress * 100.0))
                    self.activity(f"被雇佣中：等待 25/75（当前 {percent:.1f}%）")
                    self.log(
                        f"检测到被雇佣任务，收益优先模式等待 25/75；"
                        f"当前进度 {story.elapsed_seconds}/{story.duration_seconds}s "
                        f"({percent:.1f}%)，storyId={story.story_id}"
                    )
                    return True
                strategy = "达到 25/75" if mode == "best_split" else "立刻召回"
                self.activity(f"正在召回被雇佣任务（{strategy}）")
                if self._safe_or_blocked(config, "提前召回被雇佣任务"):
                    return True
                if self._settle_and_verify(client, config, story):
                    count = self.progress.increment("employed")
                    self.activity("召回完成，已回到主调度")
                    self.log(
                        f"被雇佣任务已按“{strategy}”召回、服务器验证并计数；"
                        f"今日被雇佣召回 {count} 次"
                    )
                return True

            if not pending:
                recovered_kind = self._story_kind(story.story_id)
                if recovered_kind:
                    self.progress.set_pending(recovered_kind, confirmed=True, story_id=story.story_id)
                    pending = self.progress.snapshot().get("pending")
                    self.log(f"恢复进行中的 {recovered_kind} 任务，后续将接着计数")
            if pending and not pending.get("confirmed"):
                self.progress.confirm_pending(story.story_id)
                pending = self.progress.snapshot().get("pending")
                self.log(f"任务已由服务器确认，storyId={story.story_id}")
            kind = pending.get("kind") if pending else self._story_kind(story.story_id)
            action_name = self._action_name(kind)
            if story.finished and config["story"]["auto_settle_when_end_time_reached"]:
                self.activity(f"正在结算{action_name}")
                if self._safe_or_blocked(config, "结算已完成任务"):
                    return True
                settled = self._settle_and_verify(client, config, story)
                if settled and pending:
                    self.progress.increment(pending["kind"])
                    self.progress.clear_pending()
                    self.log(f"{pending['kind']} 已结算、服务器验证通过并计数")
                return True
            self.activity(f"正在{action_name}（剩余 {story.remaining_seconds}s）")
            self.log(
                f"任务进行中：state={story.state_code}，进度 "
                f"{story.elapsed_seconds}/{story.duration_seconds}s，"
                f"剩余 {story.remaining_seconds}s，storyId={story.story_id}"
            )
            return True

        if pending:
            action_name = self._action_name(pending.get("kind"))
            self.activity(f"等待{action_name}任务确认")
            created = datetime.fromisoformat(pending["created_at"])
            age = (datetime.now().astimezone() - created).total_seconds()
            if pending.get("confirmed"):
                self.progress.increment(pending["kind"])
                self.progress.clear_pending()
                self.log(f"检测到任务已离开进行中状态，补记 {pending['kind']} 1 次")
            elif age >= float(config["story"]["start_confirm_seconds"]):
                self.progress.clear_pending()
                self.log(f"服务器未确认 {pending['kind']} 启动，已取消待确认记录")
            else:
                self.log(f"等待服务器确认 {pending['kind']} 启动（{age:.0f}s）")
            return True
        return False

    def _settle_and_verify(
        self, client: NapCatClient, config: dict, story: StoryStatus
    ) -> bool:
        block_key = f"settle:{story.story_id}"
        block = self.progress.active_care_block(block_key)
        if block:
            remaining = max(0, int(float(block["until"]) - datetime.now().astimezone().timestamp()))
            self.activity(f"结算未生效，{remaining}s 后重试")
            self.log(f"同一任务结算处于冷却期，{remaining}s 后重试，storyId={story.story_id}")
            return False

        try:
            response = client.settle_story(story.story_id)
        except QQPetError as exc:
            retry_seconds = float(config["story"]["settle_retry_seconds"])
            self.progress.set_care_block(
                block_key,
                f"结算请求失败：{exc}",
                retry_seconds,
            )
            self.activity(f"结算未生效，{int(retry_seconds)}s 后重试")
            self.log(
                f"结算请求失败：{exc}；"
                f"不计数，{int(retry_seconds)}s 后重试"
            )
            return False

        # GetPetStoryStatus intentionally keeps returning the last completed
        # story, so clearing of story_id is not a valid success condition.  The
        # mobile client treats a successful 0x9760 response as completion and
        # then renders the result carried in its response body.  Persist the ID
        # to make that acknowledgement idempotent across later scheduler runs.
        self.progress.mark_story_settled(story.story_id)
        self.progress.clear_care_block(block_key)
        self.log(
            f"结算结果已由服务器返回（{len(response.body)} bytes），"
            f"已记录 storyId，后续不会重复结算"
        )
        return True

    @staticmethod
    def _story_kind(story_id: str) -> str | None:
        prefix = story_id.split("_", 1)[0]
        return {"6100": "school", "6400": "work", "6700": "adventure"}.get(prefix)

    def _care_blocked(self, kind: str) -> bool:
        block = self.progress.active_care_block(kind)
        if not block:
            return False
        remaining = max(0, int(float(block["until"]) - datetime.now().astimezone().timestamp()))
        self.log(f"{block['reason']}；{remaining}s 后重试，本轮不启动其他任务")
        return True

    def _block_care(self, config: dict, kind: str, reason: str) -> None:
        seconds = float(config["care"]["failure_cooldown_seconds"])
        self.progress.set_care_block(kind, reason, seconds)
        self.log(f"{reason}；已暂停相关任务 {int(seconds)}s")

    def _verify_delay(self, config: dict) -> None:
        delay = max(0.0, float(config["care"]["verify_delay_seconds"]))
        if delay:
            self._stop.wait(delay)

    def _scan_friends_if_due(
        self, client: NapCatClient, config: dict, now: datetime | None = None
    ) -> None:
        visit_config = config["friend_visits"]
        now = now or datetime.now()
        if not visit_config["enabled"]:
            return
        if now.strftime("%H:%M") < str(visit_config["start_time"]):
            return
        if self.friend_progress.scanned():
            return

        friends = client.query_friend_list()
        candidates = eligible_friends(
            friends,
            str(config["account"]["uin"]),
            str(visit_config.get("whitelist", "")),
            str(visit_config.get("exclude", "")),
        )
        limit = int(visit_config.get("max_per_day", 0))
        if limit > 0:
            candidates = candidates[:limit]
        self.friend_progress.record_scan(len(friends), len(candidates))
        self.log(
            f"每日好友列表已读取：共 {len(friends)} 人，候选 {len(candidates)} 人；"
            "真实协议已抓到（访问 0x96a4/0x96a6、踩踩 0x985b），"
            "但 Windows/NapCat 会话不下发好友页面规则；"
            "在访问记录或奖励可二次验证前不会计为成功"
        )

    def _run_friend_care_if_due(
        self, _client: NapCatClient, config: dict
    ) -> str | None:
        care = config["friend_care"]
        targets = care.get("targets", [])
        if not care.get("enabled", False) or not targets:
            return None
        now = time.monotonic()
        interval = max(15.0, float(care.get("check_interval_seconds", 60)))
        if self._last_friend_care_check and now - self._last_friend_care_check < interval:
            return None
        self._last_friend_care_check = now
        threshold = float(care.get("hunger_threshold", 80))
        for target in targets:
            uin = str(target["uin"])
            pet_id = str(target["pet_id"])
            name = str(target.get("name") or uin)
            block_key = f"friend_feed:{uin}"
            if self.progress.active_care_block(block_key):
                continue
            friend_config = copy.deepcopy(config)
            friend_config["account"]["pet_id"] = pet_id
            try:
                friend_client = self.client_factory(friend_config)
                before = friend_client.query_values()
            except Exception as exc:
                cooldown = float(care.get("failure_cooldown_seconds", 600))
                self.progress.set_care_block(block_key, f"好友状态读取失败：{exc}", cooldown)
                self.log(f"好友照顾检查失败：{name}（QQ {uin}）：{exc}")
                continue
            self.log(
                f"好友照顾检查：{name}（QQ {uin}）体力 {before.hunger:.1f}/100"
            )
            if before.hunger >= threshold:
                self.progress.clear_care_block(block_key)
                continue
            self.activity(f"好友 {name} 体力不足，正在自动喂食")
            if self._safe_or_blocked(config, f"给好友 {name} 喂食"):
                return "friend_feed_blocked"
            try:
                friend_client.feed()
                self._stop.wait(max(0.0, float(care.get("verify_delay_seconds", 1))))
                after = friend_client.query_values()
            except Exception as exc:
                cooldown = float(care.get("failure_cooldown_seconds", 600))
                self.progress.set_care_block(block_key, f"好友喂食请求失败：{exc}", cooldown)
                self.log(f"好友自动喂食失败：{name}（QQ {uin}）：{exc}")
                return "friend_feed_failed"
            if after.hunger <= before.hunger:
                cooldown = float(care.get("failure_cooldown_seconds", 600))
                self.progress.set_care_block(
                    block_key, "好友喂食响应后体力未上涨", cooldown
                )
                self.log(
                    f"好友喂食未生效：{name}（QQ {uin}）体力仍为 {after.hunger:.1f}；"
                    f"{int(cooldown)} 秒后重试"
                )
                return "friend_feed_failed"
            self.progress.clear_care_block(block_key)
            count = self.progress.increment("friend_feed")
            self.activity(f"好友 {name} 喂食完成")
            self.log(
                f"好友自动喂食已由服务器验证：{name}（QQ {uin}）"
                f"{before.hunger:.1f}→{after.hunger:.1f}；今日好友喂食 {count} 次"
            )
            return "friend_feed"
        return None

    def run_once(self) -> str | None:
        self.activity("正在检查宠物状态")
        config = self.config_store.data
        if self.progress.rollover():
            self.log("检测到新的一天，昨日次数已归档，今日计数清零")
        client = self.client_factory(config)
        self._scan_friends_if_due(client, config)
        values = client.query_values()
        story = client.query_story()
        state = self.progress.snapshot()
        state["friend_visit_summary"] = self.friend_progress.summary()
        state["friend_care_summary"] = {
            "enabled": bool(config["friend_care"].get("enabled", False)),
            "targets": len(config["friend_care"].get("targets", [])),
            "feeds": int(state["counts"].get("friend_feed", 0)),
        }
        pk_summary = self.pk_progress.snapshot()
        pk_summary["opponent_mode"] = config["pk"].get("opponent_mode", "fixed")
        pk_summary["friend_pool_count"] = len(self._pk_candidate_cache)
        if self._pk_candidate_cache:
            pk_summary["friend_pool_status"] = "ready"
        elif self._pk_candidate_error_until > datetime.now().timestamp():
            pk_summary["friend_pool_status"] = "unavailable"
        else:
            pk_summary["friend_pool_status"] = "pending"
        state["pk_summary"] = pk_summary
        inventory = client.query_food_inventory()
        state["food_inventory"] = {
            "biscuits": inventory.biscuits,
            "shrimp": inventory.shrimp,
        }
        if self.status_callback:
            bath_inventory = client.query_bath_inventory()
            state["bath_inventory"] = {
                "soap": bath_inventory.soap,
                "bath_ball": bath_inventory.bath_ball,
            }
            self.status_callback(values, story, state)
        self.log(
                f"状态：金币 {values.gold:.2f}，心情 {values.feel:.1f}，体力 {values.hunger:.1f}，"
            f"清洁 {values.clean:.1f}，饼干 {inventory.biscuits}，虾仁 {inventory.shrimp}，"
            f"今日 {state['counts']}"
        )

        care = config["care"]
        if care["enabled"] and values.hunger < float(care["hunger_threshold"]):
            if self._care_blocked("feed"):
                self.activity("等待喂食条件恢复")
                return "feed_blocked"
            if not self._safe_or_blocked(config, "喂食"):
                # The recovered Feeding request uses feed_type=0, which is the
                # biscuit path.  Do not assume it can consume shrimp.
                if inventory.biscuits <= 0:
                    if not care["auto_buy_supplies"]:
                        self.activity("缺少食物，自动购买未开启")
                        self._block_care(config, "feed", f"饼干不足（虾仁 {inventory.shrimp}），自动购买已关闭")
                        return "feed_unavailable"
                    self.activity("正在购买食物")
                    buy_count = int(care["food_purchase_count"])
                    before_count = inventory.biscuits
                    purchase = client.buy_food(buy_count)
                    inventory = client.query_food_inventory()
                    if purchase.bought <= 0 and inventory.biscuits <= before_count:
                        self._block_care(config, "feed", "金币购买饼干未到账")
                        self.activity("购买食物失败，等待重试")
                        return "feed_unavailable"
                    self.log(
                        f"饼干不足，已用金币购买 {purchase.bought or buy_count} 个，"
                        f"花费 {purchase.cost_gold}，当前饼干 {inventory.biscuits}"
                    )
                self.activity("正在喂食")
                client.feed()
                self._verify_delay(config)
                after = client.query_values()
                inventory_after = client.query_food_inventory()
                if after.hunger > values.hunger or inventory_after.biscuits < inventory.biscuits:
                    self.progress.clear_care_block("feed")
                    self.progress.increment("feed")
                    self.log(
                        f"体力不足，已自动喂食并验证成功：{values.hunger:.1f}→{after.hunger:.1f}，"
                        f"剩余饼干 {inventory_after.biscuits}、虾仁 {inventory_after.shrimp}"
                    )
                    self.activity("喂食完成，等待下一轮")
                else:
                    self._block_care(config, "feed", "喂食响应成功但体力和饼干库存均未变化")
                    self.activity("喂食未生效，等待重试")
            return "feed"
        if care["enabled"] and values.clean < float(care["clean_threshold"]):
            if self._care_blocked("wash"):
                self.activity("等待洗澡条件恢复")
                return "wash_blocked"
            if not self._safe_or_blocked(config, "洗澡"):
                bath_inventory = client.query_bath_inventory()
                if bath_inventory.soap <= 0:
                    if not care["auto_buy_supplies"]:
                        self.activity("缺少洗护用品，自动购买未开启")
                        self._block_care(config, "wash", "香皂片不足，自动购买已关闭")
                        return "wash_unavailable"
                    self.activity("正在购买洗护用品")
                    buy_count = int(care["soap_purchase_count"])
                    purchase = client.buy_bath_item("1", buy_count)
                    after_purchase = client.query_bath_inventory()
                    if not purchase.succeeded and after_purchase.soap <= bath_inventory.soap:
                        self._block_care(config, "wash", f"金币购买香皂片未成功（result={purchase.result}）")
                        self.activity("购买洗护用品失败，等待重试")
                        return "wash_unavailable"
                    bath_inventory = after_purchase
                    self.log(f"香皂片不足，已用金币购买 {buy_count} 个，当前香皂片 {bath_inventory.soap}")
                self.activity("正在洗澡")
                client.use_bath_item("1")
                self._verify_delay(config)
                after = client.query_values()
                bath_after = client.query_bath_inventory()
                if after.clean > values.clean or bath_after.soap < bath_inventory.soap:
                    self.progress.clear_care_block("wash")
                    self.progress.increment("wash")
                    self.log(
                        f"清洁不足，已消耗香皂片洗澡并验证成功："
                        f"{values.clean:.1f}→{after.clean:.1f}，剩余香皂片 {bath_after.soap}"
                    )
                    self.activity("洗澡完成，等待下一轮")
                else:
                    self._block_care(
                        config,
                        "wash",
                        "洗澡响应成功但清洁值和香皂片库存均未变化",
                    )
                    self.activity("洗澡未生效，等待重试")
            return "wash"

        friend_care_action = self._run_friend_care_if_due(client, config)
        if friend_care_action:
            return friend_care_action

        # Friend care and PK are side tasks.  Run them while a school, work, or
        # adventure story remains active instead of waiting for that story to
        # finish. Requests stay serialized within this scheduler pass so the
        # same side action cannot be submitted twice at the same instant.
        pk_action = self._run_pk_if_due(client, config, values)
        if pk_action:
            return pk_action

        if self._handle_story(client, config, story):
            return "story"

        action = self.decide(config, values)
        if not action:
            self.activity("空闲：今日任务已完成")
            self.log("今日已没有符合限制的任务")
            return None
        if self._safe_or_blocked(config, action, experimental=True):
            self.activity(f"已暂停：计划{self._action_name(action)}")
            return action
        action_name = self._action_name(action)
        self.activity(f"正在准备{action_name}")
        option = config[action].get("attribute") or config[action].get("option")
        if action == "school":
            self.activity("正在获取当前阶段课程")
            preferred_course = int(config["school"].get("course_sub_event", 0))
            result = client.start_school(option, preferred_course)
            self.progress.set_pending("school")
            course = result.course
            response_story = f"，storyId={result.story_id}" if result.story_id else ""
            selection = "指定" if preferred_course else "当前阶段最高收益"
            self.log(
                f"已选择{selection}的{course.reward}课程“{course.name}”"
                f"（{course.duration}），真实开课指令已发送{response_story}；"
                "等待状态接口确认倒计时"
            )
            self.activity(f"已开课：{course.name}，等待倒计时确认")
            return action
        if action == "work":
            self.activity("正在获取开放职业和岗位")
            career_type = int(config["work"].get("career_type", 0))
            preferred_job = int(config["work"].get("job_sub_event", 0))
            strategy = config["work"].get("strategy", "highest_total")
            result = client.start_work(career_type, preferred_job, strategy)
            self.progress.set_pending("work")
            job = result.job
            response_story = f"，storyId={result.story_id}" if result.story_id else ""
            selection = "指定" if preferred_job else "总收益最高"
            friend_text = "，已雇佣好友" if result.hired_friend else ""
            self.log(
                f"已选择{selection}岗位“{job.name}”"
                f"（{job.career_name}，{job.duration}，收益 {job.reward}），"
                f"真实开工指令已发送{response_story}{friend_text}；"
                "等待状态接口确认倒计时"
            )
            if config["work"].get("employ_friend") and not result.hired_friend:
                self.log("好友雇佣列表未返回可用对象，本次按正式协议无好友开工")
            self.activity(f"已开工：{job.name}，等待倒计时确认")
            return action
        if action == "adventure":
            self.activity("正在获取服务器冒险选项")
            preferred_name = str(config["adventure"].get("option_name", ""))
            result = client.start_adventure(preferred_name)
            self.progress.set_pending("adventure")
            option = result.option
            response_story = f"，storyId={result.story_id}" if result.story_id else ""
            selection = "指定" if preferred_name else "服务器当前可用"
            friend_text = "，已雇佣好友" if result.hired_friend else ""
            reward_text = f"，奖励 {option.reward}" if option.reward else ""
            self.log(
                f"已选择{selection}冒险“{option.name}”"
                f"（{option.duration}，{option.cost}{reward_text}），"
                f"真实冒险指令已发送{response_story}{friend_text}；"
                "等待状态接口确认倒计时"
            )
            self.activity(f"已开始冒险：{option.name}，等待倒计时确认")
            return action
        rules = client.query_page_rules(6000)
        path = client.scene_path(action, option)
        if not rules.allows(path):
            count_text = "未知" if rules.declared_count is None else str(rules.declared_count)
            if action == "school":
                self.log(
                    f"{action}.{option} 已启用且不限次数；"
                    f"当前接口尚未取得学校模块的开课指令（行为规则数 {count_text}），"
                    "本轮不发送未经确认的启动请求"
                )
                self.activity("学习不限次数，正在等待开课接口补齐")
            else:
                self.log(
                    f"服务器当前未开放 {action}.{option}；"
                    f"户外规则数 {count_text}，本轮不发送启动请求"
                )
                self.activity(f"当前无可执行{action_name}路线，本轮跳过")
            return None
        self.activity(f"正在启动{action_name}")
        client.start_scene(action, option, rules)
        self.progress.set_pending(action)
        self.log(
            f"服务器规则已确认 {action}.{option} 可用，已发送启动请求，"
            "等待 storyId 确认"
        )
        self.activity(f"等待{action_name}任务确认")
        return action

    def run_forever(self) -> None:
        self._stop.clear()
        self.activity("自动控制已启动，正在检查")
        self.log("接口调度器已启动")
        while not self._stop.is_set():
            try:
                self.run_once()
                self._record_success()
            except QQPetError as exc:
                self.activity("接口连接异常，正在自动重连")
                self.log(f"接口错误：{exc}")
                self._record_failure(f"接口错误：{exc}")
                if self._reconnect_until_ready():
                    continue
            except Exception as exc:  # 保证后台循环不会因单轮配置错误退出
                self.activity("本轮执行失败，等待重试")
                self.log(f"本轮失败：{type(exc).__name__}: {exc}")
                self._record_failure(f"{type(exc).__name__}: {exc}")
            config = self.config_store.data
            interval = max(3.0, float(config["scheduler"]["interval_seconds"]))
            recall_interval = max(3.0, float(config["story"]["recall_check_seconds"]))
            interval = min(interval, recall_interval)
            self._stop.wait(interval)
        self.activity("自动控制已停止")
        self.log("接口调度器已停止")

    def _reconnect_until_ready(self) -> bool:
        """Probe the stateless OneBot HTTP endpoint without replaying a pet action."""
        config = self.config_store.data
        napcat = config["napcat"]
        if not bool(napcat.get("auto_reconnect", True)):
            self.activity("接口连接异常，自动重连未开启")
            return False
        delay = max(0.1, float(napcat.get("reconnect_initial_seconds", 3)))
        while not self._stop.is_set():
            config = self.config_store.data
            napcat = config["napcat"]
            maximum = max(delay, float(napcat.get("reconnect_max_seconds", 60)))
            self.activity(f"接口已断开，{delay:g} 秒后自动重连")
            self.log(f"等待 {delay:g} 秒后探测 NapCat 登录会话")
            if self._stop.wait(delay):
                return False
            try:
                client = self.client_factory(config)
                uin = client.check_connection()
            except QQPetError as exc:
                self.log(f"自动重连尚未成功：{exc}")
                self._record_failure(f"自动重连失败：{exc}")
                delay = min(maximum, delay * 2)
                continue
            except Exception as exc:
                self.log(f"自动重连探测失败：{type(exc).__name__}: {exc}")
                self._record_failure(f"自动重连探测失败：{type(exc).__name__}: {exc}")
                delay = min(maximum, delay * 2)
                continue
            self.activity("接口连接已恢复，继续自动控制")
            self.log(f"NapCat 登录会话已恢复：QQ {uin}；将从下一轮继续，不重发超时指令")
            self._record_success()
            return True
        return False

    def _record_failure(self, detail: str) -> None:
        self._consecutive_failures += 1
        cfg = self.config_store.data.get("notifications", {})
        if not cfg.get("enabled", False):
            return
        threshold = max(1, int(cfg.get("failure_threshold", 3)))
        now = time.monotonic()
        cooldown = max(0.0, float(cfg.get("cooldown_seconds", 1800)))
        if self._consecutive_failures < threshold:
            return
        if self._last_alert_at > 0 and now - self._last_alert_at < cooldown:
            return
        content = f"主任务已连续失败 {self._consecutive_failures} 次。\n最后错误：{detail}"
        self._last_alert_at = now
        self._failure_alerted = True
        self._send_notification_async("QQ 宠物助手任务失败", content, "failure")

    def _record_success(self) -> None:
        if not self._consecutive_failures:
            return
        failures = self._consecutive_failures
        self._consecutive_failures = 0
        cfg = self.config_store.data.get("notifications", {})
        if self._failure_alerted and cfg.get("enabled") and cfg.get("send_recovery", True):
            self._send_notification_async(
                "QQ 宠物助手已恢复", f"主任务在连续失败 {failures} 次后恢复正常。", "recovery"
            )
        self._failure_alerted = False

    def _send_notification_async(self, title: str, content: str, event: str) -> None:
        config = self.config_store.data

        def worker() -> None:
            results = NotificationManager(config).send(title, content, event)
            summary = "，".join(
                f"{item.channel}:{'成功' if item.succeeded else '失败'}" for item in results
            )
            self.log(f"通知发送结果：{summary or '未启用具体渠道'}")

        threading.Thread(target=worker, daemon=True, name="qqpet-notification").start()
