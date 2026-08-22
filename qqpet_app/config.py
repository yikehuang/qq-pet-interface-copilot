from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "connection": {
        "mode": "legacy_mobile_bridge",
    },
    "standalone_protocol": {
        "enabled": True,
        "endpoint": "http://127.0.0.1:17890",
        "timeout_seconds": 10,
        "auto_start": True,
        "host_executable": "",
    },
    "napcat": {
        "url": "",
        "token": "",
        "timeout_seconds": 5,
        "auto_reconnect": False,
        "reconnect_initial_seconds": 3,
        "reconnect_max_seconds": 60,
    },
    "mobile_protocol": {
        "enabled": True,
        "endpoint": "127.0.0.1:27042",
        "process_name": "com.tencent.mobileqq",
        "adb_serial": "127.0.0.1:16416",
        "adb_path": "",
        "persistent_connection": True,
        "prepare_on_scheduler_start": True,
        "auto_reconnect": True,
        "reconnect_initial_seconds": 3,
        "reconnect_max_seconds": 60,
    },
    "account": {
        "uin": "YOUR_QQ_UIN",
        "pet_id": "YOUR_PET_ID",
    },
    "scheduler": {
        "interval_seconds": 15,
        "coin_threshold": 500,
    },
    "optimization": {
        "enabled": False,
        "daily_active_minutes": 1440,
        "safety_floor": 200,
        "preserve_opening_gold": True,
        "course_hunger_cost": 10,
        "course_clean_cost": 4,
        "work_hunger_cost": 4,
        "work_clean_cost": 2,
        "biscuit_price": 5,
        "biscuit_restore": 10,
        "soap_price": 2,
        "soap_restore": 10,
    },
    "school": {
        "enabled": True,
        "attribute": "physical",
        "course_sub_event": 0,
        "limit_enabled": False,
        "times_per_day": 20,
    },
    "work": {
        "enabled": True,
        "attribute": "culture",
        "career_type": 0,
        "job_sub_event": 0,
        "strategy": "shortest_duration",
        "limit_enabled": False,
        "times_per_day": 20,
        "employ_friend": True,
        "hire_mode": "auto",
        "hire_friend_uin": "",
        "hire_friend_pet_id": "",
        "hire_friend_name": "",
    },
    "adventure": {
        "enabled": True,
        "option_name": "",
        "maximize_gold": True,
        "recall_lower_reward": True,
        "limit_enabled": False,
        "start_time": "20:00",
        "times_per_day": 0,
    },
    "pk": {
        "enabled": False,
        "start_time": "00:00",
        "max_per_day": 10,
        "opponent_mode": "all_friends",
        "friend_whitelist": "",
        "friend_exclude": "",
        "friend_refresh_seconds": 1800,
        "per_friend_limit": 3,
        "opponent_uin": "",
        "opponent_pet_id": "",
        "opponent_name": "",
        "opponent_power": 0,
        "only_weaker": True,
        "minimum_hunger": 80,
        "minimum_clean": 80,
        "wait_seconds": 9,
        "retry_cooldown_seconds": 300,
    },
    "friend_visits": {
        "enabled": False,
        "start_time": "21:00",
        "max_per_day": 20,
        "interval_min_seconds": 3,
        "interval_max_seconds": 5,
        "poke_enabled": False,
        "whitelist": "",
        "exclude": "",
    },
    "friend_care": {
        "enabled": False,
        "feed_enabled": True,
        "clean_enabled": True,
        "food_item": "auto",
        "auto_buy_supplies": True,
        "food_purchase_count": 10,
        "bath_purchase_count": 10,
        "check_interval_seconds": 60,
        "hunger_threshold": 80,
        "clean_threshold": 80,
        "bath_item": "auto",
        "verify_delay_seconds": 1,
        "verify_attempts": 5,
        "max_feeds_per_friend_per_check": 10,
        "max_washes_per_friend_per_check": 10,
        "failure_cooldown_seconds": 600,
        "targets": [],
    },
    "care": {
        "enabled": True,
        "hunger_threshold": 80,
        "clean_threshold": 80,
        "auto_buy_supplies": True,
        "food_item": "biscuit",
        "bath_item": "soap",
        "food_purchase_count": 10,
        "soap_purchase_count": 10,
        "verify_delay_seconds": 1,
        "failure_cooldown_seconds": 3600,
    },
    "story": {
        "recall_check_seconds": 15,
        "employed_recall_mode": "best_split",
        "start_confirm_seconds": 45,
        "settle_retry_seconds": 60,
        "auto_settle_when_end_time_reached": True,
    },
    "notifications": {
        "enabled": False,
        "failure_threshold": 3,
        "cooldown_seconds": 1800,
        "send_recovery": True,
        "windows_toast": True,
        "bark": {"enabled": False, "device_key": "", "base_url": "https://api.day.app"},
        "pushplus": {"enabled": False, "token": "", "topic": ""},
        "serverchan": {"enabled": False, "sendkey": ""},
        "smtp": {"enabled": False, "host": "", "port": 465, "user": "", "password": "", "from": "", "to": "", "ssl": True, "starttls": False},
        "webhook": {"enabled": False, "url": ""},
    },
    "safety": {
        "safe_mode": True,
        "allow_experimental_scene_actions": False,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _normalize(config: dict[str, Any]) -> dict[str, Any]:
    # Migrate releases that only supported highest_total. The current product
    # policy always favours more short runs over one long run.
    if config.get("work", {}).get("strategy") == "highest_total":
        config["work"]["strategy"] = "shortest_duration"
    return config


def _migrate_loaded(config: dict[str, Any]) -> dict[str, Any]:
    """Preserve legacy daily-limit behavior before defaults are merged."""
    migrated = copy.deepcopy(config)
    school = migrated.get("school")
    if isinstance(school, dict) and "limit_enabled" not in school:
        # Older releases deliberately ignored school.times_per_day. Keep those
        # users unlimited until they explicitly enable the new switch.
        school["limit_enabled"] = False
    work = migrated.get("work")
    if isinstance(work, dict) and "limit_enabled" not in work:
        # Work used 0=unlimited and a positive number=limited before the UI had
        # an explicit switch, so retain that behavior during upgrade.
        work["limit_enabled"] = int(work.get("times_per_day", 0) or 0) > 0
    adventure = migrated.get("adventure")
    if isinstance(adventure, dict) and "limit_enabled" not in adventure:
        # Adventure has no verified daily server-side count limit. Older local
        # defaults used 3, so migrate them to unlimited unless explicitly enabled.
        adventure["limit_enabled"] = False
    # Older builds accepted values above the mobile packet's 1-99 range. Clamp
    # them during upgrade; new saves are rejected by validation instead.
    for section, key in (
        ("care", "food_purchase_count"),
        ("care", "soap_purchase_count"),
        ("friend_care", "food_purchase_count"),
        ("friend_care", "bath_purchase_count"),
    ):
        values = migrated.get(section)
        if isinstance(values, dict) and key in values:
            values[key] = max(1, min(99, int(values[key])))
    return migrated


class ConfigStore:
    """config.yaml 使用 JSON 语法；JSON 本身是合法的 YAML 1.2。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._mtime_ns = -1
        self._config = copy.deepcopy(DEFAULT_CONFIG)
        if not self.path.exists():
            self.save(self._config)
        self.reload(force=True)

    @property
    def data(self) -> dict[str, Any]:
        self.reload()
        return copy.deepcopy(self._config)

    def reload(self, force: bool = False) -> bool:
        mtime = self.path.stat().st_mtime_ns
        if not force and mtime == self._mtime_ns:
            return False
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("config.yaml 顶层必须是对象")
        self._config = _normalize(_merge(DEFAULT_CONFIG, _migrate_loaded(loaded)))
        self._validate(self._config)
        self._mtime_ns = mtime
        return True

    def save(self, config: dict[str, Any]) -> None:
        merged = _normalize(_merge(DEFAULT_CONFIG, config))
        self._validate(merged)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)
        self._config = merged
        self._mtime_ns = self.path.stat().st_mtime_ns

    @staticmethod
    def _validate(config: dict[str, Any]) -> None:
        mode = str(config["connection"].get("mode") or "")
        if mode not in {"legacy_mobile_bridge", "standalone_mobile"}:
            raise ValueError(
                "connection.mode 必须是 legacy_mobile_bridge/standalone_mobile"
            )
        standalone = config["standalone_protocol"]
        if mode == "standalone_mobile" and not bool(standalone.get("enabled", True)):
            raise ValueError("纯电脑手机协议模式下 standalone_protocol.enabled 必须开启")
        endpoint = str(standalone.get("endpoint") or "").strip()
        if not endpoint.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]", "https://127.0.0.1", "https://localhost", "https://[::1]")):
            raise ValueError("纯电脑协议服务只允许使用本机地址")
        if float(standalone.get("timeout_seconds", 0)) <= 0:
            raise ValueError("standalone_protocol.timeout_seconds 必须大于 0")
        if not config["account"]["pet_id"]:
            raise ValueError("account.pet_id 不能为空")
        if config["mobile_protocol"].get("enabled") and not str(
            config["mobile_protocol"].get("endpoint", "")
        ).strip():
            raise ValueError("mobile_protocol.endpoint 不能为空")
        initial = float(config["mobile_protocol"]["reconnect_initial_seconds"])
        maximum = float(config["mobile_protocol"]["reconnect_max_seconds"])
        if initial <= 0 or maximum < initial:
            raise ValueError("自动重连间隔必须大于 0，且最大间隔不能小于初始间隔")
        optimization = config["optimization"]
        if not 1 <= int(optimization["daily_active_minutes"]) <= 1440:
            raise ValueError("optimization.daily_active_minutes 必须在 1 到 1440 之间")
        if float(optimization["safety_floor"]) < 0:
            raise ValueError("optimization.safety_floor 不能小于 0")
        for key in (
            "course_hunger_cost", "course_clean_cost", "work_hunger_cost",
            "work_clean_cost", "biscuit_price", "soap_price",
        ):
            if float(optimization[key]) < 0:
                raise ValueError(f"optimization.{key} 不能小于 0")
        for key in ("biscuit_restore", "soap_restore"):
            if float(optimization[key]) <= 0:
                raise ValueError(f"optimization.{key} 必须大于 0")
        if config["school"]["attribute"] not in {"culture", "physical", "art"}:
            raise ValueError("school.attribute 必须是 culture/physical/art")
        if int(config["school"].get("course_sub_event", 0)) < 0:
            raise ValueError("school.course_sub_event 不能小于 0")
        school_limit = int(config["school"].get("times_per_day", 0))
        if school_limit < 0:
            raise ValueError("school.times_per_day 不能小于 0")
        if config["school"].get("limit_enabled") and school_limit <= 0:
            raise ValueError("启用每日学习次数限制后，学习次数必须大于 0")
        if config["work"]["attribute"] not in {"culture", "physical", "art"}:
            raise ValueError("work.attribute 必须是 culture/physical/art")
        if int(config["work"].get("career_type", 0)) < 0:
            raise ValueError("work.career_type 不能小于 0")
        if int(config["work"].get("job_sub_event", 0)) < 0:
            raise ValueError("work.job_sub_event 不能小于 0")
        work_limit = int(config["work"].get("times_per_day", 0))
        if work_limit < 0:
            raise ValueError("work.times_per_day 不能小于 0")
        if config["work"].get("limit_enabled") and work_limit <= 0:
            raise ValueError("启用每日打工次数限制后，打工次数必须大于 0")
        if config["work"].get("strategy", "shortest_duration") != "shortest_duration":
            raise ValueError("work.strategy 目前必须是 shortest_duration")
        if config["work"].get("hire_mode", "auto") not in {"auto", "manual"}:
            raise ValueError("work.hire_mode 必须是 auto/manual")
        hire_uin = str(config["work"].get("hire_friend_uin", "")).strip()
        hire_pet_id = str(config["work"].get("hire_friend_pet_id", "")).strip()
        if bool(hire_uin) != bool(hire_pet_id):
            raise ValueError("手动雇佣好友必须同时保存 QQ 号和宠物 ID")
        if not isinstance(config["adventure"].get("option_name", ""), str):
            raise ValueError("adventure.option_name 必须是字符串")
        adventure_limit = int(config["adventure"].get("times_per_day", 0))
        if adventure_limit < 0:
            raise ValueError("adventure.times_per_day 不能小于 0")
        if config["adventure"].get("limit_enabled") and adventure_limit <= 0:
            raise ValueError("启用每日冒险次数限制后，冒险次数必须大于 0")
        hours, minutes = map(int, str(config["adventure"]["start_time"]).split(":"))
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            raise ValueError("adventure.start_time 必须是 HH:MM")
        pk_hours, pk_minutes = map(int, str(config["pk"]["start_time"]).split(":"))
        if not (0 <= pk_hours <= 23 and 0 <= pk_minutes <= 59):
            raise ValueError("pk.start_time 必须是 HH:MM")
        if int(config["pk"]["max_per_day"]) < 0:
            raise ValueError("pk.max_per_day 不能小于 0")
        if int(config["pk"].get("per_friend_limit", 3)) <= 0:
            raise ValueError("pk.per_friend_limit 必须大于 0")
        if config["pk"].get("opponent_mode", "fixed") not in {
            "all_friends",
            "fixed",
        }:
            raise ValueError("pk.opponent_mode 必须是 all_friends/fixed")
        if bool(config["pk"]["opponent_uin"]) != bool(config["pk"]["opponent_pet_id"]):
            raise ValueError("pk.opponent_uin 与 pk.opponent_pet_id 必须同时填写")
        for key in (
            "opponent_power",
            "minimum_hunger",
            "minimum_clean",
            "wait_seconds",
            "retry_cooldown_seconds",
            "friend_refresh_seconds",
        ):
            if float(config["pk"][key]) < 0:
                raise ValueError(f"pk.{key} 不能小于 0")
        if float(config["pk"]["wait_seconds"]) < 8:
            raise ValueError("pk.wait_seconds 不能小于 8 秒")
        visit_hours, visit_minutes = map(
            int, str(config["friend_visits"]["start_time"]).split(":")
        )
        if not (0 <= visit_hours <= 23 and 0 <= visit_minutes <= 59):
            raise ValueError("friend_visits.start_time 必须是 HH:MM")
        if int(config["friend_visits"]["max_per_day"]) < 0:
            raise ValueError("friend_visits.max_per_day 不能小于 0")
        minimum = float(config["friend_visits"]["interval_min_seconds"])
        maximum = float(config["friend_visits"]["interval_max_seconds"])
        if minimum < 1 or maximum < minimum:
            raise ValueError("好友访问间隔必须至少 1 秒，且最大值不能小于最小值")
        if float(config["friend_care"]["check_interval_seconds"]) < 15:
            raise ValueError("friend_care.check_interval_seconds 不能小于 15 秒")
        if not 0 <= float(config["friend_care"]["hunger_threshold"]) <= 100:
            raise ValueError("friend_care.hunger_threshold 必须在 0 到 100 之间")
        if not 0 <= float(config["friend_care"]["clean_threshold"]) <= 100:
            raise ValueError("friend_care.clean_threshold 必须在 0 到 100 之间")
        if str(config["friend_care"]["bath_item"]) not in {"auto", "soap", "bath_ball"}:
            raise ValueError("friend_care.bath_item 必须是 auto/soap/bath_ball")
        if str(config["friend_care"].get("food_item", "auto")) not in {
            "auto", "biscuit", "shrimp"
        }:
            raise ValueError("friend_care.food_item 必须是 auto/biscuit/shrimp")
        if not 1 <= int(config["friend_care"].get("food_purchase_count", 0)) <= 99:
            raise ValueError("friend_care.food_purchase_count 必须在 1 到 99 之间")
        if not 1 <= int(config["friend_care"].get("bath_purchase_count", 0)) <= 99:
            raise ValueError("friend_care.bath_purchase_count 必须在 1 到 99 之间")
        if float(config["friend_care"]["verify_delay_seconds"]) < 0:
            raise ValueError("friend_care.verify_delay_seconds 不能小于 0")
        if not 1 <= int(config["friend_care"]["verify_attempts"]) <= 10:
            raise ValueError("friend_care.verify_attempts 必须在 1 到 10 之间")
        if not 1 <= int(config["friend_care"]["max_feeds_per_friend_per_check"]) <= 20:
            raise ValueError(
                "friend_care.max_feeds_per_friend_per_check 必须在 1 到 20 之间"
            )
        if not 1 <= int(config["friend_care"]["max_washes_per_friend_per_check"]) <= 20:
            raise ValueError(
                "friend_care.max_washes_per_friend_per_check 必须在 1 到 20 之间"
            )
        if float(config["friend_care"]["failure_cooldown_seconds"]) < 0:
            raise ValueError("friend_care.failure_cooldown_seconds 不能小于 0")
        targets = config["friend_care"].get("targets", [])
        if not isinstance(targets, list):
            raise ValueError("friend_care.targets 必须是列表")
        seen_targets: set[str] = set()
        for target in targets:
            if not isinstance(target, dict):
                raise ValueError("好友照顾名单条目必须是对象")
            uin = str(target.get("uin", ""))
            pet_id = str(target.get("pet_id", ""))
            if not uin.isdigit() or not pet_id:
                raise ValueError("好友照顾名单必须包含有效 QQ 号和 petId")
            if uin in seen_targets:
                raise ValueError(f"好友照顾名单中 QQ {uin} 重复")
            seen_targets.add(uin)
        for section, key in (
            ("scheduler", "interval_seconds"),
            ("care", "hunger_threshold"),
            ("care", "clean_threshold"),
            ("care", "food_purchase_count"),
            ("care", "soap_purchase_count"),
            ("care", "verify_delay_seconds"),
            ("care", "failure_cooldown_seconds"),
            ("story", "recall_check_seconds"),
            ("story", "settle_retry_seconds"),
        ):
            if float(config[section][key]) < 0:
                raise ValueError(f"{section}.{key} 不能小于 0")
        if not 1 <= int(config["care"]["food_purchase_count"]) <= 99:
            raise ValueError("care.food_purchase_count 必须在 1 到 99 之间")
        if not 1 <= int(config["care"]["soap_purchase_count"]) <= 99:
            raise ValueError("care.soap_purchase_count 必须在 1 到 99 之间")
        if config["care"].get("food_item", "biscuit") not in {"biscuit", "shrimp"}:
            raise ValueError("care.food_item 必须是 biscuit/shrimp")
        if config["care"].get("bath_item", "soap") not in {"soap", "bath_ball"}:
            raise ValueError("care.bath_item 必须是 soap/bath_ball")
        if float(config["story"]["recall_check_seconds"]) < 3:
            raise ValueError("story.recall_check_seconds 不能小于 3 秒")
        if config["story"].get("employed_recall_mode", "best_split") not in {
            "best_split",
            "immediate",
        }:
            raise ValueError("story.employed_recall_mode 必须是 best_split/immediate")
        if int(config["notifications"]["failure_threshold"]) <= 0:
            raise ValueError("notifications.failure_threshold 必须大于 0")
        if float(config["notifications"]["cooldown_seconds"]) < 0:
            raise ValueError("notifications.cooldown_seconds 不能小于 0")
