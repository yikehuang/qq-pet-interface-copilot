from __future__ import annotations

import copy
import math
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .client import (
    NapCatClient,
    PetValues,
    PKOpponent,
    QQPetConnectionError,
    QQPetEmptyResponse,
    QQPetError,
    StoryStatus,
    WorkEligibilityError,
)
from .config import ConfigStore
from .friend_visits import (
    FriendVisitProgress,
    current_pet_friends,
    eligible_friends,
    parse_uin_list,
)
from .pk_progress import PKProgress
from .progress import DailyProgress
from .notifications import NotificationManager
from .mobile_protocol import reader_from_config
from .optimizer import (
    AdaptiveDecision,
    choose_adaptive_plan,
    derive_auto_optimization_inputs,
)


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
        self._login_guard_blocked = False
        self._optimization_auto_summary = "等待首次读取服务器目录"
        self._next_optimization_probe_at = 0.0

    @staticmethod
    def _make_client(config: dict) -> NapCatClient:
        mobile_reader = reader_from_config(config)
        if mobile_reader is None:
            raise QQPetError("手机 QQ 协议未启用，调度器不会回退到 NapCat 或桌面接口")
        return NapCatClient(
            config["napcat"]["url"],
            config["napcat"]["token"],
            config["account"]["pet_id"],
            float(config["napcat"]["timeout_seconds"]),
            values_reader=mobile_reader.query_values if mobile_reader else None,
            oidb_read_transport=mobile_reader.send_oidb_read if mobile_reader else None,
            oidb_write_transport=(
                mobile_reader.send_oidb_write_once if mobile_reader else None
            ),
            login_uin_reader=mobile_reader.get_self_uin if mobile_reader else None,
            friend_list_reader=mobile_reader.query_friend_list if mobile_reader else None,
        )

    def log(self, message: str) -> None:
        self.log_callback(f"[{datetime.now():%H:%M:%S}] {message}")

    def activity(self, message: str) -> None:
        if self.activity_callback:
            self.activity_callback(message)

    def _verify_login_session(self, client: NapCatClient, config: dict) -> str:
        """Block every pet request unless the configured QQ session is online."""
        checker = getattr(client, "check_connection", None)
        if checker is None:  # Lightweight test/dry-run clients do not own a QQ session.
            return ""
        try:
            uin = str(checker() or "").strip()
        except QQPetError as exc:
            message = f"登录态守卫已暂停全部操作：{exc}"
            self._notify_login_guard_once(message)
            raise QQPetConnectionError(message) from exc
        expected = str(config.get("account", {}).get("uin", "")).strip()
        if expected.isdigit() and uin != expected:
            message = "登录态守卫已暂停全部操作：模拟器当前账号与配置账号不一致"
            self._notify_login_guard_once(message)
            raise QQPetConnectionError(message)
        if self._login_guard_blocked:
            self._login_guard_blocked = False
            self.log("登录态守卫已确认正确账号在线，恢复自动控制")
            self._send_notification_async(
                "QQ 宠物助手登录已恢复",
                "模拟器 QQ 已恢复为配置账号，自动任务将从下一轮继续。",
                "login_recovery",
            )
        return uin

    def _notify_login_guard_once(self, message: str) -> None:
        if self._login_guard_blocked:
            return
        self._login_guard_blocked = True
        self.activity("QQ 登录异常，已暂停全部宠物操作")
        self.log(message)
        self._send_notification_async(
            "QQ 宠物助手已暂停",
            f"{message}\n请在 MuMu 模拟器中重新登录配置账号。",
            "login_guard",
        )

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
        if not pk["enabled"]:
            return None
        if self.pk_progress.daily_run_completed():
            return None
        batch_started = self.pk_progress.daily_run_started()
        if not batch_started:
            # Do not catch up simply because the application was opened after
            # the configured time. The batch is armed only during that exact
            # minute, then persisted so a legitimately started batch can resume.
            if now.strftime("%H:%M") != str(pk["start_time"]):
                return None
            self.pk_progress.mark_daily_run_started()
        limit = int(pk["max_per_day"])
        if limit > 0 and self.pk_progress.succeeded() >= limit:
            self.pk_progress.mark_daily_run_completed("已达到每日 PK 上限")
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

        if not batch_started:
            self.log(
                f"每日定时 PK 批次开始：计划时间 {pk['start_time']}，"
                f"今日上限 {limit if limit > 0 else '按好友额度'} 次"
            )
        completed_this_batch = 0
        # max_per_day=0 means exhaust the configured friend quotas. Keep a hard
        # safety ceiling in case a fixed opponent is configured without a limit.
        safety_ceiling = limit if limit > 0 else max(
            1, int(pk.get("per_friend_limit", 3)) * (100 if mode == "all_friends" else 1)
        )
        while self.pk_progress.succeeded() < safety_ceiling:
            current_values = client.query_values()
            if current_values.hunger < float(pk["minimum_hunger"]):
                self.log("每日 PK 批次暂停：体力低于 PK 阈值，自动照顾后继续")
                self.activity("等待体力恢复后继续每日 PK")
                return "pk_paused"
            if current_values.clean < float(pk["minimum_clean"]):
                self.log("每日 PK 批次暂停：清洁低于 PK 阈值，自动照顾后继续")
                self.activity("等待清洁恢复后继续每日 PK")
                return "pk_paused"

            self.activity("每日 PK：正在比较双方战力")
            opponent_uin = ""
            opponent_pet_id = ""
            try:
                self_power = client.query_pk_power().power
                opponent = self._select_pk_opponent(client, pk, self_power, now)
                if opponent is None:
                    reason = "没有符合筛选条件或剩余额度的好友宠物"
                    self.pk_progress.mark_daily_run_completed(reason)
                    self.log(f"每日 PK 批次完成：{reason}；今日成功 {self.pk_progress.succeeded()} 次")
                    self.activity("今日自动 PK 已完成")
                    return "pk" if completed_this_batch else "pk_completed"
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
                    self.pk_progress.record_failure(
                        opponent_uin,
                        opponent_pet_id,
                        f"战力筛选：自身 {self_power}，对手 {opponent_power}",
                        86400,
                        block_all=mode == "fixed",
                    )
                    self.log(
                        f"跳过 PK：自身战力 {self_power}，对手战力 {opponent_power}，"
                        "已开启仅挑战更弱对手"
                    )
                    if mode == "fixed":
                        self.pk_progress.mark_daily_run_completed("固定对手不符合战力筛选")
                        return "pk_completed"
                    continue

                self.activity(
                    f"每日 PK：{opponent.nickname or opponent.pet_name or opponent_uin} "
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
                else:
                    self.pk_progress.mark_daily_run_completed(
                        "PK 战力或好友接口读取失败"
                    )
                    self.log(f"自动 PK 批次读取失败：{exc}；今日不再自动重发")
                    self.activity("今日自动 PK 已结束")
                    return "pk_failed"
                self.log(f"自动 PK 失败：{exc}；本次每日批次不重复发送该对手")
                if mode == "fixed":
                    self.pk_progress.mark_daily_run_completed("固定对手 PK 失败")
                    self.activity("今日自动 PK 已结束")
                    return "pk_failed"
                continue

            self.pk_progress.record_success(
                result,
                opponent.nickname or opponent.pet_name,
                self_power,
                opponent_power,
            )
            self.progress.increment("pk")
            completed_this_batch += 1
            verification = "状态变化复查" if result.state_verified else "服务器结算"
            self.log(
                f"PK 已由{verification}验证：金币 {result.gold_delta:+.0f}，"
                f"心情 {result.mood_delta:+.0f}，体力 -{result.hunger_cost:.0f}，"
                f"清洁 -{result.clean_cost:.0f}"
                f"{f'，storyId={result.story_id}' if result.story_id else ''}；"
                f"今日成功 {self.pk_progress.succeeded()} 次"
            )

        self.pk_progress.mark_daily_run_completed("已达到每日 PK 上限")
        self.log(f"每日 PK 批次完成：今日成功 {self.pk_progress.succeeded()} 次")
        self.activity("今日自动 PK 已完成")
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

    def _select_work_hire(self, client: NapCatClient, config: dict) -> PKOpponent | None:
        """Choose a verified friend pet for work without blocking normal work."""
        work = config["work"]
        if not work.get("employ_friend", False):
            return None
        hire_mode = str(work.get("hire_mode", "auto"))
        own_uin = str(config.get("account", {}).get("uin", "")).strip()
        unavailable_uins = self.progress.work_hire_unavailable_uins()
        try:
            candidates = tuple(
                item
                for item in client.query_pk_friend_candidates()
                if item.user_id
                and item.pet_id
                and item.user_id != own_uin
                and item.user_id not in unavailable_uins
            )
        except QQPetError as exc:
            candidates = ()
            self.log(f"打工雇佣好友池暂时无法更新：{exc}")

        if hire_mode == "manual":
            selected_uin = str(work.get("hire_friend_uin", "")).strip()
            selected_pet_id = str(work.get("hire_friend_pet_id", "")).strip()
            if selected_uin in unavailable_uins:
                self.log("手动选择的雇佣好友今天已不可再雇佣，本次改为无好友打工")
                return None
            selected = next(
                (item for item in candidates if item.user_id == selected_uin),
                None,
            )
            if selected is not None:
                self.log(
                    f"打工将手动雇佣好友 "
                    f"{selected.nickname or selected.pet_name or selected.user_id}"
                )
                return selected
            if selected_uin and selected_pet_id:
                self.log("手动雇佣好友本轮未出现在好友池，使用已保存的真实宠物 ID")
                return PKOpponent(
                    user_id=selected_uin,
                    pet_id=selected_pet_id,
                    nickname=str(work.get("hire_friend_name", "")).strip(),
                )
            self.log("已选择手动雇佣，但尚未保存有效好友；本次不雇佣")
            return None

        if candidates:
            # Prefer the strongest known friend. The QQ number is a stable
            # tie-breaker when the server omits power or returns equal values.
            return sorted(
                candidates,
                key=lambda item: (-(item.power or 0), item.user_id),
            )[0]

        pk = config.get("pk", {})
        fallback = PKOpponent(
            user_id=str(pk.get("opponent_uin", "")).strip(),
            pet_id=str(pk.get("opponent_pet_id", "")).strip(),
            nickname=str(pk.get("opponent_name", "")).strip(),
            power=int(pk.get("opponent_power", 0)),
        )
        if fallback.user_id in unavailable_uins:
            self.log("备用雇佣好友今天已不可再雇佣，本次改为无好友打工")
            return None
        if fallback.user_id and fallback.pet_id:
            self.log("打工雇佣使用已验证的备用好友；服务器好友宠物池本轮为空")
            return fallback
        return None

    @staticmethod
    def _is_work_hire_unavailable(exc: Exception) -> bool:
        message = str(exc)
        return any(
            marker in message
            for marker in (
                "今天很累",
                "今日很累",
                "无法继续被雇佣",
                "不能继续被雇佣",
                "今日不可雇佣",
                "已经被雇佣过",
                "已被雇佣过",
            )
        )

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

    def _adaptive_decision(
        self, client: NapCatClient, config: dict, values: PetValues
    ) -> AdaptiveDecision | None:
        settings = config.get("optimization", {})
        if not settings.get("enabled", False):
            return None
        courses = ()
        jobs = ()
        counts = self.progress.snapshot()["counts"]
        if self._under_limit(config, counts, "school"):
            courses = client.query_school_courses()
        if self._under_limit(config, counts, "work"):
            jobs = client.query_work_catalog().jobs
        state = self.progress.optimizer_state(values.gold)
        food_inventory = client.query_food_inventory()
        bath_inventory = client.query_bath_inventory()
        bath_item_id = (
            "2" if str(config["care"].get("bath_item", "soap")) == "bath_ball" else "1"
        )
        automatic = derive_auto_optimization_inputs(
            courses=courses,
            jobs=jobs,
            bath_items=client.query_bath_items(),
            food_count=food_inventory.biscuits,
            bath_count=bath_inventory.count(bath_item_id),
            preferred_bath_item_id=bath_item_id,
            learned_profile=self.progress.economy_profile(),
        )
        self._optimization_auto_summary = automatic.summary
        decision = choose_adaptive_plan(
            courses=courses,
            jobs=jobs,
            attribute=str(config["school"].get("attribute", "physical")),
            current_gold=values.gold,
            opening_gold=float(state.get("opening_gold", values.gold)),
            active_minutes=int(state.get("active_minutes", 0)),
            daily_active_minutes=automatic.daily_active_minutes,
            safety_floor=automatic.safety_floor,
            preserve_opening_gold=automatic.preserve_opening_gold,
            course_hunger_cost=automatic.course_hunger_cost,
            course_clean_cost=automatic.course_clean_cost,
            work_hunger_cost=automatic.work_hunger_cost,
            work_clean_cost=automatic.work_clean_cost,
            biscuit_price=automatic.biscuit_price,
            biscuit_restore=automatic.biscuit_restore,
            soap_price=automatic.soap_price,
            soap_restore=automatic.soap_restore,
        )
        self.log(automatic.summary)
        self.log(decision.explanation)
        return decision

    @staticmethod
    def _under_limit(config: dict, counts: dict, kind: str) -> bool:
        if not config[kind]["enabled"]:
            return False
        if not config[kind].get("limit_enabled", False):
            return True
        limit = int(config[kind].get("times_per_day", 0))
        return limit > 0 and counts[kind] < limit

    def _safe_or_blocked(self, config: dict, action: str, experimental: bool = False) -> bool:
        if config["safety"]["safe_mode"]:
            self.log(f"安全模式：计划执行 {action}，本轮不发送写请求")
            return True
        if experimental and not config["safety"]["allow_experimental_scene_actions"]:
            self.log(f"已阻止实验性动作 {action}；请在设置中明确开启")
            return True
        return False

    def _encourage_story_if_needed(
        self, client: NapCatClient, config: dict, kind: str | None, story_id: str
    ) -> bool:
        if kind not in {"school", "work"} or not story_id:
            return False
        if self.progress.story_was_encouraged(story_id):
            return True
        block_key = f"encourage:{story_id}"
        if self.progress.active_care_block(block_key):
            return False
        if self._safe_or_blocked(config, f"鼓励{self._action_name(kind)}中的宠物"):
            return False
        encourage = getattr(client, "encourage_story", None)
        if not callable(encourage):
            return False
        try:
            result = encourage(story_id)
        except QQPetError as exc:
            self.progress.set_care_block(block_key, str(exc), 60)
            self.log(f"鼓励暂未成功：{exc}；60s 后随任务状态重试")
            return False
        self.progress.mark_story_encouraged(story_id)
        self.progress.clear_care_block(block_key)
        # The server returns a pool of encouragement phrases; the official UI
        # displays one at a time, so keep the console concise as well.
        detail = result.toast or (result.messages[0] if result.messages else "服务器已确认")
        credit = f"，奖励积分 {result.credit}" if result.credit else ""
        self.log(f"已鼓励正在{self._action_name(kind)}的宠物{credit}：{detail}")
        self.activity(f"已鼓励宠物，正在{self._action_name(kind)}")
        return True

    def _handle_story(self, client: NapCatClient, config: dict, story: StoryStatus) -> bool:
        state = self.progress.snapshot()
        pending = state.get("pending")
        if story.story_id and self.progress.story_was_settled(story.story_id):
            if not pending:
                self.activity("上次任务已结算，正在准备下一项")
                return False
            # Some sessions keep returning the previous completed story while
            # a newly submitted task is waiting for its own story ID.  Treat
            # that stale response as no active story, so the pending guard
            # below waits instead of submitting the task again.
            self.activity("服务器仍返回上次任务，等待当前任务结果")
            story = StoryStatus()
        if story.story_id:
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
            if not story.finished:
                self._encourage_story_if_needed(client, config, kind, story.story_id)
            if story.finished and config["story"]["auto_settle_when_end_time_reached"]:
                self.activity(f"正在结算{action_name}")
                if self._safe_or_blocked(config, "结算已完成任务"):
                    return True
                settled = self._settle_and_verify(client, config, story)
                if settled and pending:
                    if pending["kind"] in {"school", "work"}:
                        minutes = max(1, (int(story.duration_seconds) + 59) // 60)
                        active = self.progress.record_activity_minutes(
                            pending["kind"], minutes
                        )
                        self.log(f"优化器已记录本次 {minutes} 分钟；今日累计 {active} 分钟")
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
                duration_minutes = int(pending.get("duration_minutes", 0) or 0)
                if pending["kind"] in {"school", "work"} and duration_minutes > 0:
                    self.progress.record_activity_minutes(
                        pending["kind"], duration_minutes
                    )
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

    def _supply_restore(self, kind: str, fallback: float) -> float:
        profile = self.progress.economy_profile().get(kind, {})
        if isinstance(profile, dict):
            observed = float(profile.get("restore", 0) or 0)
            if observed > 0:
                return observed
        return max(1.0, float(fallback))

    @staticmethod
    def _needed_supply_count(current: float, target: float, restore: float) -> int:
        missing = max(0.0, float(target) - float(current))
        return max(1, min(20, math.ceil(missing / max(1.0, float(restore)))))

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

        login_uin = client.check_connection()
        friends = client.query_friend_list()
        eligible = eligible_friends(
            friends,
            login_uin,
            str(visit_config.get("whitelist", "")),
            str(visit_config.get("exclude", "")),
        )
        try:
            live_pets = client.query_pk_friend_candidates()
        except Exception as exc:
            self.friend_progress.record_scan(len(friends), 0)
            self.log(f"每日好友宠物池读取失败：{exc}；本轮未发送访问请求")
            return
        verified_pets = current_pet_friends(friends, live_pets)
        verified_pets.pop(login_uin, None)
        for friend in eligible:
            if friend.user_id not in verified_pets and not self.friend_progress.attempted(friend.user_id):
                self.friend_progress.mark(
                    friend.user_id,
                    "no_pet",
                    detail="服务器当前宠物好友池未返回该 QQ",
                )
        candidates = tuple(
            friend
            for friend in eligible
            if friend.user_id in verified_pets
            and not self.friend_progress.attempted(friend.user_id)
        )
        limit = int(visit_config.get("max_per_day", 0))
        if limit > 0:
            summary = self.friend_progress.summary()
            used = summary["success"] + summary["already_visited"]
            candidates = candidates[: max(0, limit - used)]
        self.friend_progress.record_scan(len(friends), len(candidates))
        if config["safety"].get("safe_mode", True):
            self.log(
                f"每日好友列表已读取：共 {len(friends)} 人，当前宠物好友 "
                f"{len(verified_pets)} 人，候选 {len(candidates)} 人；安全模式未发送访问"
            )
            return
        succeeded = 0
        failed = 0
        for index, friend in enumerate(candidates):
            pet = verified_pets[friend.user_id]
            try:
                path, response, after_rules = client.visit_friend_verified(
                    friend.user_id, pet.pet_id
                )
            except Exception as exc:
                self.friend_progress.mark(
                    friend.user_id,
                    "failed",
                    pet_id=pet.pet_id,
                    detail=str(exc),
                )
                failed += 1
            else:
                detail = (
                    f"动态路径 {path[0]}/{path[1]}/{path[2]}；"
                    "手机协议已接收访问事件；"
                    f"复查规则 {after_rules.declared_count} 条"
                )
                poked = False
                if visit_config.get("poke_enabled", False):
                    try:
                        poked = bool(client.poke_friend(friend.user_id).body)
                        detail += "；踩踩已确认" if poked else "；踩踩未返回业务确认"
                    except Exception as exc:
                        poke_error = str(exc)
                        if "136202" in poke_error or "不能重复点赞" in poke_error:
                            poked = True
                            detail += "；踩踩今日已完成（服务器拒绝重复点赞）"
                        else:
                            detail += f"；踩踩失败：{poke_error}"
                # 访问与踩踩分开判定：踩踩失败不能覆盖已经验证成功的访问。
                self.friend_progress.mark(
                    friend.user_id,
                    "success",
                    pet_id=pet.pet_id,
                    detail=detail,
                    poked=poked,
                )
                succeeded += 1
            if index + 1 < len(candidates):
                minimum = float(visit_config.get("interval_min_seconds", 3))
                maximum = float(visit_config.get("interval_max_seconds", 5))
                self._stop.wait(random.uniform(minimum, max(minimum, maximum)))
        self.log(
            f"每日好友访问完成：QQ 好友 {len(friends)} 人，当前宠物好友 "
            f"{len(verified_pets)} 人，本轮成功 {succeeded} 人、失败 {failed} 人"
        )

    def _run_friend_care_if_due(
        self, client: NapCatClient, config: dict
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
        feed_enabled = bool(care.get("feed_enabled", True))
        clean_enabled = bool(care.get("clean_enabled", True))
        hunger_threshold = float(care.get("hunger_threshold", 80))
        clean_threshold = float(care.get("clean_threshold", 80))
        attempts = max(1, min(10, int(care.get("verify_attempts", 5))))
        base_delay = max(0.0, float(care.get("verify_delay_seconds", 1)))
        cooldown = float(care.get("failure_cooldown_seconds", 600))
        for target in targets:
            uin = str(target["uin"])
            pet_id = str(target["pet_id"])
            name = str(target.get("name") or uin)
            feed_block_key = f"friend_feed:{uin}"
            wash_block_key = f"friend_wash:{uin}"
            info_block_key = f"friend_info:{uin}"
            if self.progress.active_care_block(info_block_key):
                continue
            friend_config = copy.deepcopy(config)
            friend_config["account"]["pet_id"] = pet_id
            try:
                friend_client = self.client_factory(friend_config)
                current = client.query_friend_pet_values(uin, pet_id)
            except Exception as exc:
                self.progress.set_care_block(
                    info_block_key, f"好友宠物信息读取失败：{exc}", cooldown
                )
                self.log(f"好友照顾检查失败：{name}（QQ {uin}）：{exc}")
                continue
            self.progress.clear_care_block(info_block_key)
            self.log(
                f"好友照顾检查：{name}（QQ {uin}）饥饿度 "
                f"{current.hunger:.1f}/100，清洁 {current.clean:.1f}/100"
                f"（好友宠物信息接口）"
            )

            if current.hunger >= hunger_threshold:
                self.progress.clear_care_block(feed_block_key)
            elif feed_enabled and not self.progress.active_care_block(feed_block_key):
                max_feeds = max(
                    1,
                    min(20, int(care.get("max_feeds_per_friend_per_check", 10))),
                )
                feeds_this_check = 0
                while (
                    current.hunger < hunger_threshold
                    and feeds_this_check < max_feeds
                ):
                    feed_restore = self._supply_restore(
                        "food", float(config["optimization"].get("biscuit_restore", 10))
                    )
                    batch_count = min(
                        max_feeds - feeds_this_check,
                        self._needed_supply_count(
                            current.hunger, hunger_threshold, feed_restore
                        ),
                    )
                    self.activity(
                        f"好友 {name} 饥饿度 {current.hunger:.1f}，"
                        f"正在一次投喂 {batch_count} 份"
                    )
                    if self._safe_or_blocked(config, f"给好友 {name} 喂食"):
                        return "friend_feed_blocked"
                    try:
                        # 喂食无已验证数量字段，因此同批连续发送，批次结束后只刷新一次。
                        for _ in range(batch_count):
                            friend_client.feed()
                    except Exception as exc:
                        detail = str(exc)
                        if "金币" in detail and any(
                            word in detail for word in ("不足", "不够", "余额", "缺少")
                        ):
                            self.progress.set_care_block(
                                feed_block_key, f"好友投喂停止：金币不足：{exc}", cooldown
                            )
                            self.log(
                                f"好友连续投喂已停止：{name}（QQ {uin}）金币不足；"
                                f"当前饥饿度 {current.hunger:.1f}"
                            )
                            return "friend_feed_insufficient_gold"
                        self.progress.set_care_block(
                            feed_block_key, f"好友喂食请求失败：{exc}", cooldown
                        )
                        self.log(f"好友自动喂食失败：{name}（QQ {uin}）：{exc}")
                        return "friend_feed_failed"

                    after = current
                    confirmed = False
                    last_read_error = ""
                    for attempt in range(1, attempts + 1):
                        self._stop.wait(base_delay * attempt)
                        try:
                            # 重新调用 0x976c_0 GetOtherUserPet，禁止使用通用状态缓存。
                            after = client.query_friend_pet_values(uin, pet_id)
                            last_read_error = ""
                            if after.hunger > current.hunger:
                                confirmed = True
                                break
                        except Exception as exc:
                            last_read_error = str(exc)
                        if attempt < attempts:
                            detail = (
                                f"（读取异常：{last_read_error}）"
                                if last_read_error
                                else ""
                            )
                            self.log(
                                f"好友宠物信息暂未刷新：{name}（QQ {uin}）饥饿度仍为 "
                                f"{after.hunger:.1f}；继续重新调用好友信息接口 "
                                f"{attempt}/{attempts}{detail}"
                            )

                    if not confirmed:
                        self.progress.set_care_block(
                            feed_block_key, "好友喂食已发送，等待好友宠物信息同步", cooldown
                        )
                        self.log(
                            f"好友喂食已发送但好友信息尚未同步：{name}（QQ {uin}）"
                            f"饥饿度仍为 {after.hunger:.1f}；本轮不会继续投喂，"
                            f"{int(cooldown)} 秒后重新检查"
                        )
                        return "friend_feed_pending"

                    feeds_this_check += batch_count
                    count = self.progress.increment("friend_feed", batch_count)
                    self.log(
                        f"好友自动喂食已由好友宠物信息接口验证：{name}（QQ {uin}）"
                        f"饥饿度 {current.hunger:.1f}→{after.hunger:.1f}；"
                        f"本批使用 {batch_count} 份，今日好友喂食 {count} 份"
                    )
                    current = after

                if current.hunger >= hunger_threshold:
                    self.progress.clear_care_block(feed_block_key)
                    self.activity(f"好友 {name} 投喂完成，饥饿度已达到配置值")
                    return "friend_feed"

                self.progress.set_care_block(
                    feed_block_key, "达到单轮连续投喂安全上限", cooldown
                )
                self.log(
                    f"好友连续投喂达到单轮上限 {max_feeds} 次：{name}（QQ {uin}）；"
                    f"当前饥饿度 {current.hunger:.1f}，{int(cooldown)} 秒后重新检查"
                )
                return "friend_feed_partial"

            if current.clean >= clean_threshold:
                self.progress.clear_care_block(wash_block_key)
                continue
            if not clean_enabled or self.progress.active_care_block(wash_block_key):
                continue

            max_washes = max(
                1,
                min(20, int(care.get("max_washes_per_friend_per_check", 10))),
            )
            bath_choice = str(care.get("bath_item", "soap"))
            bath_item_id = "2" if bath_choice == "bath_ball" else "1"
            bath_item_name = "沐浴球" if bath_choice == "bath_ball" else "香皂片"
            washes_this_check = 0
            while current.clean < clean_threshold and washes_this_check < max_washes:
                bath_restore = self._supply_restore(
                    "bath", float(config["optimization"].get("soap_restore", 10))
                )
                batch_count = min(
                    max_washes - washes_this_check,
                    self._needed_supply_count(current.clean, clean_threshold, bath_restore),
                )
                self.activity(
                    f"好友 {name} 清洁 {current.clean:.1f}，正在一次使用 "
                    f"{batch_count} 个{bath_item_name}清洁"
                )
                if self._safe_or_blocked(config, f"给好友 {name} 清洁"):
                    return "friend_wash_blocked"
                try:
                    # 好友 petId 已写入 friend_client，pet_uin 明确指定目标好友。
                    friend_client.use_bath_item(bath_item_id, uin, count=batch_count)
                except Exception as exc:
                    detail = str(exc)
                    reason = (
                        f"好友清洁停止：金币或洗护用品不足：{exc}"
                        if any(word in detail for word in ("金币", "不足", "不够", "缺少"))
                        else f"好友清洁请求失败：{exc}"
                    )
                    self.progress.set_care_block(wash_block_key, reason, cooldown)
                    self.log(f"好友自动清洁失败：{name}（QQ {uin}）：{exc}")
                    return "friend_wash_failed"

                after = current
                confirmed = False
                last_read_error = ""
                for attempt in range(1, attempts + 1):
                    self._stop.wait(base_delay * attempt)
                    try:
                        # 成功只按重新读取到的好友清洁值上涨判定，禁止用库存推断。
                        after = client.query_friend_pet_values(uin, pet_id)
                        last_read_error = ""
                        if after.clean > current.clean:
                            confirmed = True
                            break
                    except Exception as exc:
                        last_read_error = str(exc)
                    if attempt < attempts:
                        detail = (
                            f"（读取异常：{last_read_error}）" if last_read_error else ""
                        )
                        self.log(
                            f"好友宠物信息暂未刷新：{name}（QQ {uin}）清洁仍为 "
                            f"{after.clean:.1f}；继续重新调用好友信息接口 "
                            f"{attempt}/{attempts}{detail}"
                        )

                if not confirmed:
                    self.progress.set_care_block(
                        wash_block_key, "好友清洁已发送，等待好友宠物信息同步", cooldown
                    )
                    self.log(
                        f"好友清洁已发送但好友信息尚未同步：{name}（QQ {uin}）"
                        f"清洁仍为 {after.clean:.1f}；本轮不会继续清洁，"
                        f"{int(cooldown)} 秒后重新检查"
                    )
                    return "friend_wash_pending"

                washes_this_check += batch_count
                count = self.progress.increment("friend_wash", batch_count)
                self.log(
                    f"好友自动清洁已由好友宠物信息接口验证：{name}（QQ {uin}）"
                    f"清洁 {current.clean:.1f}→{after.clean:.1f}；"
                    f"本批使用 {batch_count} 个，今日好友清洁 {count} 个"
                )
                current = after

            if current.clean >= clean_threshold:
                self.progress.clear_care_block(wash_block_key)
                self.activity(f"好友 {name} 清洁完成，清洁值已达到配置值")
                return "friend_wash"

            self.progress.set_care_block(
                wash_block_key, "达到单轮连续清洁安全上限", cooldown
            )
            self.log(
                f"好友连续清洁达到单轮上限 {max_washes} 次：{name}（QQ {uin}）；"
                f"当前清洁 {current.clean:.1f}，{int(cooldown)} 秒后重新检查"
            )
            return "friend_wash_partial"
        return None

    def run_once(self) -> str | None:
        self.activity("正在检查宠物状态")
        config = self.config_store.data
        if self.progress.rollover():
            self.log("检测到新的一天，昨日次数已归档，今日计数清零")
        client = self.client_factory(config)
        self._verify_login_session(client, config)
        self._scan_friends_if_due(client, config)
        values = client.query_values()
        story = client.query_story()
        preview_adaptive: AdaptiveDecision | None = None
        optimization_enabled = bool(config.get("optimization", {}).get("enabled", False))
        if optimization_enabled and time.monotonic() >= self._next_optimization_probe_at:
            # Preload read-only economics even while another story or side task
            # is active, so the settings page never waits for the next idle slot.
            try:
                preview_adaptive = self._adaptive_decision(client, config, values)
                self._next_optimization_probe_at = time.monotonic() + 1800
            except (QQPetError, ValueError, RuntimeError, AttributeError) as exc:
                self._optimization_auto_summary = f"自动读取失败：{exc}；60 秒后重试"
                self._next_optimization_probe_at = time.monotonic() + 60
                self.log(f"动态优化预读取失败：{exc}")
        elif not optimization_enabled:
            self._optimization_auto_summary = "动态收益优化未启用"
        state = self.progress.snapshot()
        state["friend_visit_summary"] = self.friend_progress.summary()
        state["friend_care_summary"] = {
            "enabled": bool(config["friend_care"].get("enabled", False)),
            "targets": len(config["friend_care"].get("targets", [])),
            "feeds": int(state["counts"].get("friend_feed", 0)),
            "washes": int(state["counts"].get("friend_wash", 0)),
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
        state["optimization_auto_summary"] = self._optimization_auto_summary
        if self.status_callback:
            bath_inventory = client.query_bath_inventory()
            state["bath_inventory"] = {
                "soap": bath_inventory.soap,
                "bath_ball": bath_inventory.bath_ball,
            }
            display_story = (
                StoryStatus()
                if story.story_id and self.progress.story_was_settled(story.story_id)
                else story
            )
            self.status_callback(values, display_story, state)
        value_source = "手机协议" if getattr(client, "last_values_source", "desktop") == "mobile" else "桌面协议"
        self.log(
            f"状态（{value_source}）：金币 {values.gold:.2f}，心情 {values.feel:.1f}，体力 {values.hunger:.1f}，"
            f"清洁 {values.clean:.1f}，饼干 {inventory.biscuits}，虾仁 {inventory.shrimp}，"
            f"今日 {state['counts']}"
        )

        care = config["care"]
        if care["enabled"] and values.hunger < float(care["hunger_threshold"]):
            if self._care_blocked("feed"):
                self.activity("等待喂食条件恢复")
                return "feed_blocked"
            if not self._safe_or_blocked(config, "喂食"):
                food_choice = str(care.get("food_item", "biscuit"))
                food_name = "虾仁" if food_choice == "shrimp" else "饼干"
                food_item = None
                if food_choice == "shrimp":
                    food_item = next(
                        (
                            item
                            for item in client.query_food_items()
                            if item.food_id == "3" or "虾仁" in item.name
                        ),
                        None,
                    )
                # Empty foodId is the verified default biscuit path. Shrimp
                # always uses the exact server-provided foodId.
                food_id = food_item.food_id if food_item else ""
                food_count = (
                    food_item.balance
                    if food_item is not None
                    else (inventory.shrimp if food_choice == "shrimp" else inventory.biscuits)
                )
                if food_choice == "shrimp" and food_item is None:
                    self._block_care(config, "feed", "服务器未下发虾仁 foodId，无法安全发送虾仁喂食")
                    self.activity("虾仁接口目录暂不可用")
                    return "feed_unavailable"
                food_restore = self._supply_restore(
                    "food", float(config["optimization"].get("biscuit_restore", 10))
                )
                use_count = self._needed_supply_count(
                    values.hunger, float(care["hunger_threshold"]), food_restore
                )
                if food_count < use_count:
                    if not care["auto_buy_supplies"]:
                        if food_count <= 0:
                            self.activity("缺少食物，自动购买未开启")
                            self._block_care(config, "feed", f"{food_name}不足，自动购买已关闭")
                            return "feed_unavailable"
                        use_count = food_count
                    elif food_choice == "shrimp":
                        if food_count <= 0:
                            self._block_care(
                                config,
                                "feed",
                                "虾仁不足；当前金币购买接口只支持饼干，未发送错误购买指令",
                            )
                            self.activity("虾仁不足，暂无法自动兑换")
                            return "feed_unavailable"
                        use_count = food_count
                        self.log(
                            f"虾仁仅有 {food_count} 个，低于本轮计划 {use_count} 个；"
                            f"将一次使用现有库存并在刷新后重新计算"
                        )
                    else:
                        self.activity("正在购买本轮所需食物")
                        shortage = max(0, use_count - food_count)
                        buy_count = max(shortage, int(care["food_purchase_count"]))
                        before_count = inventory.biscuits
                        purchase = client.buy_food(buy_count)
                        inventory = client.query_food_inventory()
                        if purchase.bought <= 0 and inventory.biscuits <= before_count:
                            self._block_care(config, "feed", "金币购买饼干未到账")
                            self.activity("购买食物失败，等待重试")
                            return "feed_unavailable"
                        bought = purchase.bought or max(0, inventory.biscuits - before_count)
                        if bought > 0 and purchase.cost_gold > 0:
                            self.progress.record_supply_observation(
                                "food", price=purchase.cost_gold / bought
                            )
                        food_count = inventory.biscuits
                        use_count = min(use_count, food_count)
                        self.log(
                            f"饼干不足，已用金币购买 {purchase.bought or buy_count} 个，"
                            f"花费 {purchase.cost_gold}，当前饼干 {inventory.biscuits}"
                        )
                if use_count <= 0:
                    self._block_care(config, "feed", f"{food_name}库存不足")
                    return "feed_unavailable"
                self.activity(
                    f"正在按体力缺口一次使用 {use_count} 个{food_name}"
                )
                # 喂食封包尚未发现可靠的数量字段；同一批次连续发送所需份数，
                # 全部发送后仅刷新一次状态，避免逐份查询造成延迟和误判。
                for _ in range(use_count):
                    client.feed(food_id) if food_id else client.feed()
                self._verify_delay(config)
                after = client.query_values()
                inventory_after = client.query_food_inventory()
                after_food_item = None
                if food_choice == "shrimp":
                    after_food_item = next(
                        (
                            item
                            for item in client.query_food_items()
                            if item.food_id == food_id
                        ),
                        None,
                    )
                inventory_selected_after = (
                    after_food_item.balance
                    if after_food_item is not None
                    else (
                        inventory_after.shrimp
                        if food_choice == "shrimp"
                        else inventory_after.biscuits
                    )
                )
                if after.hunger > values.hunger or inventory_selected_after < food_count:
                    consumed = max(1, food_count - inventory_selected_after)
                    if after.hunger > values.hunger:
                        self.progress.record_supply_observation(
                            "food", restore=(after.hunger - values.hunger) / consumed
                        )
                    self.progress.clear_care_block("feed")
                    self.progress.increment("feed", consumed)
                    self.log(
                        f"体力不足，已一次使用 {consumed} 个{food_name}并验证成功："
                        f"{values.hunger:.1f}→{after.hunger:.1f}，剩余{food_name} "
                        f"{inventory_selected_after}"
                    )
                    self.activity("喂食完成，等待下一轮")
                else:
                    self._block_care(config, "feed", f"{food_name}喂食响应成功但体力和库存均未变化")
                    self.activity("喂食未生效，等待重试")
            return "feed"
        if care["enabled"] and values.clean < float(care["clean_threshold"]):
            if self._care_blocked("wash"):
                self.activity("等待洗澡条件恢复")
                return "wash_blocked"
            if not self._safe_or_blocked(config, "洗澡"):
                bath_inventory = client.query_bath_inventory()
                bath_choice = str(care.get("bath_item", "soap"))
                bath_item_id = "2" if bath_choice == "bath_ball" else "1"
                bath_item_name = "沐浴球" if bath_choice == "bath_ball" else "香皂片"
                query_bath_items = getattr(client, "query_bath_items", None)
                bath_catalog_item = next(
                    (
                        item
                        for item in (query_bath_items() if callable(query_bath_items) else ())
                        if item.item_id == bath_item_id
                    ),
                    None,
                )
                if bath_catalog_item is not None:
                    self.progress.record_supply_observation(
                        "bath",
                        price=float(bath_catalog_item.gold_price),
                        restore=float(bath_catalog_item.clean_gain),
                    )
                bath_count = bath_inventory.count(bath_item_id)
                bath_restore = (
                    float(bath_catalog_item.clean_gain)
                    if bath_catalog_item is not None and bath_catalog_item.clean_gain > 0
                    else self._supply_restore(
                        "bath", float(config["optimization"].get("soap_restore", 10))
                    )
                )
                use_count = self._needed_supply_count(
                    values.clean, float(care["clean_threshold"]), bath_restore
                )
                if bath_count < use_count:
                    if not care["auto_buy_supplies"]:
                        if bath_count <= 0:
                            self.activity("缺少洗护用品，自动购买未开启")
                            self._block_care(config, "wash", f"{bath_item_name}不足，自动购买已关闭")
                            return "wash_unavailable"
                        use_count = bath_count
                    else:
                        self.activity("正在购买本轮所需洗护用品")
                        shortage = max(0, use_count - bath_count)
                        buy_count = max(shortage, int(care["soap_purchase_count"]))
                        purchase = client.buy_bath_item(bath_item_id, buy_count)
                        after_purchase = client.query_bath_inventory()
                        if (
                            not purchase.succeeded
                            and after_purchase.count(bath_item_id) <= bath_count
                        ):
                            self._block_care(
                                config,
                                "wash",
                                f"金币购买{bath_item_name}未成功（result={purchase.result}）",
                            )
                            self.activity("购买洗护用品失败，等待重试")
                            return "wash_unavailable"
                        bath_inventory = after_purchase
                        bath_count = bath_inventory.count(bath_item_id)
                        use_count = min(use_count, bath_count)
                        self.log(
                            f"{bath_item_name}不足，已用金币购买 {buy_count} 个，"
                            f"当前{bath_item_name} {bath_count}"
                        )
                if use_count <= 0:
                    self._block_care(config, "wash", f"{bath_item_name}库存不足")
                    return "wash_unavailable"
                self.activity(
                    f"正在按清洁缺口一次使用 {use_count} 个{bath_item_name}"
                )
                client.use_bath_item(bath_item_id, count=use_count)
                self._verify_delay(config)
                after = client.query_values()
                bath_after = client.query_bath_inventory()
                if after.clean > values.clean or bath_after.count(bath_item_id) < bath_count:
                    consumed = max(1, bath_count - bath_after.count(bath_item_id))
                    if after.clean > values.clean:
                        self.progress.record_supply_observation(
                            "bath", restore=(after.clean - values.clean) / consumed
                        )
                    self.progress.clear_care_block("wash")
                    self.progress.increment("wash", consumed)
                    self.log(
                        f"清洁不足，已一次使用 {consumed} 个{bath_item_name}并验证成功："
                        f"{values.clean:.1f}→{after.clean:.1f}，"
                        f"剩余{bath_item_name} {bath_after.count(bath_item_id)}"
                    )
                    self.activity("洗澡完成，等待下一轮")
                else:
                    self._block_care(
                        config,
                        "wash",
                        f"洗澡响应成功但清洁值和{bath_item_name}库存均未变化",
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
        adaptive: AdaptiveDecision | None = preview_adaptive
        # Adventure keeps its configured priority. School/work are selected by
        # the resource-aware planner whenever optimization is enabled.
        if action != "adventure" and config.get("optimization", {}).get("enabled", False):
            try:
                if adaptive is None:
                    adaptive = self._adaptive_decision(client, config, values)
                action = (
                    "school" if adaptive.action == "study"
                    else "work" if adaptive.action == "work"
                    else None
                )
            except (QQPetError, ValueError, RuntimeError, AttributeError) as exc:
                self.log(f"动态优化目录读取失败，保留原调度逻辑：{exc}")
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
            # 用户固定课程优先于优化器建议（与打工分支一致）。
            user_course = int(config["school"].get("course_sub_event", 0))
            user_fixed_course = bool(user_course)
            if user_fixed_course:
                preferred_course = user_course
            else:
                preferred_course = (
                    adaptive.course_sub_event
                    if adaptive and adaptive.course_sub_event
                    else 0
                )
            try:
                result = client.start_school(option, preferred_course)
            except (QQPetEmptyResponse, QQPetConnectionError) as exc:
                if exc.command_name != "OidbSvcTrpcTcp.0x975e_1":
                    raise
                self.progress.set_pending("school")
                self.log(
                    "开课请求返回空响应，发送结果暂不确定；已进入待确认状态，"
                    "后续只查询服务器任务状态，不会重复开课"
                )
                self.activity("开课结果待确认，正在等待服务器状态")
                return action
            course = result.course
            self.progress.set_pending(
                "school",
                duration_minutes=max(1, (course.duration_seconds + 59) // 60),
                activity_name=course.name,
            )
            if preferred_course and course.sub_event_type != preferred_course:
                refreshed = self.config_store.data
                refreshed["school"]["course_sub_event"] = 0
                self.config_store.save(refreshed)
                self.log(
                    f"原课程 {preferred_course} 已不属于当前学习阶段，"
                    f"已刷新并自动改选“{course.name}”"
                )
                preferred_course = 0
            if result.story_id:
                self._encourage_story_if_needed(
                    client, config, "school", result.story_id
                )
            response_story = f"，storyId={result.story_id}" if result.story_id else ""
            if preferred_course and user_fixed_course:
                selection = "指定（用户固定）"
            elif preferred_course:
                selection = "优化器建议"
            else:
                selection = "当前阶段最短时长"
            self.log(
                f"已选择{selection}的{course.reward}课程“{course.name}”"
                f"（{course.duration}），真实开课指令已发送{response_story}；"
                "等待状态接口确认倒计时"
            )
            self.activity(f"已开课：{course.name}，等待倒计时确认")
            return action
        if action == "work":
            requirement_block = self.progress.active_care_block("work_requirements")
            if requirement_block:
                remaining = max(
                    0,
                    int(
                        float(requirement_block["until"])
                        - datetime.now().astimezone().timestamp()
                    ),
                )
                self.log(f"打工资格暂不可用；{remaining}s 后重新读取职业规则")
                self.activity("等待宠物满足打工职业要求")
                return "work_blocked"
            self.activity("正在获取开放职业和岗位")
            # 用户显式设置的固定岗位拥有最高优先级；优化器的建议只是「自动」层，
            # 只有在用户未固定岗位（career_type 与 job_sub_event 均为 0）时才采用，
            # 避免优化器旁路掉用户在设置里明确选择的岗位。
            user_career = int(config["work"].get("career_type", 0))
            user_job = int(config["work"].get("job_sub_event", 0))
            user_fixed = bool(user_career or user_job)
            if user_fixed:
                career_type = user_career
                preferred_job = user_job
            else:
                career_type = (
                    adaptive.career_type
                    if adaptive and adaptive.career_type
                    else 0
                )
                preferred_job = (
                    adaptive.job_sub_event
                    if adaptive and adaptive.job_sub_event
                    else 0
                )
            strategy = config["work"].get("strategy", "shortest_duration")
            hired_friend = self._select_work_hire(client, config)
            hired_uin = hired_friend.user_id if hired_friend else ""
            hired_pet_id = hired_friend.pet_id if hired_friend else ""
            selected_job = None
            if preferred_job:
                try:
                    selected_job = client.select_work_job(
                        career_type,
                        preferred_job,
                        strategy,
                        hired_pet_id,
                    )
                except QQPetError:
                    try:
                        selected_job = client.select_work_job(
                            0,
                            0,
                            strategy,
                            hired_pet_id,
                        )
                    except WorkEligibilityError as exc:
                        cooldown = max(
                            300.0,
                            float(config["care"]["failure_cooldown_seconds"]),
                        )
                        self.progress.set_care_block(
                            "work_requirements", str(exc), cooldown
                        )
                        self.log(
                            f"{exc}；本轮没有符合条件的岗位，"
                            f"{int(cooldown)}s 后重新读取"
                        )
                        self.activity("暂无符合宠物条件的打工岗位")
                        return "work_unavailable"
                    self.log(
                        f"指定岗位 {preferred_job} 当前不可用，"
                        "已自动刷新并回退到服务器最短时长岗位"
                    )
                    refreshed = self.config_store.data
                    refreshed["work"]["career_type"] = 0
                    refreshed["work"]["job_sub_event"] = 0
                    refreshed["work"]["strategy"] = "shortest_duration"
                    self.config_store.save(refreshed)
                    preferred_job = 0
            start_career = selected_job.career_type if selected_job else career_type
            start_job = selected_job.sub_event_type if selected_job else preferred_job
            rejected_jobs: list[int] = []
            try:
                while True:
                    try:
                        result = client.start_work(
                            start_career,
                            start_job,
                            strategy,
                            hired_uin,
                            hired_pet_id,
                        )
                        break
                    except WorkEligibilityError as exc:
                        if exc.job is None:
                            raise
                        rejected_jobs.append(exc.job.sub_event_type)
                        self.log(
                            f"岗位“{exc.job.name}”被服务器判定为尚未满足参与要求，"
                            "正在尝试下一可用岗位"
                        )
                        fallback = client.select_work_job(
                            0,
                            0,
                            strategy,
                            hired_pet_id,
                            tuple(rejected_jobs),
                        )
                        start_career = fallback.career_type
                        start_job = fallback.sub_event_type
                        preferred_job = 0
                    except QQPetError as exc:
                        if not hired_uin or not self._is_work_hire_unavailable(exc):
                            raise
                        self.progress.mark_work_hire_unavailable(hired_uin)
                        tired_name = (
                            hired_friend.nickname
                            or hired_friend.pet_name
                            or hired_friend.user_id
                            if hired_friend
                            else hired_uin
                        )
                        self.log(
                            f"雇佣好友 {tired_name} 今日已不可再雇佣；"
                            "已加入今日跳过名单，正在用同一岗位无好友开工"
                        )
                        hired_uin = ""
                        hired_pet_id = ""
                        result = client.start_work(
                            start_career,
                            start_job,
                            strategy,
                            "",
                            "",
                        )
                        break
            except WorkEligibilityError as exc:
                cooldown = max(300.0, float(config["care"]["failure_cooldown_seconds"]))
                self.progress.set_care_block(
                    "work_requirements", str(exc), cooldown
                )
                self.log(
                    f"{exc}；本轮没有符合条件的岗位，{int(cooldown)}s 后重新读取"
                )
                self.activity("暂无符合宠物条件的打工岗位")
                return "work_unavailable"
            except (QQPetEmptyResponse, QQPetConnectionError) as exc:
                if exc.command_name != "OidbSvcTrpcTcp.0x975e_1":
                    raise
                self.progress.set_pending("work")
                self.log(
                    "开工请求返回空响应，发送结果暂不确定；已进入待确认状态，"
                    "后续只查询服务器任务状态，不会重复开工"
                )
                self.activity("开工结果待确认，正在等待服务器状态")
                return action
            job = result.job
            self.progress.set_pending(
                "work",
                duration_minutes=max(1, (job.duration_seconds + 59) // 60),
                activity_name=job.name,
            )
            self.progress.clear_care_block("work_requirements")
            if result.story_id:
                self._encourage_story_if_needed(client, config, "work", result.story_id)
            response_story = f"，storyId={result.story_id}" if result.story_id else ""
            # 来源区分：用户固定岗位 vs 优化器建议 vs 最短时长（均未固定时）。
            if preferred_job and user_fixed:
                selection = "指定（用户固定）"
            elif preferred_job:
                selection = "优化器建议"
            else:
                selection = "时长最短"
            friend_name = (
                hired_friend.nickname or hired_friend.pet_name or hired_friend.user_id
                if hired_friend
                else ""
            )
            friend_text = f"，已雇佣好友 {friend_name}" if result.hired_friend else ""
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
            try:
                result = client.start_adventure(preferred_name)
            except (QQPetEmptyResponse, QQPetConnectionError) as exc:
                if exc.command_name != "OidbSvcTrpcTcp.0x975e_1":
                    raise
                self.progress.set_pending("adventure")
                self.log(
                    "冒险请求返回空响应，发送结果暂不确定；已进入待确认状态，"
                    "后续只查询服务器任务状态，不会重复开始冒险"
                )
                self.activity("冒险结果待确认，正在等待服务器状态")
                return action
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
            except QQPetConnectionError as exc:
                self.activity("接口连接异常，正在自动重连")
                self.log(f"接口错误：{exc}")
                self._record_failure(f"接口错误：{exc}")
                if self._reconnect_until_ready():
                    continue
            except QQPetError as exc:
                self.activity("服务器暂时未返回结果，等待下一轮重试")
                self.log(f"接口错误：{exc}")
                self._record_failure(f"接口错误：{exc}")
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
        mobile = config["mobile_protocol"]
        if not bool(mobile.get("auto_reconnect", True)):
            self.activity("接口连接异常，自动重连未开启")
            return False
        delay = max(0.1, float(mobile.get("reconnect_initial_seconds", 3)))
        while not self._stop.is_set():
            config = self.config_store.data
            mobile = config["mobile_protocol"]
            maximum = max(delay, float(mobile.get("reconnect_max_seconds", 60)))
            self.activity(f"接口已断开，{delay:g} 秒后自动重连")
            self.log(f"等待 {delay:g} 秒后探测手机 QQ 协议会话")
            if self._stop.wait(delay):
                return False
            try:
                client = self.client_factory(config)
                uin = self._verify_login_session(client, config)
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
            self.log(f"手机 QQ 协议登录会话已恢复：QQ {uin}；将从下一轮继续，不重发超时指令")
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
