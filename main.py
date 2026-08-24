from __future__ import annotations

import queue
import os
import random
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from qqpet_app.client import (
    PKOpponent,
    QQPetConnectionError,
    QQPetEmptyResponse,
)
from qqpet_app import __version__
from qqpet_app.config import ConfigStore
from qqpet_app.diagnostics import create_diagnostic_bundle
from qqpet_app.friend_visits import (
    FriendVisitProgress,
    current_pet_friends,
    eligible_friends,
)
from qqpet_app.friend_pet_cache import load_latest_friend_pet_capture
from qqpet_app.interface_tests import InterfaceTestResult, InterfaceTestRunner
from qqpet_app.notifications import NotificationManager
from qqpet_app.scheduler import Scheduler
from qqpet_app.updater import (
    UpdateInfo,
    download_update,
    extract_executable,
    fetch_latest,
    is_newer,
    schedule_windows_install,
)
from qqpet_app.single_instance import SingleInstance
from qqpet_app.mobile_protocol import default_project_root


ROOT = default_project_root()
CONFIG_PATH = ROOT / "config.yaml"
PROGRESS_PATH = ROOT / "runs" / "daily_progress.json"
LOG_DIR = ROOT / "runs" / "logs"
FRIEND_VISIT_DIR = ROOT / "runs"


SETTING_FIELDS = [
    ("mobile_protocol.enabled", "启用模拟器手机协议读取", bool),
    ("mobile_protocol.endpoint", "手机协议本机地址", str),
    ("mobile_protocol.adb_serial", "模拟器连接地址", str),
    ("mobile_protocol.adb_path", "ADB 程序路径（留空自动查找）", str),
    ("mobile_protocol.auto_reconnect", "手机协议断开后自动重连", bool),
    ("mobile_protocol.reconnect_initial_seconds", "自动重连初始间隔（秒）", float),
    ("mobile_protocol.reconnect_max_seconds", "自动重连最大间隔（秒）", float),
    ("account.uin", "QQ 号", str),
    ("account.pet_id", "宠物 ID", str),
    ("scheduler.interval_seconds", "轮询间隔（秒）", int),
    ("scheduler.coin_threshold", "学习金币阈值", float),
    ("optimization.enabled", "测试：启用动态数学模型调度（关闭时使用原调度）", bool),
    ("school.enabled", "启用学习", bool),
    ("school.attribute", "学习属性 culture/physical/art", str),
    ("school.limit_enabled", "限制每日学习次数（关闭=不限）", bool),
    ("school.times_per_day", "每日最大学习次数", int),
    ("work.enabled", "启用打工", bool),
    ("work.limit_enabled", "限制每日打工次数（关闭=不限）", bool),
    ("work.times_per_day", "每日最大打工次数", int),
    ("work.employ_friend", "启用打工雇佣好友", bool),
    ("work.hire_mode", "雇佣方式", str),
    ("adventure.enabled", "启用冒险", bool),
    ("adventure.start_time", "冒险开始时间 HH:MM", str),
    ("adventure.times_per_day", "每日冒险上限", int),
    ("pk.enabled", "启用每日定时自动 PK", bool),
    ("pk.start_time", "每日 PK 批次开始时间 HH:MM", str),
    ("pk.max_per_day", "每日 PK 上限（0 不限）", int),
    ("pk.opponent_mode", "对手来源 all_friends=全部好友 / fixed=固定", str),
    ("pk.friend_whitelist", "PK 好友白名单（空=全部）", str),
    ("pk.friend_exclude", "PK 好友排除名单", str),
    ("pk.friend_refresh_seconds", "PK 好友池刷新间隔（秒）", float),
    ("pk.per_friend_limit", "每位好友连续 PK 次数", int),
    ("pk.opponent_uin", "备用/固定对手 QQ", str),
    ("pk.opponent_pet_id", "备用/固定对手宠物 ID", str),
    ("pk.opponent_name", "备用/固定对手备注名", str),
    ("pk.opponent_power", "备用/固定对手战力（0=接口读取）", int),
    ("pk.only_weaker", "仅挑战战力低于自己的对手", bool),
    ("pk.minimum_hunger", "PK 最低体力", float),
    ("pk.minimum_clean", "PK 最低清洁", float),
    ("friend_visits.enabled", "启用每日好友访问", bool),
    ("friend_visits.start_time", "每日好友访问时间 HH:MM", str),
    ("friend_visits.max_per_day", "每日最多访问人数（0 不限）", int),
    ("friend_visits.interval_min_seconds", "访问最短间隔（秒）", float),
    ("friend_visits.interval_max_seconds", "访问最长间隔（秒）", float),
    ("friend_visits.poke_enabled", "访问成功后踩踩", bool),
    ("friend_visits.whitelist", "好友白名单（逗号分隔，空=全部）", str),
    ("friend_visits.exclude", "好友排除名单（逗号分隔）", str),
    ("friend_care.enabled", "启用好友自动照顾", bool),
    ("friend_care.feed_enabled", "启用好友自动喂食", bool),
    ("friend_care.clean_enabled", "启用好友自动清洁", bool),
    ("friend_care.check_interval_seconds", "好友照顾检查间隔（秒）", float),
    ("friend_care.hunger_threshold", "好友体力喂食阈值", float),
    ("friend_care.clean_threshold", "好友清洁洗护阈值", float),
    ("friend_care.bath_item", "好友自动清洁使用物品", str),
    ("friend_care.verify_delay_seconds", "好友状态刷新基础间隔（秒）", float),
    ("friend_care.verify_attempts", "好友照顾后刷新次数（1-10）", int),
    ("friend_care.max_feeds_per_friend_per_check", "单次检查最多连续投喂次数（1-20）", int),
    ("friend_care.max_washes_per_friend_per_check", "单次检查最多连续清洁次数（1-20）", int),
    ("friend_care.failure_cooldown_seconds", "好友照顾失败冷却（秒）", float),
    ("care.enabled", "启用状态照顾", bool),
    ("care.hunger_threshold", "体力喂食阈值", float),
    ("care.clean_threshold", "清洁洗澡阈值", float),
    ("care.auto_buy_supplies", "道具不足时自动用金币购买", bool),
    ("care.food_item", "自动喂食使用物品", str),
    ("care.bath_item", "自动洗澡使用物品", str),
    ("care.food_purchase_count", "每次购买饼干数量", int),
    ("care.soap_purchase_count", "每次购买洗护用品数量", int),
    ("care.verify_delay_seconds", "照顾后验证等待（秒）", float),
    ("care.failure_cooldown_seconds", "照顾失败重试间隔（秒）", float),
    ("story.recall_check_seconds", "被雇佣检查间隔（秒）", float),
    ("story.employed_recall_mode", "被雇佣召回策略", str),
    ("notifications.enabled", "启用外部通知", bool),
    ("notifications.failure_threshold", "连续失败多少次后发送外部通知", int),
    ("notifications.cooldown_seconds", "外部通知重复发送冷却（秒）", float),
    ("notifications.send_recovery", "任务恢复后发送外部通知", bool),
    ("notifications.windows_toast", "Windows 系统通知", bool),
    ("notifications.bark.enabled", "启用 Bark", bool),
    ("notifications.bark.device_key", "Bark Device Key", str),
    ("notifications.bark.base_url", "Bark 服务地址", str),
    ("notifications.pushplus.enabled", "启用 PushPlus", bool),
    ("notifications.pushplus.token", "PushPlus Token", str),
    ("notifications.pushplus.topic", "PushPlus 群组编码（可空）", str),
    ("notifications.serverchan.enabled", "启用 Server酱", bool),
    ("notifications.serverchan.sendkey", "Server酱 SendKey", str),
    ("notifications.smtp.enabled", "启用 SMTP 邮件", bool),
    ("notifications.smtp.host", "SMTP 服务器", str),
    ("notifications.smtp.port", "SMTP 端口", int),
    ("notifications.smtp.user", "SMTP 用户名", str),
    ("notifications.smtp.password", "SMTP 密码/授权码", str),
    ("notifications.smtp.from", "发件地址（可空）", str),
    ("notifications.smtp.to", "收件地址（可空）", str),
    ("notifications.smtp.ssl", "SMTP 使用 SSL", bool),
    ("notifications.smtp.starttls", "SMTP 使用 STARTTLS", bool),
    ("notifications.webhook.enabled", "启用自定义 webhook", bool),
    ("notifications.webhook.url", "自定义 webhook 地址", str),
    ("safety.safe_mode", "安全模式（只读）", bool),
    ("safety.allow_experimental_scene_actions", "允许真实学习/打工/冒险", bool),
]

CHOICE_FIELDS = {
    "care.food_item": {
        "饼干": "biscuit",
        "虾仁": "shrimp",
    },
    "care.bath_item": {
        "香皂片": "soap",
        "沐浴球": "bath_ball",
    },
    "friend_care.bath_item": {
        "香皂片": "soap",
        "沐浴球": "bath_ball",
    },
    "work.hire_mode": {
        "自动选择可用好友": "auto",
        "手动选择固定好友": "manual",
    },
    "story.employed_recall_mode": {
        "等到 25/75（收益分成最高）": "best_split",
        "立刻召回": "immediate",
    },
}

SETTING_SECTIONS = (
    ("connection", "连接与账号", ("mobile_protocol.", "account.")),
    ("scheduler", "自动调度", ("scheduler.",)),
    ("optimization", "动态收益优化", ("optimization.",)),
    ("care", "自己的宠物照顾", ("care.",)),
    ("school", "学习", ("school.",)),
    ("work", "打工", ("work.",)),
    ("adventure", "冒险", ("adventure.",)),
    ("pk", "每日定时 PK", ("pk.",)),
    ("friend_visits", "好友访问与踩踩", ("friend_visits.",)),
    ("friend_care", "好友自动照顾", ("friend_care.",)),
    ("story", "被雇佣召回", ("story.",)),
    ("notifications", "外部通知", ("notifications.",)),
    ("safety", "安全与真实操作", ("safety.",)),
    ("interface_test", "接口测试", ("interface_test.",)),
)


def deep_get(data: dict, path: str) -> Any:
    value: Any = data
    for key in path.split("."):
        value = value[key]
    return value


def deep_set(data: dict, path: str, value: Any) -> None:
    target = data
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value


class MainWindow(tk.Tk):
    def __init__(self, auto_start: bool = False) -> None:
        super().__init__()
        self.title("QQ 宠物接口助手")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        available_width = max(640, screen_width - 80)
        available_height = max(520, screen_height - 100)
        self.geometry(f"{min(1440, available_width)}x{min(900, available_height)}")
        self.minsize(min(980, available_width), min(640, available_height))
        self.config_store = ConfigStore(CONFIG_PATH)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.scheduler: Scheduler | None = None
        self.scheduler_thread: threading.Thread | None = None
        self.setting_vars: dict[str, tuple[tk.Variable, type]] = {}
        self.course_var = tk.StringVar(value="自动选择当前属性最短时长")
        self.course_options: dict[str, int] = {"自动选择当前属性最短时长": 0}
        self.job_var = tk.StringVar(value="自动选择开放职业中最短时长岗位")
        self.job_options: dict[str, tuple[int, int]] = {
            "自动选择开放职业中最短时长岗位": (0, 0)
        }
        self.adventure_var = tk.StringVar(value="自动选择服务器当前可用冒险")
        self.adventure_options: dict[str, str] = {
            "自动选择服务器当前可用冒险": ""
        }
        self.work_hire_friend_var = tk.StringVar(value="请先刷新好友宠物池")
        self.work_hire_friend_options: dict[str, PKOpponent] = {}
        self.test_food_var = tk.StringVar(value="默认饼干（已验证）")
        self.test_food_options: dict[str, tuple[str, str]] = {
            "默认饼干（已验证）": ("", "默认饼干")
        }
        self.test_bath_var = tk.StringVar(value="香皂片")
        self.test_bath_options: dict[str, tuple[str, str]] = {
            "香皂片": ("1", "香皂片"),
            "沐浴球": ("2", "沐浴球"),
        }
        self.test_course_var = tk.StringVar(value="请先刷新接口目录")
        self.test_job_var = tk.StringVar(value="请先刷新接口目录")
        self.test_hire_friend_var = tk.StringVar(value="请先刷新好友宠物池")
        self.test_adventure_var = tk.StringVar(value="请先刷新接口目录")
        self.interface_test_status_var = tk.StringVar(
            value="进入本页后会自动读取目录；也可点击刷新按钮重新读取。"
        )
        self.interface_test_buttons: list[ttk.Button] = []
        self.interface_catalog_loading = False
        self.interface_catalog_loaded = False
        self.manual_pk_friend_var = tk.StringVar(value="请先刷新好友")
        self.manual_pk_uin_var = tk.StringVar()
        self.manual_pk_pet_id_var = tk.StringVar()
        self.manual_pk_name_var = tk.StringVar()
        self.manual_pk_power_var = tk.StringVar(value="--")
        self.manual_pk_count_var = tk.IntVar(value=1)
        self.manual_pk_status_var = tk.StringVar(value="请选择好友或输入 QQ 号")
        self.manual_pk_friend_uins: dict[str, str] = {}
        self.manual_pk_cached_opponents: dict[str, PKOpponent] = {}
        self.hide_friends_without_pet_var = tk.BooleanVar(value=False)
        self.manual_pk_all_friends = ()
        self.manual_pk_pool_error = ""
        self.manual_pk_captured_count = 0
        self.friend_care_friend_var = tk.StringVar(value="请先刷新好友")
        self.friend_care_uin_var = tk.StringVar()
        self.friend_care_status_var = tk.StringVar(value="照顾名单为空")
        self.optimization_auto_var = tk.StringVar(
            value="启用后自动读取课程、岗位、道具目录和库存；首次喂食后自动校准食物恢复量。"
        )
        self.friend_care_friend_uins: dict[str, str] = {}
        self._notice_windows: list[tk.Toplevel] = []
        self.status_vars = {
            key: tk.StringVar(value="--")
            for key in (
                "connection", "gold", "food", "bath", "mood", "hunger",
                "clean", "story", "counts", "pk", "friend_visits", "friend_care",
            )
        }
        self._build_ui()
        self.bind_all("<MouseWheel>", self._route_mousewheel, add="+")
        self.after_idle(self._maximize_window)
        self._load_settings()
        self.after(500, self._refresh_school_courses)
        self.after(700, self._refresh_work_jobs)
        self.after(900, self._refresh_adventure_options)
        self.after(1100, self._refresh_manual_pk_friends)
        self.after(250, self._probe_connection)
        self.after(100, self._drain_events)
        if auto_start:
            self.after(250, self._start)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.configure(background="#f5f3fb")
        style.configure("TFrame", background="#f5f3fb")
        style.configure("TLabel", background="#f5f3fb", foreground="#403852")
        style.configure("TNotebook", background="#f5f3fb", borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#ebe7f4",
            foreground="#655d73",
            padding=(18, 9),
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#ffffff")],
            foreground=[("selected", "#5d49cb")],
        )
        style.configure(
            "Primary.TButton",
            background="#6c56dd",
            foreground="#ffffff",
            padding=(12, 8),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map("Primary.TButton", background=[("active", "#5b45c8")])
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Card.TLabel", background="#ffffff", foreground="#817991")
        style.configure(
            "CardValue.TLabel",
            background="#ffffff",
            foreground="#393149",
            font=("Microsoft YaHei UI", 15, "bold"),
        )
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 14, "bold"))
        style.configure(
            "SettingsHeader.TButton",
            font=("Microsoft YaHei UI", 11, "bold"),
            anchor="w",
            padding=(12, 9),
        )

        hero = tk.Frame(
            self,
            background="#ffffff",
            highlightbackground="#e8e3f1",
            highlightthickness=1,
            padx=18,
            pady=12,
        )
        hero.pack(fill=tk.X, padx=12, pady=(12, 0))
        avatar = tk.Label(
            hero,
            text="宠",
            width=3,
            height=1,
            background="#7059df",
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 20, "bold"),
        )
        avatar.pack(side=tk.LEFT, padx=(0, 13))
        hero_copy = tk.Frame(hero, background="#ffffff")
        hero_copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            hero_copy,
            text="ONEBOT · QQ PET",
            background="#ffffff",
            foreground="#887da6",
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hero_copy,
            text="QQ 宠物接口助手",
            background="#ffffff",
            foreground="#302b48",
            font=("Microsoft YaHei UI", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hero_copy,
            text="纯电脑接口托管 · 学习 / 打工 / 冒险 / PK / 好友照顾",
            background="#ffffff",
            foreground="#817991",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(2, 0))
        hero_status = tk.Frame(hero, background="#ffffff")
        hero_status.pack(side=tk.RIGHT, padx=(12, 0))
        self.hero_connection_label = tk.Label(
            hero_status,
            textvariable=self.status_vars["connection"],
            background="#fff0d7",
            foreground="#9b6109",
            padx=12,
            pady=5,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.hero_connection_label.pack(anchor="e")
        tk.Label(
            hero_status,
            textvariable=self.status_vars["story"],
            background="#ffffff",
            foreground="#817991",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="e", pady=(6, 0))

        shell = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        left_panel = ttk.Frame(shell)
        left_canvas = tk.Canvas(
            left_panel,
            highlightthickness=0,
            width=390,
            background=style.lookup("TFrame", "background") or self.cget("background"),
        )
        left_scroll = ttk.Scrollbar(
            left_panel, orient=tk.VERTICAL, command=left_canvas.yview
        )
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scroll.grid(row=0, column=1, sticky="ns")
        left_panel.rowconfigure(0, weight=1)
        left_panel.columnconfigure(0, weight=1)
        left = ttk.Frame(left_canvas, padding=18)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind(
            "<Configure>",
            lambda _event: left_canvas.configure(scrollregion=left_canvas.bbox("all")),
        )
        left_canvas.bind(
            "<Configure>",
            lambda event: left_canvas.itemconfigure(left_window, width=event.width),
        )
        self.left_status_canvas = left_canvas
        right = ttk.Frame(shell)
        shell.add(left_panel, weight=1)
        shell.add(right, weight=3)

        ttk.Label(left, text="宠物实时状态", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        metrics = ttk.Frame(left)
        metrics.pack(fill=tk.X, pady=(0, 10))
        metrics.columnconfigure((0, 1), weight=1)
        self._metric_card(metrics, "金币", "gold", 0, 0, "#a36e00")
        self._metric_card(metrics, "心情", "mood", 0, 1, "#c85178")
        self._metric_card(metrics, "体力", "hunger", 1, 0, "#27834d")
        self._metric_card(metrics, "清洁", "clean", 1, 1, "#287aa7")
        self._status_row(left, "接口", "connection")
        self._status_row(left, "金币", "gold")
        self._status_row(left, "食物", "food")
        self._status_row(left, "洗护", "bath")
        self._status_row(left, "心情", "mood")
        self._status_row(left, "体力", "hunger")
        self._status_row(left, "清洁", "clean")
        self._status_row(left, "当前任务", "story", small=True)
        self._status_row(left, "今日次数", "counts", small=True)
        self._status_row(left, "自动 PK", "pk", small=True)
        self._status_row(left, "好友访问", "friend_visits", small=True)
        self._status_row(left, "好友照顾", "friend_care", small=True)

        buttons = ttk.Frame(left)
        buttons.pack(fill=tk.X, pady=(22, 0))
        self.start_button = ttk.Button(
            buttons, text="启动自动托管", command=self._start, style="Primary.TButton"
        )
        self.start_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        self.stop_button = ttk.Button(buttons, text="停止", command=self._stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
        ttk.Button(left, text="立即检查一轮", command=self._check_once).pack(fill=tk.X, pady=(10, 0))
        self.friend_visit_button = ttk.Button(
            left,
            text="立即执行今日访问",
            command=self._run_friend_visits_once,
        )
        self.friend_visit_button.pack(fill=tk.X, pady=(10, 0))
        self.update_button = ttk.Button(
            left,
            text=f"检查更新（当前 v{__version__}）",
            command=self._check_for_updates,
        )
        self.update_button.pack(fill=tk.X, pady=(10, 0))
        self.diagnostics_button = ttk.Button(
            left,
            text="导出脱敏诊断包",
            command=self._export_diagnostics,
        )
        self.diagnostics_button.pack(fill=tk.X, pady=(10, 0))

        note = (
            "接口版不需要 scrcpy、OCR 或手机坐标。\n"
            "食物和洗护库存均来自服务器；洗澡会核对清洁值。\n"
            "学习、打工和 PK 均使用服务器接口，不使用固定坐标。"
        )
        ttk.Label(left, text=note, foreground="#666", justify=tk.LEFT).pack(anchor="w", pady=(18, 0))

        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True)
        log_page = ttk.Frame(notebook, padding=10)
        manual_pk_page = ttk.Frame(notebook, padding=16)
        friend_care_page = ttk.Frame(notebook, padding=16)
        settings_page = ttk.Frame(notebook, padding=10)
        notebook.add(log_page, text="运行日志")
        notebook.add(manual_pk_page, text="PK 好友")
        notebook.add(friend_care_page, text="好友照顾")
        notebook.add(settings_page, text="设置")

        self.log_text = tk.Text(log_page, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10))
        log_scroll = ttk.Scrollbar(log_page, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_manual_pk_page(manual_pk_page)
        self._build_friend_care_page(friend_care_page)

        settings_page.columnconfigure(1, weight=1)
        settings_page.rowconfigure(0, weight=1)
        nav_panel = ttk.Frame(settings_page, padding=(8, 10))
        nav_panel.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        ttk.Label(nav_panel, text="设置分类", style="Title.TLabel").pack(
            anchor="w", padx=8, pady=(0, 12)
        )
        self.settings_nav = tk.Listbox(
            nav_panel,
            width=24,
            borderwidth=0,
            highlightthickness=0,
            activestyle="none",
            exportselection=False,
            font=("Microsoft YaHei UI", 10),
        )
        self.settings_nav.pack(fill=tk.Y, expand=True)
        for _key, title, _prefixes in SETTING_SECTIONS:
            self.settings_nav.insert(tk.END, title)
        self.settings_nav.bind("<<ListboxSelect>>", self._settings_nav_selected)

        content_panel = ttk.Frame(settings_page)
        content_panel.grid(row=0, column=1, sticky="nsew")
        canvas = tk.Canvas(content_panel, highlightthickness=0)
        scroll = ttk.Scrollbar(content_panel, orient=tk.VERTICAL, command=canvas.yview)
        form = ttk.Frame(canvas)
        form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        form_window = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(form_window, width=event.width),
        )
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.settings_canvas = canvas
        self.settings_form = form

        section_frames: dict[str, ttk.Frame] = {}
        section_rows: dict[str, int] = {}
        self.settings_section_containers: dict[str, ttk.Frame] = {}
        self.settings_section_bodies: dict[str, ttk.Frame] = {}
        self.settings_section_titles: dict[str, tk.StringVar] = {}
        self.settings_section_expanded: dict[str, bool] = {}
        for key, title, _prefixes in SETTING_SECTIONS:
            container = ttk.Frame(form, relief="solid", borderwidth=1)
            container.pack(fill=tk.X, expand=True, padx=6, pady=6)
            title_var = tk.StringVar(value=f"▼  {title}")
            ttk.Button(
                container,
                textvariable=title_var,
                style="SettingsHeader.TButton",
                command=lambda section_key=key: self._toggle_settings_section(section_key),
            ).pack(fill=tk.X)
            section = ttk.Frame(container, padding=(12, 8))
            section.pack(fill=tk.X, expand=True)
            section.columnconfigure(1, weight=1)
            section_frames[key] = section
            section_rows[key] = 0
            self.settings_section_containers[key] = container
            self.settings_section_bodies[key] = section
            self.settings_section_titles[key] = title_var
            self.settings_section_expanded[key] = True
        self.settings_nav.selection_set(0)

        external_section = section_frames["notifications"]
        ttk.Label(
            external_section,
            text=(
                "类似 MAA 的外部通知：选择需要的渠道，任务连续失败或恢复时发送；"
                "应用内彩色消息不受此开关影响。"
            ),
            foreground="#666",
            wraplength=680,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 10))
        section_rows["notifications"] = 1

        def section_key(path: str) -> str:
            matches = (
                (len(prefix), key)
                for key, _title, prefixes in SETTING_SECTIONS
                for prefix in prefixes
                if path.startswith(prefix)
            )
            return max(matches)[1]

        for path, label, value_type in SETTING_FIELDS:
            key = section_key(path)
            section = section_frames[key]
            row = section_rows[key]
            ttk.Label(section, text=label).grid(
                row=row, column=0, sticky="w", padx=6, pady=5
            )
            if path in CHOICE_FIELDS:
                variable = tk.StringVar()
                ttk.Combobox(
                    section,
                    textvariable=variable,
                    state="readonly",
                    width=43,
                    values=tuple(CHOICE_FIELDS[path]),
                ).grid(row=row, column=1, sticky="ew", padx=6, pady=5)
            elif value_type is bool:
                variable: tk.Variable = tk.BooleanVar()
                ttk.Checkbutton(section, variable=variable).grid(
                    row=row, column=1, sticky="w", padx=6, pady=5
                )
            else:
                variable = tk.StringVar()
                ttk.Entry(section, textvariable=variable, width=46).grid(
                    row=row, column=1, sticky="ew", padx=6, pady=5
                )
            self.setting_vars[path] = (variable, value_type)
            section_rows[key] += 1

        optimization_section = section_frames["optimization"]
        ttk.Label(
            optimization_section,
            textvariable=self.optimization_auto_var,
            wraplength=760,
            justify=tk.LEFT,
        ).grid(
            row=section_rows["optimization"],
            column=0,
            columnspan=2,
            sticky="ew",
            padx=6,
            pady=(8, 5),
        )

        connection_section = section_frames["connection"]
        pet_lookup_row = section_rows["connection"]
        self.pet_id_lookup_button = ttk.Button(
            connection_section,
            text="从服务器一键读取并保存宠物 ID",
            command=self._lookup_own_pet_id,
        )
        self.pet_id_lookup_button.grid(
            row=pet_lookup_row,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=6,
            pady=(12, 6),
        )

        external_test_row = section_rows["notifications"]
        self.external_notification_test_button = ttk.Button(
            external_section,
            text="向已启用渠道发送测试通知",
            command=self._test_external_notifications,
        )
        self.external_notification_test_button.grid(
            row=external_test_row,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=6,
            pady=(12, 6),
        )

        school_section = section_frames["school"]
        course_row = section_rows["school"]
        ttk.Label(school_section, text="当前阶段课程").grid(
            row=course_row, column=0, sticky="w", padx=6, pady=5
        )
        course_box = ttk.Frame(school_section)
        course_box.grid(row=course_row, column=1, sticky="ew", padx=6, pady=5)
        self.course_combo = ttk.Combobox(
            course_box,
            textvariable=self.course_var,
            state="readonly",
            width=41,
            values=tuple(self.course_options),
        )
        self.course_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.course_refresh_button = ttk.Button(
            course_box,
            text="刷新",
            command=self._refresh_school_courses,
        )
        self.course_refresh_button.pack(side=tk.LEFT, padx=(6, 0))
        self.course_stage_label = ttk.Label(
            school_section, text="将从服务器读取当前学园阶段", foreground="#666"
        )
        self.course_stage_label.grid(
            row=course_row + 1, column=1, sticky="w", padx=6, pady=(0, 5)
        )
        work_section = section_frames["work"]
        job_row = section_rows["work"]
        ttk.Label(work_section, text="开放职业岗位").grid(
            row=job_row, column=0, sticky="w", padx=6, pady=5
        )
        job_box = ttk.Frame(work_section)
        job_box.grid(row=job_row, column=1, sticky="ew", padx=6, pady=5)
        self.job_combo = ttk.Combobox(
            job_box,
            textvariable=self.job_var,
            state="readonly",
            width=41,
            values=tuple(self.job_options),
        )
        self.job_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.job_refresh_button = ttk.Button(
            job_box,
            text="刷新",
            command=self._refresh_work_jobs,
        )
        self.job_refresh_button.pack(side=tk.LEFT, padx=(6, 0))
        self.job_status_label = ttk.Label(
            work_section, text="将从服务器读取已开放职业和岗位", foreground="#666"
        )
        self.job_status_label.grid(
            row=job_row + 1, column=1, sticky="w", padx=6, pady=(0, 5)
        )
        ttk.Label(work_section, text="手动雇佣好友").grid(
            row=job_row + 2, column=0, sticky="w", padx=6, pady=5
        )
        hire_box = ttk.Frame(work_section)
        hire_box.grid(row=job_row + 2, column=1, sticky="ew", padx=6, pady=5)
        self.work_hire_friend_combo = ttk.Combobox(
            hire_box,
            textvariable=self.work_hire_friend_var,
            state="readonly",
            width=41,
        )
        self.work_hire_friend_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            hire_box, text="刷新好友", command=self._refresh_manual_pk_friends
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(
            work_section,
            text="选择“手动选择固定好友”时生效；仅显示服务器已确认拥有宠物的好友。",
            foreground="#666",
        ).grid(row=job_row + 3, column=1, sticky="w", padx=6, pady=(0, 5))
        adventure_section = section_frames["adventure"]
        adventure_row = section_rows["adventure"]
        ttk.Label(adventure_section, text="服务器冒险选项").grid(
            row=adventure_row, column=0, sticky="w", padx=6, pady=5
        )
        adventure_box = ttk.Frame(adventure_section)
        adventure_box.grid(row=adventure_row, column=1, sticky="ew", padx=6, pady=5)
        self.adventure_combo = ttk.Combobox(
            adventure_box,
            textvariable=self.adventure_var,
            state="readonly",
            width=41,
            values=tuple(self.adventure_options),
        )
        self.adventure_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.adventure_refresh_button = ttk.Button(
            adventure_box,
            text="刷新",
            command=self._refresh_adventure_options,
        )
        self.adventure_refresh_button.pack(side=tk.LEFT, padx=(6, 0))
        self.adventure_status_label = ttk.Label(
            adventure_section,
            text="将从服务器读取天气冒险目录；冒险与学习、打工互斥执行",
            foreground="#666",
        )
        self.adventure_status_label.grid(
            row=adventure_row + 1, column=1, sticky="w", padx=6, pady=(0, 5)
        )
        self._build_interface_test_section(section_frames["interface_test"])
        ttk.Button(form, text="保存全部设置并立即生效", command=self._save_settings).pack(
            fill=tk.X, padx=6, pady=(10, 18)
        )

    def _build_interface_test_section(self, section: ttk.Frame) -> None:
        ttk.Label(
            section,
            text=(
                "这里用于逐项定位协议问题。灰色检查按钮只读取服务器；红色“真实测试”按钮会立刻"
                "消耗道具或启动任务。学习、打工、冒险属于互斥主任务，一项成功后，另外两项必须"
                "等待倒计时结束。进入本页会自动读取可选目录。"
            ),
            foreground="#b24a3a",
            wraplength=720,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 12))

        def add_button(row: int, text: str, command) -> ttk.Button:
            button = ttk.Button(section, text=text, command=command)
            button.grid(row=row, column=2, sticky="ew", padx=6, pady=5)
            self.interface_test_buttons.append(button)
            return button

        ttk.Label(section, text="基础读取").grid(row=1, column=0, sticky="w", padx=6, pady=5)
        ttk.Label(section, text="状态、库存与服务器岗位规则").grid(
            row=1, column=1, sticky="w", padx=6, pady=5
        )
        add_button(1, "只读检查状态", lambda: self._run_interface_test("state"))

        ttk.Label(section, text="接口目录").grid(row=2, column=0, sticky="w", padx=6, pady=5)
        ttk.Label(section, text="食物 / 洗护 / 课程 / 岗位 / 冒险").grid(
            row=2, column=1, sticky="w", padx=6, pady=5
        )
        add_button(2, "刷新并检查全部目录", self._refresh_interface_test_catalogs)

        ttk.Label(section, text="喂食物品").grid(row=3, column=0, sticky="w", padx=6, pady=5)
        self.test_food_combo = ttk.Combobox(
            section,
            textvariable=self.test_food_var,
            state="readonly",
            values=tuple(self.test_food_options),
            width=45,
        )
        self.test_food_combo.grid(row=3, column=1, sticky="ew", padx=6, pady=5)
        add_button(3, "真实测试：立即喂食", lambda: self._run_interface_test("feed"))

        ttk.Label(section, text="洗护物品").grid(row=4, column=0, sticky="w", padx=6, pady=5)
        self.test_bath_combo = ttk.Combobox(
            section,
            textvariable=self.test_bath_var,
            state="readonly",
            values=tuple(self.test_bath_options),
            width=45,
        )
        self.test_bath_combo.grid(row=4, column=1, sticky="ew", padx=6, pady=5)
        add_button(4, "真实测试：立即洗澡", lambda: self._run_interface_test("wash"))

        ttk.Label(section, text="学习课程").grid(row=5, column=0, sticky="w", padx=6, pady=5)
        self.test_course_combo = ttk.Combobox(
            section, textvariable=self.test_course_var, state="readonly", width=45
        )
        self.test_course_combo.grid(row=5, column=1, sticky="ew", padx=6, pady=5)
        add_button(5, "真实测试：立即开课", lambda: self._run_interface_test("school"))

        ttk.Label(section, text="打工岗位").grid(row=6, column=0, sticky="w", padx=6, pady=5)
        self.test_job_combo = ttk.Combobox(
            section, textvariable=self.test_job_var, state="readonly", width=45
        )
        self.test_job_combo.grid(row=6, column=1, sticky="ew", padx=6, pady=5)
        add_button(6, "真实测试：立即开工", lambda: self._run_interface_test("work"))

        ttk.Label(section, text="冒险项目").grid(row=7, column=0, sticky="w", padx=6, pady=5)
        self.test_adventure_combo = ttk.Combobox(
            section, textvariable=self.test_adventure_var, state="readonly", width=45
        )
        self.test_adventure_combo.grid(row=7, column=1, sticky="ew", padx=6, pady=5)
        add_button(7, "真实测试：立即冒险", lambda: self._run_interface_test("adventure"))

        ttk.Label(section, text="雇佣好友开工").grid(
            row=8, column=0, sticky="w", padx=6, pady=5
        )
        self.test_hire_friend_combo = ttk.Combobox(
            section,
            textvariable=self.test_hire_friend_var,
            state="readonly",
            width=45,
        )
        self.test_hire_friend_combo.grid(row=8, column=1, sticky="ew", padx=6, pady=5)
        add_button(
            8,
            "真实测试：雇佣好友开工",
            lambda: self._run_interface_test("work_hire"),
        )

        ttk.Label(section, text="被他人雇佣召回").grid(
            row=9, column=0, sticky="w", padx=6, pady=5
        )
        ttk.Label(section, text="读取当前被雇佣任务并立即召回验证").grid(
            row=9, column=1, sticky="w", padx=6, pady=5
        )
        add_button(
            9,
            "真实测试：立即召回",
            lambda: self._run_interface_test("recall_employed"),
        )

        ttk.Separator(section).grid(
            row=10, column=0, columnspan=3, sticky="ew", padx=6, pady=(12, 8)
        )
        ttk.Label(section, text="最近结果").grid(row=11, column=0, sticky="nw", padx=6, pady=5)
        ttk.Label(
            section,
            textvariable=self.interface_test_status_var,
            wraplength=700,
            justify=tk.LEFT,
            foreground="#5d5568",
        ).grid(row=11, column=1, columnspan=2, sticky="w", padx=6, pady=5)
        section.columnconfigure(1, weight=1)

    def _metric_card(
        self,
        parent: ttk.Frame,
        title: str,
        key: str,
        row: int,
        column: int,
        accent: str,
    ) -> None:
        card = tk.Frame(
            parent,
            background="#ffffff",
            highlightbackground="#e9e5f1",
            highlightthickness=1,
            padx=11,
            pady=8,
        )
        card.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
        tk.Label(
            card,
            text=title,
            background="#ffffff",
            foreground="#837b95",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w")
        tk.Label(
            card,
            textvariable=self.status_vars[key],
            background="#ffffff",
            foreground=accent,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(anchor="w", pady=(2, 0))

    @staticmethod
    def _settings_section_title(key: str) -> str:
        return next(title for item_key, title, _prefixes in SETTING_SECTIONS if item_key == key)

    def _set_settings_section_expanded(self, key: str, expanded: bool) -> None:
        body = self.settings_section_bodies[key]
        title = self._settings_section_title(key)
        if expanded:
            if not body.winfo_manager():
                body.pack(fill=tk.X, expand=True)
            self.settings_section_titles[key].set(f"▼  {title}")
        else:
            body.pack_forget()
            self.settings_section_titles[key].set(f"▶  {title}")
        self.settings_section_expanded[key] = expanded
        self.settings_form.update_idletasks()
        self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all"))

    def _toggle_settings_section(self, key: str) -> None:
        self._set_settings_section_expanded(
            key, not self.settings_section_expanded.get(key, True)
        )

    def _settings_nav_selected(self, _event=None) -> None:
        selected = self.settings_nav.curselection()
        if not selected:
            return
        index = int(selected[0])
        key = SETTING_SECTIONS[index][0]
        self._set_settings_section_expanded(key, True)
        self.settings_form.update_idletasks()
        container = self.settings_section_containers[key]
        content_height = max(1, self.settings_form.winfo_height())
        viewport_height = self.settings_canvas.winfo_height()
        scrollable = max(1, content_height - viewport_height)
        self.settings_canvas.yview_moveto(min(1.0, container.winfo_y() / scrollable))
        if key == "interface_test" and not self.interface_catalog_loaded:
            self._refresh_interface_test_catalogs()

    def _show_notice(
        self,
        title: str,
        message: str,
        level: str = "info",
        duration_ms: int | None = None,
    ) -> None:
        palette = {
            "info": ("#2563eb", "#eff6ff", "ℹ"),
            "success": ("#16a34a", "#f0fdf4", "✓"),
            "warning": ("#d97706", "#fffbeb", "!"),
            "error": ("#dc2626", "#fef2f2", "×"),
        }
        accent, background, icon = palette.get(level, palette["info"])
        notice = tk.Toplevel(self)
        notice.overrideredirect(True)
        notice.transient(self)
        try:
            notice.attributes("-topmost", True)
        except tk.TclError:
            pass
        shell = tk.Frame(
            notice,
            background=background,
            highlightbackground=accent,
            highlightthickness=1,
            padx=0,
            pady=0,
        )
        shell.pack(fill=tk.BOTH, expand=True)
        tk.Frame(shell, width=5, background=accent).pack(side=tk.LEFT, fill=tk.Y)
        icon_label = tk.Label(
            shell,
            text=icon,
            foreground=accent,
            background=background,
            font=("Microsoft YaHei UI", 15, "bold"),
            width=2,
        )
        icon_label.pack(side=tk.LEFT, padx=(8, 2), pady=12, anchor="n")
        text_box = tk.Frame(shell, background=background)
        text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=10)
        tk.Label(
            text_box,
            text=title,
            foreground="#111827",
            background=background,
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            text_box,
            text=str(message),
            foreground="#374151",
            background=background,
            font=("Microsoft YaHei UI", 9),
            justify=tk.LEFT,
            anchor="w",
            wraplength=340,
        ).pack(fill=tk.X, pady=(3, 0))
        tk.Button(
            shell,
            text="×",
            relief=tk.FLAT,
            borderwidth=0,
            foreground="#6b7280",
            background=background,
            activebackground=background,
            command=lambda: self._dismiss_notice(notice),
        ).pack(side=tk.RIGHT, padx=8, pady=6, anchor="n")
        self._notice_windows.append(notice)
        notice.update_idletasks()
        self._position_notices()
        lifetime = duration_ms if duration_ms is not None else (9000 if level == "error" else 5500)
        notice.after(lifetime, lambda: self._dismiss_notice(notice))

    def _dismiss_notice(self, notice: tk.Toplevel) -> None:
        if notice in self._notice_windows:
            self._notice_windows.remove(notice)
        try:
            notice.destroy()
        except tk.TclError:
            pass
        self._position_notices()

    def _position_notices(self) -> None:
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, self.winfo_width() - 430)
        y = self.winfo_rooty() + 52
        for notice in tuple(self._notice_windows):
            try:
                height = max(76, notice.winfo_reqheight())
                notice.geometry(f"410x{height}+{x}+{y}")
                y += height + 10
            except tk.TclError:
                if notice in self._notice_windows:
                    self._notice_windows.remove(notice)

    def _maximize_window(self) -> None:
        """Open at a useful size while keeping a fallback for non-Windows Tk."""
        try:
            if sys.platform == "win32":
                self.state("zoomed")
        except tk.TclError:
            return

    def _route_mousewheel(self, event: tk.Event) -> str | None:
        """Scroll the panel under the pointer instead of hiding lower controls."""
        for canvas in (self.left_status_canvas, self.settings_canvas):
            left = canvas.winfo_rootx()
            top = canvas.winfo_rooty()
            if (
                left <= event.x_root < left + canvas.winfo_width()
                and top <= event.y_root < top + canvas.winfo_height()
            ):
                direction = -1 if event.delta > 0 else 1
                canvas.yview_scroll(direction * 3, "units")
                return "break"
        return None

    def _status_row(self, parent: ttk.Frame, title: str, key: str, small: bool = False) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=6)
        ttk.Label(frame, text=title, width=10).pack(side=tk.LEFT)
        style = "Title.TLabel" if small else "Value.TLabel"
        ttk.Label(frame, textvariable=self.status_vars[key], style=style).pack(side=tk.RIGHT)

    def _build_manual_pk_page(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="手动 PK 专区", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )
        ttk.Label(
            parent,
            text="与自动 PK 独立：手动执行不会写入自动 PK 每日轮换次数。",
            foreground="#666",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(parent, text="选择 QQ 好友").grid(row=2, column=0, sticky="w", pady=6)
        self.manual_pk_friend_combo = ttk.Combobox(
            parent,
            textvariable=self.manual_pk_friend_var,
            state="readonly",
            width=42,
        )
        self.manual_pk_friend_combo.grid(row=2, column=1, sticky="ew", padx=8, pady=6)
        self.manual_pk_friend_combo.bind(
            "<<ComboboxSelected>>", self._manual_pk_friend_selected
        )
        self.manual_pk_refresh_button = ttk.Button(
            parent, text="刷新好友", command=self._refresh_manual_pk_friends
        )
        self.manual_pk_refresh_button.grid(row=2, column=2, sticky="ew", pady=6)

        ttk.Checkbutton(
            parent,
            text="隐藏确认无宠物的好友（资料未知者保留）",
            variable=self.hide_friends_without_pet_var,
            command=self._friend_pet_filter_changed,
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 6))

        fields = (
            ("QQ 名/备注", self.manual_pk_name_var, True),
            ("QQ 账号", self.manual_pk_uin_var, False),
            ("宠物 ID", self.manual_pk_pet_id_var, True),
            ("对手战力", self.manual_pk_power_var, True),
        )
        for row, (label, variable, readonly) in enumerate(fields, start=4):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
            entry = ttk.Entry(parent, textvariable=variable, width=44)
            if readonly:
                entry.configure(state="readonly")
            entry.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=6)

        count_row = 4 + len(fields)
        ttk.Label(parent, text="本次连续 PK 次数").grid(
            row=count_row, column=0, sticky="w", pady=6
        )
        self.manual_pk_count_spinbox = ttk.Spinbox(
            parent,
            from_=1,
            to=99,
            textvariable=self.manual_pk_count_var,
            width=42,
        )
        self.manual_pk_count_spinbox.grid(
            row=count_row, column=1, columnspan=2, sticky="ew", padx=8, pady=6
        )

        button_row = count_row + 1
        self.manual_pk_lookup_button = ttk.Button(
            parent, text="按 QQ 检索宠物资料", command=self._lookup_manual_pk_opponent
        )
        self.manual_pk_lookup_button.grid(
            row=button_row, column=0, columnspan=3, sticky="ew", pady=(14, 6)
        )
        self.manual_pk_run_button = ttk.Button(
            parent, text="按设置次数立即 PK", command=self._run_manual_pk
        )
        self.manual_pk_run_button.grid(
            row=button_row + 1, column=0, columnspan=3, sticky="ew", pady=6
        )
        ttk.Label(
            parent,
            textvariable=self.manual_pk_status_var,
            foreground="#555",
            wraplength=520,
        ).grid(row=button_row + 2, column=0, columnspan=3, sticky="w", pady=(12, 0))
        parent.columnconfigure(1, weight=1)

    @staticmethod
    def _configured_pk_opponent(config: dict) -> PKOpponent | None:
        pk = config["pk"]
        uin = str(pk.get("opponent_uin", "")).strip()
        pet_id = str(pk.get("opponent_pet_id", "")).strip()
        if not uin or not pet_id:
            return None
        return PKOpponent(
            user_id=uin,
            pet_id=pet_id,
            nickname=str(pk.get("opponent_name", "")),
            power=int(pk.get("opponent_power", 0)),
        )

    def _build_friend_care_page(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="好友自动照顾名单", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )
        ttk.Label(
            parent,
            text="只监控名单中的好友；体力或清洁低于各自阈值时自动照顾，并重新读取好友宠物资料验证。",
            foreground="#666",
            wraplength=540,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(parent, text="选择 QQ 好友").grid(row=2, column=0, sticky="w", pady=6)
        self.friend_care_friend_combo = ttk.Combobox(
            parent,
            textvariable=self.friend_care_friend_var,
            state="readonly",
            width=42,
        )
        self.friend_care_friend_combo.grid(row=2, column=1, sticky="ew", padx=8, pady=6)
        self.friend_care_friend_combo.bind(
            "<<ComboboxSelected>>", self._friend_care_friend_selected
        )
        self.friend_care_refresh_button = ttk.Button(
            parent, text="刷新 QQ 好友", command=self._refresh_manual_pk_friends
        )
        self.friend_care_refresh_button.grid(row=2, column=2, sticky="ew", pady=6)
        ttk.Checkbutton(
            parent,
            text="隐藏确认无宠物的好友（资料未知者保留）",
            variable=self.hide_friends_without_pet_var,
            command=self._friend_pet_filter_changed,
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 6))
        ttk.Label(parent, text="好友 QQ 账号").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=self.friend_care_uin_var, width=44).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=8, pady=6
        )
        self.friend_care_add_button = ttk.Button(
            parent, text="解析宠物并加入自动照顾名单", command=self._add_friend_care_target
        )
        self.friend_care_add_button.grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(10, 6)
        )
        ttk.Label(parent, text="当前照顾名单").grid(row=6, column=0, sticky="nw", pady=6)
        self.friend_care_listbox = tk.Listbox(parent, height=9, exportselection=False)
        self.friend_care_listbox.grid(
            row=6, column=1, columnspan=2, sticky="nsew", padx=8, pady=6
        )
        self.friend_care_remove_button = ttk.Button(
            parent, text="从照顾名单移除", command=self._remove_friend_care_target
        )
        self.friend_care_remove_button.grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=6
        )
        ttk.Label(
            parent,
            textvariable=self.friend_care_status_var,
            foreground="#555",
            wraplength=540,
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(6, weight=1)

    def _reload_friend_care_targets(self) -> None:
        targets = self.config_store.data["friend_care"].get("targets", [])
        self.friend_care_listbox.delete(0, tk.END)
        for target in targets:
            self.friend_care_listbox.insert(
                tk.END,
                f"{target.get('name') or target['uin']}｜QQ {target['uin']}｜petId {target['pet_id']}",
            )
        care = self.config_store.data["friend_care"]
        state = "已启用" if care.get("enabled") else "未启用"
        self.friend_care_status_var.set(
            f"{state}；监控 {len(targets)} 位好友；体力低于 {float(care['hunger_threshold']):g} 自动喂食；"
            f"清洁低于 {float(care['clean_threshold']):g} 自动洗护；"
            f"每 {float(care['check_interval_seconds']):g} 秒检查"
        )

    def _friend_care_friend_selected(self, _event=None) -> None:
        uin = self.friend_care_friend_uins.get(self.friend_care_friend_var.get(), "")
        if uin:
            self.friend_care_uin_var.set(uin)

    def _add_friend_care_target(self) -> None:
        uin = self.friend_care_uin_var.get().strip()
        if not uin.isdigit():
            self._show_notice("无法加入好友", "请输入有效的好友 QQ 号", "warning")
            return
        self.friend_care_add_button.configure(state=tk.DISABLED)
        self.friend_care_status_var.set(f"正在解析 QQ {uin} 的真实宠物资料…")

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                fallback = self.manual_pk_cached_opponents.get(uin)
                opponent = client.resolve_pk_opponent(
                    uin, fallback or self._configured_pk_opponent(config)
                )
                friend_config = {
                    **config,
                    "account": {**config["account"], "pet_id": opponent.pet_id},
                }
                friend_values_client = Scheduler._make_client(friend_config)
                values = friend_values_client.query_values()
                self.events.put(("friend_care_target_resolved", (opponent, values)))
            except Exception as exc:
                self.events.put(("friend_care_target_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _remove_friend_care_target(self) -> None:
        selected = self.friend_care_listbox.curselection()
        if not selected:
            self._show_notice("好友照顾", "请先选择要移除的好友", "info")
            return
        index = int(selected[0])
        config = self.config_store.data
        targets = list(config["friend_care"].get("targets", []))
        if index >= len(targets):
            return
        removed = targets.pop(index)
        config["friend_care"]["targets"] = targets
        self.config_store.save(config)
        self._reload_friend_care_targets()
        self._append_log(
            f"[{datetime.now():%H:%M:%S}] 已从自动照顾名单移除 "
            f"{removed.get('name') or removed['uin']}（QQ {removed['uin']}）"
        )

    def _load_settings(self) -> None:
        config = self.config_store.data
        for path, (variable, _value_type) in self.setting_vars.items():
            value = deep_get(config, path)
            if path in CHOICE_FIELDS:
                labels = CHOICE_FIELDS[path]
                value = next((label for label, saved in labels.items() if saved == value), value)
            variable.set(value)
        selected = int(config["school"].get("course_sub_event", 0))
        if selected:
            label = f"已保存课程编号 {selected}（刷新后显示名称）"
            self.course_options[label] = selected
            self.course_combo.configure(values=tuple(self.course_options))
            self.course_var.set(label)
        else:
            self.course_var.set("自动选择当前属性最短时长")
        career_type = int(config["work"].get("career_type", 0))
        job_sub_event = int(config["work"].get("job_sub_event", 0))
        if job_sub_event:
            label = f"已保存岗位编号 {job_sub_event}（刷新后显示名称）"
            self.job_options[label] = (career_type, job_sub_event)
            self.job_combo.configure(values=tuple(self.job_options))
            self.job_var.set(label)
        else:
            self.job_var.set("自动选择开放职业中最短时长岗位")
        adventure_name = str(config["adventure"].get("option_name", ""))
        if adventure_name:
            label = f"已保存冒险“{adventure_name}”（刷新后显示详情）"
            self.adventure_options[label] = adventure_name
            self.adventure_combo.configure(values=tuple(self.adventure_options))
            self.adventure_var.set(label)
        else:
            self.adventure_var.set("自动选择服务器当前可用冒险")
        self._reload_friend_care_targets()

    def _refresh_school_courses(self) -> None:
        self.course_refresh_button.configure(state=tk.DISABLED)
        self.course_stage_label.configure(text="正在读取服务器课程目录…")

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                stage = client.query_school_stage()
                courses = client.query_school_courses(stage)
                self.events.put(("school_courses", (stage, courses)))
            except Exception as exc:
                self.events.put(("school_courses_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _lookup_own_pet_id(self) -> None:
        self.pet_id_lookup_button.configure(state=tk.DISABLED)
        self._show_notice(
            "正在读取宠物 ID",
            "正在通过当前电脑版 QQ 会话查询服务器本人宠物资料…",
            "info",
        )

        def worker() -> None:
            try:
                expected_uin = str(self.setting_vars["account.uin"][0].get()).strip()
                config = self.config_store.data
                lookup_config = {
                    **config,
                    "account": {**config["account"], "pet_id": ""},
                }
                client = Scheduler._make_client(lookup_config)
                logged_in_uin = client.check_connection()
                if expected_uin and expected_uin != logged_in_uin:
                    raise RuntimeError(
                        f"设置中的 QQ {expected_uin} 与当前登录 QQ {logged_in_uin} 不一致"
                    )
                profile = client.query_own_pet_profile(logged_in_uin)
                self.events.put(("own_pet_profile", profile))
            except Exception as exc:
                self.events.put(("own_pet_profile_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_work_jobs(self) -> None:
        self.job_refresh_button.configure(state=tk.DISABLED)
        self.job_status_label.configure(text="正在读取服务器职业和岗位目录…")

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                catalog = client.query_work_catalog()
                self.events.put(("work_jobs", catalog))
            except Exception as exc:
                self.events.put(("work_jobs_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_adventure_options(self) -> None:
        self.adventure_refresh_button.configure(state=tk.DISABLED)
        self.adventure_status_label.configure(text="正在读取服务器冒险目录…")

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                options = client.query_adventure_options()
                self.events.put(("adventure_options", options))
            except Exception as exc:
                self.events.put(("adventure_options_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _set_interface_test_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        for button in self.interface_test_buttons:
            button.configure(state=state)

    def _refresh_interface_test_catalogs(self) -> None:
        if self.interface_catalog_loading:
            return
        self.interface_catalog_loading = True
        self._set_interface_test_busy(True)
        self.interface_test_status_var.set("正在读取全部服务器接口目录…")

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                food_items = client.query_food_items()
                food_inventory = client.query_food_inventory()
                bath_items = client.query_bath_items()
                bath_inventory = client.query_bath_inventory()
                stage = client.query_school_stage()
                courses = tuple(item for item in client.query_school_courses(stage) if item.can_do)
                work_catalog = client.query_work_catalog()
                jobs = tuple(
                    item
                    for item in work_catalog.jobs
                    if item.can_do and item.sub_event_type > 0
                )
                rejected = tuple(
                    f"{career.name or career.career_type}: {message}"
                    for career, message in work_catalog.rejected_careers
                )
                work_detail = (
                    f"开放职业 {sum(1 for item in work_catalog.overview.careers if item.available)} 个，"
                    f"可执行岗位 {len(jobs)} 个"
                )
                if jobs:
                    work_detail += "；" + "、".join(
                        f"{job.career_name}/{job.name}({job.sub_event_type})" for job in jobs
                    )
                if rejected:
                    work_detail += f"；当前宠物未满足 {len(rejected)} 个职业要求"
                work_result = InterfaceTestResult(
                    "岗位规则读取", "服务器职业目录", True, work_detail
                )
                adventures = tuple(item for item in client.query_adventure_options() if item.can_do)
                self.events.put(
                    (
                        "interface_catalogs",
                        (
                            food_items,
                            food_inventory,
                            bath_items,
                            bath_inventory,
                            stage,
                            courses,
                            jobs,
                            adventures,
                            rejected,
                            work_result,
                        ),
                    )
                )
            except Exception as exc:
                self.events.put(("interface_catalogs_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _run_interface_test(self, action: str) -> None:
        selections: dict[str, Any] = {}
        try:
            if action == "feed":
                selections["food"] = self.test_food_options[self.test_food_var.get()]
            elif action == "wash":
                selections["bath"] = self.test_bath_options[self.test_bath_var.get()]
            elif action == "school":
                label = self.test_course_var.get()
                sub_event = int(self.course_options.get(label, 0))
                if not sub_event:
                    raise ValueError("请先刷新目录并选择一门具体课程")
                selections.update(label=label, sub_event=sub_event)
            elif action in {"work", "work_hire"}:
                label = self.test_job_var.get()
                career_type, sub_event = self.job_options.get(label, (0, 0))
                if not career_type or not sub_event:
                    raise ValueError("请先刷新目录并选择一个具体岗位")
                selections.update(label=label, career_type=career_type, sub_event=sub_event)
                if action == "work_hire":
                    friend = self.work_hire_friend_options.get(
                        self.test_hire_friend_var.get()
                    )
                    if friend is None or not friend.user_id or not friend.pet_id:
                        raise ValueError("请先刷新好友宠物池并选择一位可雇佣好友")
                    selections["hired_friend"] = friend
            elif action == "adventure":
                label = self.test_adventure_var.get()
                option_name = self.adventure_options.get(label, "")
                if not option_name:
                    raise ValueError("请先刷新目录并选择一个具体冒险")
                selections.update(label=label, option_name=option_name)
        except (KeyError, TypeError, ValueError) as exc:
            self._show_notice("无法测试接口", str(exc), "warning")
            return

        self._set_interface_test_busy(True)
        action_name = {
            "state": "状态读取",
            "feed": "喂食",
            "wash": "洗澡",
            "school": "学习开课",
            "work": "打工开工",
            "work_hire": "雇佣好友开工",
            "adventure": "冒险启动",
            "recall_employed": "被雇佣召回",
        }[action]
        self.interface_test_status_var.set(f"正在执行：{action_name}…")
        self._append_log(f"[{datetime.now():%H:%M:%S}] 接口单项测试开始：{action_name}")

        def worker() -> None:
            try:
                config = self.config_store.data
                runner = InterfaceTestRunner(Scheduler._make_client(config), config)
                if action == "state":
                    result = runner.check_state()
                elif action == "feed":
                    result = runner.feed(*selections["food"])
                elif action == "wash":
                    result = runner.wash(*selections["bath"])
                elif action == "school":
                    result = runner.start_school(selections["sub_event"], selections["label"])
                elif action == "work":
                    result = runner.start_work(
                        selections["career_type"], selections["sub_event"], selections["label"]
                    )
                elif action == "work_hire":
                    friend = selections["hired_friend"]
                    result = runner.start_work(
                        selections["career_type"],
                        selections["sub_event"],
                        selections["label"],
                        friend.user_id,
                        friend.pet_id,
                        friend.nickname or friend.pet_name,
                    )
                elif action == "adventure":
                    result = runner.start_adventure(
                        selections["option_name"], selections["label"]
                    )
                else:
                    result = runner.recall_employed()
                self.events.put(("interface_test_done", result))
            except Exception as exc:
                self.events.put(("interface_test_error", (action_name, str(exc))))

        threading.Thread(target=worker, daemon=True).start()

    def _test_external_notifications(self) -> None:
        try:
            config = self.config_store.data
            for path, (variable, value_type) in self.setting_vars.items():
                if not path.startswith("notifications."):
                    continue
                raw = variable.get()
                value = raw if value_type is bool else value_type(raw)
                deep_set(config, path, value)
            # A manual test targets the selected providers even when automatic
            # failure notifications have not yet been globally enabled.
            config["notifications"]["enabled"] = True
        except Exception as exc:
            self._show_notice("外部通知设置无效", str(exc), "error")
            return
        self.external_notification_test_button.configure(state=tk.DISABLED)
        self._show_notice("正在测试外部通知", "正在向已启用渠道发送测试消息…", "info")

        def worker() -> None:
            try:
                results = NotificationManager(config).send(
                    "QQ 宠物助手测试通知",
                    "外部通知连接测试成功。收到此消息表示该渠道配置可用。",
                    event="test",
                )
                if not results:
                    raise RuntimeError("没有可测试的渠道，请启用渠道并填写必要的令牌或地址")
                self.events.put(("external_notification_test_done", results))
            except Exception as exc:
                self.events.put(("external_notification_test_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _save_settings(self) -> None:
        config = self.config_store.data
        try:
            for path, (variable, value_type) in self.setting_vars.items():
                raw = variable.get()
                if path in CHOICE_FIELDS:
                    if raw not in CHOICE_FIELDS[path]:
                        raise ValueError(f"请选择有效的{path}")
                    value = CHOICE_FIELDS[path][raw]
                else:
                    value = raw if value_type is bool else value_type(raw)
                deep_set(config, path, value)
            selected_label = self.course_var.get()
            if selected_label not in self.course_options:
                raise ValueError("请刷新并重新选择课程")
            config["school"]["course_sub_event"] = self.course_options[selected_label]
            selected_job = self.job_var.get()
            if selected_job not in self.job_options:
                raise ValueError("请刷新并重新选择打工岗位")
            career_type, job_sub_event = self.job_options[selected_job]
            config["work"]["career_type"] = career_type
            config["work"]["job_sub_event"] = job_sub_event
            config["work"]["strategy"] = "shortest_duration"
            hire_mode = str(config["work"].get("hire_mode", "auto"))
            if config["work"].get("employ_friend") and hire_mode == "manual":
                selected_hire = self.work_hire_friend_options.get(
                    self.work_hire_friend_var.get()
                )
                if selected_hire is None:
                    raise ValueError("手动雇佣模式下，请刷新并选择一位有宠物的好友")
                config["work"]["hire_friend_uin"] = selected_hire.user_id
                config["work"]["hire_friend_pet_id"] = selected_hire.pet_id
                config["work"]["hire_friend_name"] = (
                    selected_hire.nickname or selected_hire.pet_name
                )
            elif hire_mode == "auto":
                config["work"]["hire_friend_uin"] = ""
                config["work"]["hire_friend_pet_id"] = ""
                config["work"]["hire_friend_name"] = ""
            selected_adventure = self.adventure_var.get()
            if selected_adventure not in self.adventure_options:
                raise ValueError("请刷新并重新选择冒险")
            config["adventure"]["option_name"] = self.adventure_options[selected_adventure]
            self.config_store.save(config)
        except Exception as exc:
            self._show_notice("设置无效", str(exc), "error")
            return
        self._append_log(f"[{datetime.now():%H:%M:%S}] 设置已保存，下一轮立即生效")
        self._show_notice("设置已保存", "全部设置已保存，下一轮调度立即生效。", "success")

    def _new_scheduler(self) -> Scheduler:
        return Scheduler(
            CONFIG_PATH,
            PROGRESS_PATH,
            log=lambda text: self.events.put(("log", text)),
            status_callback=lambda values, story, state: self.events.put(("status", (values, story, state))),
            activity_callback=lambda text: self.events.put(("activity", text)),
        )

    def _check_for_updates(self) -> None:
        self.update_button.configure(state=tk.DISABLED, text="正在检查更新……")

        def worker() -> None:
            try:
                info = fetch_latest()
                self.events.put(("update_checked", info))
            except Exception as exc:
                self.events.put(("update_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _export_diagnostics(self) -> None:
        default_name = f"qqpet-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.zip"
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="保存脱敏诊断包",
            initialdir=str(Path.home() / "Desktop"),
            initialfile=default_name,
            defaultextension=".zip",
            filetypes=(("ZIP 压缩包", "*.zip"),),
        )
        if not destination:
            return
        self.diagnostics_button.configure(state=tk.DISABLED, text="正在脱敏并导出……")

        def worker() -> None:
            try:
                output = create_diagnostic_bundle(
                    ROOT,
                    self.config_store.data,
                    destination,
                    log_dir=LOG_DIR,
                )
                self.events.put(("diagnostics_done", str(output)))
            except Exception as exc:
                self.events.put(("diagnostics_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _download_update(self, info: UpdateInfo) -> None:
        self.update_button.configure(state=tk.DISABLED, text=f"正在下载 {info.tag}……")

        def progress(received: int, total: int) -> None:
            percent = min(100, int(received * 100 / max(1, total)))
            self.events.put(("update_progress", (info.tag, percent)))

        def worker() -> None:
            try:
                update_root = Path(os.environ.get("LOCALAPPDATA") or ROOT) / "QQPetInterfaceCopilot" / "updates"
                archive = download_update(info, update_root, progress)
                executable = extract_executable(archive, update_root / info.tag)
                self.events.put(("update_ready", (info, executable)))
            except Exception as exc:
                self.events.put(("update_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _start(self) -> None:
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            return
        self.scheduler = self._new_scheduler()
        self.scheduler_thread = threading.Thread(target=self.scheduler.run_forever, daemon=True)
        self.scheduler_thread.start()
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)

    def _stop(self) -> None:
        if self.scheduler:
            self.scheduler.stop()
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)

    def _probe_connection(self) -> None:
        """Report QQ session health independently from pet business reads."""

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                uin = client.check_connection()
                self.events.put(("connection", f"QQ {uin} 已连接"))
            except Exception as exc:
                self.events.put(("connection", "手机 QQ 协议未连接"))
                self.events.put(
                    ("log", f"[{datetime.now():%H:%M:%S}] 手机 QQ 协议连接检查失败：{exc}")
                )

        threading.Thread(target=worker, daemon=True).start()

    def _check_once(self) -> None:
        def worker() -> None:
            scheduler = self._new_scheduler()
            try:
                config = scheduler.config_store.data
                uin = scheduler.client_factory(config).check_connection()
                self.events.put(("connection", f"QQ {uin} 已连接"))
                scheduler.run_once()
            except QQPetEmptyResponse as exc:
                self.events.put(
                    (
                        "log",
                        f"[{datetime.now():%H:%M:%S}] 手机 QQ 协议已连接，"
                        f"但宠物读取接口暂时无响应：{exc}",
                    )
                )
                self.events.put(("connection", "QQ 已连接 · 宠物接口重试中"))
                self.events.put(
                    (
                        "notice",
                        (
                            "宠物接口正在重试",
                            "QQ 登录正常，但桌面端宠物读取接口暂未返回数据。",
                            "warning",
                        ),
                    )
                )
            except QQPetConnectionError as exc:
                self.events.put(("log", f"[{datetime.now():%H:%M:%S}] 检查失败：{exc}"))
                self.events.put(("connection", "手机 QQ 协议未连接"))
                self.events.put(("notice", ("连接失败", str(exc), "error")))
            except Exception as exc:
                self.events.put(("log", f"[{datetime.now():%H:%M:%S}] 检查失败：{exc}"))
                self.events.put(("connection", "QQ 已连接 · 宠物接口异常"))
                self.events.put(("notice", ("宠物接口异常", str(exc), "error")))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _friend_choice_rows(
        friends,
        opponent_by_uin: dict[str, PKOpponent],
        pool_error: str,
        hide_without_pet: bool,
    ) -> list[tuple[str, str]]:
        rows: list[tuple[int, str, str, str]] = []
        for friend in friends:
            uin = friend.user_id
            display = friend.remark or friend.nickname or uin
            if uin in opponent_by_uin:
                rank, pet_mark = 0, "有宠物"
            elif pool_error:
                rank, pet_mark = 1, "宠物资料未知"
            else:
                rank, pet_mark = 2, "服务器未返回宠物"
            if hide_without_pet and rank == 2:
                continue
            label = f"{display}｜QQ {uin}｜{pet_mark}"
            rows.append((rank, display.casefold(), uin, label))
        rows.sort(key=lambda item: (item[0], item[1], item[2]))
        return [(label, uin) for _rank, _display, uin, label in rows]

    def _populate_friend_choices(self) -> None:
        previous_manual_uin = self.manual_pk_friend_uins.get(
            self.manual_pk_friend_var.get(), ""
        )
        previous_care_uin = self.friend_care_friend_uins.get(
            self.friend_care_friend_var.get(), ""
        )
        previous_hire_uin = ""
        previous_hire = self.work_hire_friend_options.get(self.work_hire_friend_var.get())
        if previous_hire:
            previous_hire_uin = previous_hire.user_id
        configured_uin = str(self.config_store.data["pk"].get("opponent_uin", ""))
        rows = self._friend_choice_rows(
            self.manual_pk_all_friends,
            self.manual_pk_cached_opponents,
            self.manual_pk_pool_error,
            self.hide_friends_without_pet_var.get(),
        )
        uins = {label: uin for label, uin in rows}
        if configured_uin and configured_uin not in uins.values():
            fallback = self.manual_pk_cached_opponents.get(configured_uin)
            if fallback:
                display = fallback.nickname or fallback.pet_name or configured_uin
                label = f"{display}｜QQ {configured_uin}｜备用固定对手"
                rows.insert(0, (label, configured_uin))
                uins = {item_label: uin for item_label, uin in rows}
        options = [label for label, _uin in rows]
        self.manual_pk_friend_uins = uins
        self.friend_care_friend_uins = dict(uins)
        self.manual_pk_friend_combo.configure(values=tuple(options))
        self.friend_care_friend_combo.configure(values=tuple(options))

        hire_rows: list[tuple[str, PKOpponent]] = []
        own_uin = str(self.config_store.data["account"].get("uin", "")).strip()
        friend_names = {
            friend.user_id: friend.remark or friend.nickname
            for friend in self.manual_pk_all_friends
        }
        for opponent in self.manual_pk_cached_opponents.values():
            if (
                not opponent.user_id
                or not opponent.pet_id
                or opponent.user_id == own_uin
            ):
                continue
            display = (
                friend_names.get(opponent.user_id)
                or opponent.nickname
                or opponent.pet_name
                or opponent.user_id
            )
            label = f"{display}｜QQ {opponent.user_id}｜petId 已确认"
            hire_rows.append((label, opponent))
        hire_rows.sort(key=lambda item: ((item[1].nickname or item[0]).casefold(), item[1].user_id))
        self.work_hire_friend_options = dict(hire_rows)
        hire_labels = tuple(label for label, _item in hire_rows)
        self.work_hire_friend_combo.configure(values=hire_labels)
        self.test_hire_friend_combo.configure(values=hire_labels)
        configured_hire_uin = str(
            self.config_store.data["work"].get("hire_friend_uin", "")
        ).strip()
        selected_hire_uin = previous_hire_uin or configured_hire_uin
        selected_hire = next(
            (
                label
                for label, opponent in hire_rows
                if opponent.user_id == selected_hire_uin
            ),
            next(iter(hire_labels), "当前没有可雇佣的宠物好友"),
        )
        self.work_hire_friend_var.set(selected_hire)
        self.test_hire_friend_var.set(selected_hire)

        manual_uin = previous_manual_uin or configured_uin
        selected = next(
            (label for label in options if uins[label] == manual_uin),
            "请选择好友" if options else "未读取到符合条件的好友",
        )
        self.manual_pk_friend_var.set(selected)
        care_selected = next(
            (label for label in options if uins[label] == previous_care_uin),
            "请选择好友" if options else "未读取到符合条件的好友",
        )
        self.friend_care_friend_var.set(care_selected)
        if selected in uins:
            self._manual_pk_friend_selected()
        if care_selected in uins:
            self._friend_care_friend_selected()

        pet_count = len(self.manual_pk_cached_opponents)
        filter_text = "；已隐藏确认无宠物好友" if self.hide_friends_without_pet_var.get() else ""
        if self.manual_pk_pool_error:
            self.manual_pk_status_var.set(
                f"宠物好友池当前不可用；已加载抓包中的 {self.manual_pk_captured_count} 位宠物好友；"
                f"当前显示 {len(options)} 位{filter_text}"
            )
        else:
            self.manual_pk_status_var.set(
                f"已读取 {len(self.manual_pk_all_friends)} 位 QQ 好友，其中 {pet_count} 位返回宠物资料；"
                f"当前显示 {len(options)} 位{filter_text}"
            )

    def _friend_pet_filter_changed(self) -> None:
        if self.manual_pk_all_friends:
            self._populate_friend_choices()

    def _refresh_manual_pk_friends(self) -> None:
        self.manual_pk_refresh_button.configure(state=tk.DISABLED)
        self.friend_care_refresh_button.configure(state=tk.DISABLED)
        self.manual_pk_lookup_button.configure(state=tk.DISABLED)
        self.manual_pk_status_var.set("正在读取 QQ 好友和宠物资料…")

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                friends = client.query_friend_list()
                pool_error = ""
                try:
                    opponents = client.query_pk_friend_candidates()
                except Exception as exc:
                    opponents = ()
                    pool_error = str(exc)
                captured = load_latest_friend_pet_capture(FRIEND_VISIT_DIR)
                merged = {item.user_id: item for item in captured}
                merged.update({item.user_id: item for item in opponents})
                opponents = tuple(merged.values())
                fallback = self._configured_pk_opponent(config)
                if fallback and all(item.user_id != fallback.user_id for item in opponents):
                    opponents = (*opponents, fallback)
                self.events.put(
                    ("manual_pk_friends", (friends, opponents, pool_error, len(captured)))
                )
            except Exception as exc:
                self.events.put(("manual_pk_friends_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _manual_pk_friend_selected(self, _event=None) -> None:
        label = self.manual_pk_friend_var.get()
        uin = self.manual_pk_friend_uins.get(label, "")
        if not uin:
            return
        self.manual_pk_uin_var.set(uin)
        cached = self.manual_pk_cached_opponents.get(uin)
        if cached:
            self.manual_pk_name_var.set(cached.nickname or cached.pet_name)
            self.manual_pk_pet_id_var.set(cached.pet_id)
            self.manual_pk_power_var.set(str(cached.power or "--"))
        else:
            self.manual_pk_name_var.set(label.split("｜", 1)[0])
            self.manual_pk_pet_id_var.set("")
            self.manual_pk_power_var.set("--")
        self._lookup_manual_pk_opponent()

    def _lookup_manual_pk_opponent(self) -> None:
        uin = self.manual_pk_uin_var.get().strip()
        if not uin.isdigit():
            self._show_notice("无法检索", "请输入有效的对手 QQ 号", "warning")
            return
        self.manual_pk_lookup_button.configure(state=tk.DISABLED)
        self.manual_pk_run_button.configure(state=tk.DISABLED)
        self.manual_pk_status_var.set(f"正在从服务器检索 QQ {uin} 的宠物 ID 和战力…")

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                fallback = self.manual_pk_cached_opponents.get(uin)
                opponent = client.resolve_pk_opponent(
                    uin, fallback or self._configured_pk_opponent(config)
                )
                self.events.put(("manual_pk_resolved", opponent))
            except Exception as exc:
                self.events.put(("manual_pk_resolve_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _run_manual_pk(self) -> None:
        uin = self.manual_pk_uin_var.get().strip()
        pet_id = self.manual_pk_pet_id_var.get().strip()
        if not uin.isdigit() or not pet_id:
            self._show_notice(
                "无法开始 PK", "请先选择好友并成功检索宠物资料", "warning"
            )
            return
        try:
            requested_count = int(self.manual_pk_count_var.get())
        except (TypeError, ValueError, tk.TclError):
            requested_count = 0
        if not 1 <= requested_count <= 99:
            self._show_notice(
                "无法开始 PK", "本次连续 PK 次数必须为 1–99", "warning"
            )
            return
        self.manual_pk_run_button.configure(state=tk.DISABLED)
        self.manual_pk_lookup_button.configure(state=tk.DISABLED)
        self.manual_pk_refresh_button.configure(state=tk.DISABLED)
        self.manual_pk_count_spinbox.configure(state=tk.DISABLED)
        self.manual_pk_status_var.set(
            f"正在连续 PK：0/{requested_count}，每场均等待服务器结算验证…"
        )
        self._append_log(
            f"[{datetime.now():%H:%M:%S}] 手动 PK 已开始："
            f"{self.manual_pk_name_var.get() or uin}（QQ {uin}），计划 {requested_count} 场"
        )

        def worker() -> None:
            try:
                config = self.config_store.data
                if config["safety"]["safe_mode"]:
                    raise RuntimeError("安全模式已开启，请先在设置中关闭后再手动 PK")
                client = Scheduler._make_client(config)
                opponent = client.resolve_pk_opponent(
                    uin, self._configured_pk_opponent(config)
                )
                if opponent.pet_id != pet_id:
                    raise RuntimeError("对手宠物 ID 已变化，请重新检索后再 PK")
                # PK is a side task: an active school/work/adventure story does
                # not block a manually requested battle.
                results = []
                for index in range(1, requested_count + 1):
                    try:
                        result = client.perform_pk(
                            opponent.user_id,
                            opponent.pet_id,
                            float(config["pk"].get("wait_seconds", 9)),
                        )
                    except Exception as exc:
                        self.events.put(
                            (
                                "manual_pk_batch_error",
                                (opponent, tuple(results), requested_count, str(exc)),
                            )
                        )
                        return
                    results.append(result)
                    self.events.put(
                        ("manual_pk_progress", (opponent, index, requested_count, result))
                    )
                self.events.put(("manual_pk_done", (opponent, tuple(results))))
            except Exception as exc:
                self.events.put(("manual_pk_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _run_friend_visits_once(self) -> None:
        self.friend_visit_button.configure(state=tk.DISABLED)
        self.events.put(("log", f"[{datetime.now():%H:%M:%S}] 正在读取 QQ 好友列表"))

        def worker() -> None:
            try:
                config = self.config_store.data
                client = Scheduler._make_client(config)
                login_uin = client.check_connection()
                friends = client.query_friend_list()
                visit_config = config["friend_visits"]
                candidates = eligible_friends(
                    friends,
                    login_uin,
                    str(visit_config.get("whitelist", "")),
                    str(visit_config.get("exclude", "")),
                )
                pool_error = ""
                try:
                    live_pets = client.query_pk_friend_candidates()
                except Exception as exc:
                    live_pets = ()
                    pool_error = str(exc)
                captured_pets = load_latest_friend_pet_capture(FRIEND_VISIT_DIR)
                verified_pets = current_pet_friends(friends, live_pets, captured_pets)
                verified_pets.pop(login_uin, None)
                progress = FriendVisitProgress(FRIEND_VISIT_DIR)
                if not pool_error:
                    for friend in candidates:
                        if friend.user_id not in verified_pets and not progress.attempted(friend.user_id):
                            progress.mark(
                                friend.user_id,
                                "no_pet",
                                detail="服务器当前宠物好友池未返回该 QQ",
                            )
                candidates = tuple(
                    friend
                    for friend in candidates
                    if str(friend.user_id) in verified_pets
                    and not progress.attempted(friend.user_id)
                )
                limit = int(visit_config.get("max_per_day", 0))
                if limit > 0:
                    summary_before = progress.summary()
                    used = summary_before["success"] + summary_before["already_visited"]
                    candidates = candidates[: max(0, limit - used)]
                protocol_state = "no_candidates"
                summary_before = progress.summary()
                processed = sum(summary_before.values())
                protocol_detail = (
                    f"今日记录已处理 {processed} 位宠物好友（成功 "
                    f"{summary_before['success']}、无宠物 {summary_before['no_pet']}、"
                    f"已访问 {summary_before['already_visited']}、失败 "
                    f"{summary_before['failed']}），为避免重复访问或点赞，本轮未重发"
                )
                visited = 0
                failed = 0
                if candidates and config["safety"].get("safe_mode", True):
                    protocol_state = "safe_mode"
                    protocol_detail = f"安全模式：识别到 {len(candidates)} 位候选，未发送访问"
                elif candidates:
                    for index, friend in enumerate(candidates):
                        pet = verified_pets[friend.user_id]
                        try:
                            path, response, after_rules = client.visit_friend_verified(
                                friend.user_id, pet.pet_id
                            )
                        except Exception as exc:
                            progress.mark(
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
                                    poke_response = client.poke_friend(friend.user_id)
                                    poked = bool(poke_response.body)
                                    detail += (
                                        "；踩踩已确认" if poked else "；踩踩未返回业务确认"
                                    )
                                except Exception as exc:
                                    poke_error = str(exc)
                                    if "136202" in poke_error or "不能重复点赞" in poke_error:
                                        poked = True
                                        detail += "；踩踩今日已完成（服务器拒绝重复点赞）"
                                    else:
                                        detail += f"；踩踩失败：{poke_error}"
                            # 访问已经验证成功后，无论踩踩结果如何都保留访问成功。
                            progress.mark(
                                friend.user_id,
                                "success",
                                pet_id=pet.pet_id,
                                detail=detail,
                                poked=poked,
                            )
                            visited += 1
                        if index + 1 < len(candidates):
                            minimum = float(visit_config.get("interval_min_seconds", 3))
                            maximum = float(visit_config.get("interval_max_seconds", 5))
                            time.sleep(random.uniform(minimum, max(minimum, maximum)))
                    protocol_state = "visited" if visited else "visit_failed"
                    protocol_detail = f"真实访问成功 {visited} 人，失败 {failed} 人"
                elif pool_error:
                    protocol_state = "pool_failed"
                    protocol_detail = f"宠物好友池读取失败：{pool_error}"
                progress.record_scan(len(friends), len(candidates))
                self.events.put(
                    (
                        "friend_visit_scan",
                        (
                            len(friends),
                            len(candidates),
                            len(verified_pets),
                            progress.summary(),
                            protocol_state,
                            protocol_detail,
                            visited,
                            failed,
                        ),
                    )
                )
            except Exception as exc:
                self.events.put(("friend_visit_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind.endswith("_error") and kind not in {
                    "manual_pk_batch_error",
                    "interface_test_error",
                    "update_error",
                    "diagnostics_error",
                }:
                    self._show_notice("操作失败", str(payload), "error")
                if kind == "log":
                    self._append_log(payload)
                elif kind == "update_checked":
                    info = payload
                    self.update_button.configure(
                        state=tk.NORMAL, text=f"检查更新（当前 v{__version__}）"
                    )
                    if not is_newer(info.version, __version__):
                        self._show_notice(
                            "已经是最新版",
                            f"当前版本 v{__version__}，GitHub 最新正式版 {info.tag}。",
                            "success",
                        )
                    elif messagebox.askyesno(
                        "发现新版本",
                        f"当前版本：v{__version__}\n最新版本：{info.tag}\n\n"
                        f"{info.name}\n\n是否下载并自动更新？",
                    ):
                        self._download_update(info)
                elif kind == "update_progress":
                    tag, percent = payload
                    self.update_button.configure(text=f"正在下载 {tag}：{percent}%")
                elif kind == "update_ready":
                    info, executable = payload
                    self.update_button.configure(state=tk.NORMAL, text=f"安装 {info.tag}")
                    if not getattr(sys, "frozen", False):
                        self._show_notice(
                            "新版已下载",
                            f"源码运行模式不会自动覆盖文件。新版已保存到：{executable}",
                            "info",
                            12000,
                        )
                    elif messagebox.askyesno(
                        "安装更新",
                        f"{info.tag} 已下载并通过 SHA-256 校验。\n\n"
                        "现在退出助手、安装并自动重新打开吗？",
                    ):
                        if self.scheduler:
                            self.scheduler.stop()
                        schedule_windows_install(executable)
                        self.destroy()
                elif kind == "update_error":
                    self.update_button.configure(
                        state=tk.NORMAL, text=f"检查更新（当前 v{__version__}）"
                    )
                    self._show_notice("更新失败", str(payload), "error", 12000)
                elif kind == "diagnostics_done":
                    self.diagnostics_button.configure(
                        state=tk.NORMAL, text="导出脱敏诊断包"
                    )
                    self._show_notice(
                        "诊断包已保存",
                        f"已保存到：{payload}\n请检查后再自行发送，程序没有自动上传。",
                        "success",
                        12000,
                    )
                elif kind == "diagnostics_error":
                    self.diagnostics_button.configure(
                        state=tk.NORMAL, text="导出脱敏诊断包"
                    )
                    self._show_notice("诊断包导出失败", str(payload), "error", 12000)
                elif kind == "notice":
                    title, message, level = payload
                    self._show_notice(str(title), str(message), str(level))
                elif kind == "external_notification_test_done":
                    results = tuple(payload)
                    succeeded = [item.channel for item in results if item.succeeded]
                    failed = [
                        f"{item.channel}: {item.detail}"
                        for item in results
                        if not item.succeeded
                    ]
                    if failed:
                        self._show_notice(
                            "外部通知测试完成",
                            f"成功 {len(succeeded)} 个，失败 {len(failed)} 个："
                            + "；".join(failed),
                            "warning",
                            10000,
                        )
                    else:
                        self._show_notice(
                            "外部通知测试成功",
                            "已送达：" + "、".join(succeeded),
                            "success",
                        )
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 外部通知测试："
                        f"成功 {succeeded or '无'}，失败 {failed or '无'}"
                    )
                    self.external_notification_test_button.configure(state=tk.NORMAL)
                elif kind == "external_notification_test_error":
                    self.external_notification_test_button.configure(state=tk.NORMAL)
                elif kind == "interface_catalogs":
                    (
                        food_items,
                        food_inventory,
                        bath_items,
                        bath_inventory,
                        stage,
                        courses,
                        jobs,
                        adventures,
                        rejected,
                        work_result,
                    ) = payload
                    food_options = {}
                    for item in food_items:
                        label = f"{item.name}｜库存 {item.balance}｜foodId {item.food_id}"
                        food_options[label] = (item.food_id, item.name)
                    if not food_options:
                        food_options[
                            f"默认饼干（库存 {food_inventory.biscuits}，已验证）"
                        ] = ("", "默认饼干")
                    self.test_food_options = food_options
                    self.test_food_combo.configure(values=tuple(food_options))
                    self.test_food_var.set(next(iter(food_options)))

                    bath_names = {item.item_id: item.name for item in bath_items}
                    bath_options = {}
                    for item_id, fallback in (("1", "香皂片"), ("2", "沐浴球")):
                        name = bath_names.get(item_id, fallback)
                        label = f"{name}｜库存 {bath_inventory.count(item_id)}｜itemId {item_id}"
                        bath_options[label] = (item_id, name)
                    self.test_bath_options = bath_options
                    self.test_bath_combo.configure(values=tuple(bath_options))
                    self.test_bath_var.set(next(iter(bath_options)))

                    course_options = {
                        f"{item.name}｜{item.duration}｜{item.reward}": item.sub_event_type
                        for item in courses
                    }
                    self.course_options.update(course_options)
                    self.test_course_combo.configure(values=tuple(course_options))
                    self.test_course_var.set(
                        next(iter(course_options), "当前阶段没有可执行课程")
                    )

                    job_options = {
                        f"{item.career_name}｜{item.name}｜{item.duration}｜收益 {item.reward}": (
                            item.career_type,
                            item.sub_event_type,
                        )
                        for item in jobs
                    }
                    self.job_options.update(job_options)
                    self.test_job_combo.configure(values=tuple(job_options))
                    self.test_job_var.set(next(iter(job_options), "当前没有可执行岗位"))

                    adventure_options = {
                        f"{item.name}｜{item.duration}｜{item.cost}": item.name
                        for item in adventures
                    }
                    self.adventure_options.update(adventure_options)
                    self.test_adventure_combo.configure(values=tuple(adventure_options))
                    self.test_adventure_var.set(
                        next(iter(adventure_options), "当前没有可执行冒险")
                    )
                    stage_name = {
                        0: "学前辅导",
                        1: "初级学园",
                        2: "中级学园",
                        3: "高级学园",
                        4: "进修学院",
                    }.get(stage, f"阶段 {stage}")
                    rejected_text = f"；拒绝 {len(rejected)} 个职业" if rejected else ""
                    food_note = ""
                    if food_inventory.shrimp > 0 and not any(
                        "虾" in item.name for item in food_items
                    ):
                        food_note = (
                            f"；虾仁库存 {food_inventory.shrimp}，但本次目录未下发其 foodId，"
                            "因此未开放虾仁真实测试"
                        )
                    detail = (
                        f"目录刷新成功：食物 {len(food_items)}、洗护 {len(bath_items)}、"
                        f"{stage_name}课程 {len(courses)}、可执行岗位 {len(jobs)}、"
                        f"冒险 {len(adventures)}{rejected_text}{food_note}。{work_result.detail}"
                    )
                    self.interface_test_status_var.set(detail)
                    self._append_log(f"[{datetime.now():%H:%M:%S}] 接口目录检查：{detail}")
                    self._set_interface_test_busy(False)
                    self.interface_catalog_loading = False
                    self.interface_catalog_loaded = True
                elif kind == "interface_catalogs_error":
                    self.interface_test_status_var.set(f"接口目录刷新失败：{payload}")
                    self._set_interface_test_busy(False)
                    self.interface_catalog_loading = False
                elif kind == "interface_test_done":
                    result = payload
                    outcome = "成功" if result.succeeded else "未验证生效"
                    detail = f"{result.action}｜{result.target}｜{outcome}：{result.detail}"
                    self.interface_test_status_var.set(detail)
                    self._append_log(f"[{datetime.now():%H:%M:%S}] 接口单项测试：{detail}")
                    self._show_notice(
                        "接口测试成功" if result.succeeded else "接口返回但未验证生效",
                        detail,
                        "success" if result.succeeded else "warning",
                        10000,
                    )
                    self._set_interface_test_busy(False)
                elif kind == "interface_test_error":
                    action_name, error = payload
                    detail = f"{action_name}失败：{error}"
                    self.interface_test_status_var.set(detail)
                    self._append_log(f"[{datetime.now():%H:%M:%S}] 接口单项测试失败：{detail}")
                    self._show_notice("接口测试失败", detail, "error", 10000)
                    self._set_interface_test_busy(False)
                elif kind == "own_pet_profile":
                    profile = payload
                    self.setting_vars["account.uin"][0].set(profile.user_id)
                    self.setting_vars["account.pet_id"][0].set(profile.pet_id)
                    config = self.config_store.data
                    config["account"]["uin"] = profile.user_id
                    config["account"]["pet_id"] = profile.pet_id
                    self.config_store.save(config)
                    self.pet_id_lookup_button.configure(state=tk.NORMAL)
                    pet_label = f"“{profile.pet_name}”" if profile.pet_name else "当前宠物"
                    self._show_notice(
                        "宠物 ID 已保存",
                        f"已从服务器读取{pet_label}，以后可直接在电脑上运行。",
                        "success",
                    )
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 已从服务器读取并保存 QQ "
                        f"{profile.user_id} 的宠物 ID"
                    )
                elif kind == "own_pet_profile_error":
                    self.pet_id_lookup_button.configure(state=tk.NORMAL)
                elif kind == "status":
                    values, story, state = payload
                    # 供菜单栏显示「当前动作」（学习中/打工中/冒险中/空闲）
                    kind = (
                        Scheduler._story_kind(story.story_id)
                        if (story is not None and story.story_id)
                        else None
                    )
                    self._current_action = {
                        "school": "学习中", "work": "打工中", "adventure": "冒险中",
                    }.get(kind, "空闲")
                    self.status_vars["connection"].set("已连接")
                    self.hero_connection_label.configure(
                        background="#e1f7ee", foreground="#187d53"
                    )
                    self.status_vars["gold"].set(f"{values.gold:.2f}")
                    inventory = state.get("food_inventory", {})
                    self.status_vars["food"].set(
                        f"饼干 {inventory.get('biscuits', '--')} / 虾仁 {inventory.get('shrimp', '--')}"
                    )
                    bath_inventory = state.get("bath_inventory", {})
                    self.status_vars["bath"].set(
                        f"香皂片 {bath_inventory.get('soap', '--')} / "
                        f"沐浴球 {bath_inventory.get('bath_ball', '--')}"
                    )
                    self.status_vars["mood"].set(f"{values.feel:.1f}/100")
                    self.status_vars["hunger"].set(f"{values.hunger:.1f}/100")
                    self.status_vars["clean"].set(f"{values.clean:.1f}/100")
                    self.optimization_auto_var.set(
                        state.get(
                            "optimization_auto_summary",
                            "等待调度器自动读取服务器目录",
                        )
                    )
                    counts = state["counts"]
                    self.status_vars["counts"].set(
                        f"学{counts['school']} 工{counts['work']} "
                        f"冒{counts['adventure']} PK{counts.get('pk', 0)}"
                    )
                    pk_summary = state.get("pk_summary", {})
                    pool_status = pk_summary.get("friend_pool_status")
                    pool_text = {
                        "ready": f"好友池 {pk_summary.get('friend_pool_count', 0)}",
                        "unavailable": "好友池暂不可用",
                        "pending": "好友池待刷新",
                    }.get(pool_status, "")
                    self.status_vars["pk"].set(
                        f"成功 {pk_summary.get('success', 0)} / "
                        f"失败 {pk_summary.get('failed', 0)} / "
                        f"金币 {pk_summary.get('gold_earned', 0):.0f}"
                        + (
                            " / 今日批次已完成"
                            if pk_summary.get("daily_run_completed")
                            else " / 等待每日批次"
                        )
                        + (f" / {pool_text}" if pool_text else "")
                    )
                    visit_summary = state.get("friend_visit_summary", {})
                    if visit_summary:
                        self.status_vars["friend_visits"].set(
                            f"成功{visit_summary.get('success', 0)} "
                            f"无宠物{visit_summary.get('no_pet', 0)} "
                            f"已访问{visit_summary.get('already_visited', 0)} "
                            f"失败{visit_summary.get('failed', 0)}"
                        )
                    care_summary = state.get("friend_care_summary", {})
                    if care_summary:
                        care_state = "开启" if care_summary.get("enabled") else "关闭"
                        self.status_vars["friend_care"].set(
                            f"{care_state} / 名单 {care_summary.get('targets', 0)} / "
                            f"今日喂食 {care_summary.get('feeds', 0)} / "
                            f"今日清洁 {care_summary.get('washes', 0)}"
                        )
                elif kind == "connection":
                    connection_text = str(payload)
                    self.status_vars["connection"].set(connection_text)
                    is_connected = "已连接" in connection_text
                    is_degraded = "重试" in connection_text or "异常" in connection_text
                    self.hero_connection_label.configure(
                        background="#fff0d7" if is_degraded else (
                            "#e1f7ee" if is_connected else "#fff0d7"
                        ),
                        foreground="#9b6109" if is_degraded else (
                            "#187d53" if is_connected else "#9b6109"
                        ),
                    )
                elif kind == "activity":
                    self.status_vars["story"].set(str(payload))
                elif kind == "friend_visit_scan":
                    (
                        total,
                        eligible,
                        verified_pet_count,
                        summary,
                        protocol_state,
                        protocol_detail,
                        visited,
                        failed,
                    ) = payload
                    self.status_vars["friend_visits"].set(
                        f"成功{summary['success']} 无宠物{summary['no_pet']} "
                        f"已访问{summary['already_visited']} 失败{summary['failed']}"
                    )
                    message = (
                        f"[{datetime.now():%H:%M:%S}] 好友列表共 {total} 人，"
                        f"已确认有宠物 {verified_pet_count} 人，本轮候选 {eligible} 人；"
                        f"{protocol_detail}。"
                    )
                    if protocol_state == "visited":
                        message += f"本轮真实访问 {visited} 人，失败 {failed} 人"
                    elif protocol_state == "visit_failed":
                        message += f"已发送 {failed} 个访问请求，但均未通过二次验证"
                    else:
                        message += "本轮真实访问 0 人，未发送访问或踩踩写请求"
                    self._append_log(message)
                    self.friend_visit_button.configure(state=tk.NORMAL)
                elif kind == "friend_visit_error":
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 好友访问准备失败：{payload}"
                    )
                    self.friend_visit_button.configure(state=tk.NORMAL)
                elif kind == "manual_pk_friends":
                    friends, opponents, pool_error, captured_count = payload
                    self.manual_pk_all_friends = tuple(friends)
                    self.manual_pk_cached_opponents = {
                        item.user_id: item for item in opponents
                    }
                    self.manual_pk_pool_error = pool_error
                    self.manual_pk_captured_count = captured_count
                    self._populate_friend_choices()
                    self.manual_pk_refresh_button.configure(state=tk.NORMAL)
                    self.friend_care_refresh_button.configure(state=tk.NORMAL)
                    self.manual_pk_lookup_button.configure(state=tk.NORMAL)
                elif kind == "manual_pk_friends_error":
                    self.manual_pk_status_var.set(f"好友读取失败：{payload}")
                    self.manual_pk_refresh_button.configure(state=tk.NORMAL)
                    self.friend_care_refresh_button.configure(state=tk.NORMAL)
                    self.manual_pk_lookup_button.configure(state=tk.NORMAL)
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 手动 PK 好友读取失败：{payload}"
                    )
                elif kind == "friend_care_target_resolved":
                    opponent, values = payload
                    config = self.config_store.data
                    targets = list(config["friend_care"].get("targets", []))
                    target = {
                        "uin": opponent.user_id,
                        "pet_id": opponent.pet_id,
                        "name": opponent.nickname or opponent.pet_name or opponent.user_id,
                    }
                    existing = next(
                        (index for index, item in enumerate(targets) if str(item["uin"]) == opponent.user_id),
                        None,
                    )
                    if existing is None:
                        targets.append(target)
                    else:
                        targets[existing] = target
                    config["friend_care"]["targets"] = targets
                    config["friend_care"]["enabled"] = True
                    self.config_store.save(config)
                    if "friend_care.enabled" in self.setting_vars:
                        self.setting_vars["friend_care.enabled"][0].set(True)
                    self._reload_friend_care_targets()
                    self.friend_care_add_button.configure(state=tk.NORMAL)
                    self.friend_care_status_var.set(
                        f"已加入 {target['name']}（QQ {target['uin']}）；"
                        f"当前体力 {values.hunger:.1f}/100、清洁 {values.clean:.1f}/100，"
                        f"自动照顾已启用"
                    )
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 已加入自动照顾名单："
                        f"{target['name']}（QQ {target['uin']}），"
                        f"petId={target['pet_id']}，当前体力 {values.hunger:.1f}、"
                        f"清洁 {values.clean:.1f}"
                    )
                elif kind == "friend_care_target_error":
                    self.friend_care_add_button.configure(state=tk.NORMAL)
                    self.friend_care_status_var.set(f"加入照顾名单失败：{payload}")
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 加入好友照顾名单失败：{payload}"
                    )
                elif kind == "manual_pk_resolved":
                    opponent = payload
                    self.manual_pk_uin_var.set(opponent.user_id)
                    self.manual_pk_pet_id_var.set(opponent.pet_id)
                    self.manual_pk_name_var.set(
                        opponent.nickname or opponent.pet_name or opponent.user_id
                    )
                    self.manual_pk_power_var.set(str(opponent.power))
                    self.manual_pk_cached_opponents[opponent.user_id] = opponent
                    config = self.config_store.data
                    config["pk"]["opponent_uin"] = opponent.user_id
                    config["pk"]["opponent_pet_id"] = opponent.pet_id
                    config["pk"]["opponent_name"] = (
                        opponent.nickname or opponent.pet_name
                    )
                    config["pk"]["opponent_power"] = opponent.power
                    self.config_store.save(config)
                    self.manual_pk_status_var.set(
                        f"检索成功：{opponent.pet_name or '宠物'}，战力 {opponent.power}；"
                        "已保存为备用固定对手"
                    )
                    self.manual_pk_lookup_button.configure(state=tk.NORMAL)
                    self.manual_pk_run_button.configure(state=tk.NORMAL)
                    self.manual_pk_refresh_button.configure(state=tk.NORMAL)
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 手动 PK 对手已解析："
                        f"{opponent.nickname or opponent.user_id}，QQ {opponent.user_id}，"
                        f"petId={opponent.pet_id}，战力 {opponent.power}"
                    )
                elif kind == "manual_pk_resolve_error":
                    self.manual_pk_pet_id_var.set("")
                    self.manual_pk_power_var.set("--")
                    self.manual_pk_status_var.set(f"宠物资料检索失败：{payload}")
                    self.manual_pk_lookup_button.configure(state=tk.NORMAL)
                    self.manual_pk_run_button.configure(state=tk.DISABLED)
                    self.manual_pk_refresh_button.configure(state=tk.NORMAL)
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 手动 PK 对手检索失败：{payload}"
                    )
                elif kind == "manual_pk_progress":
                    opponent, completed, requested, result = payload
                    self.manual_pk_status_var.set(
                        f"连续 PK 进度 {completed}/{requested}："
                        f"金币 {result.gold_delta:+.0f}，心情 {result.mood_delta:+.0f}，"
                        f"体力 -{result.hunger_cost:.0f}，清洁 -{result.clean_cost:.0f}"
                    )
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 手动 PK 第 {completed}/{requested} 场"
                        f"已由服务器验证："
                        f"QQ {opponent.user_id}，storyId={result.story_id}，"
                        f"金币 {result.gold_delta:+.0f}，心情 {result.mood_delta:+.0f}"
                    )
                elif kind == "manual_pk_done":
                    opponent, results = payload
                    completed = len(results)
                    gold = sum(item.gold_delta for item in results)
                    mood = sum(item.mood_delta for item in results)
                    hunger = sum(item.hunger_cost for item in results)
                    clean = sum(item.clean_cost for item in results)
                    self.manual_pk_status_var.set(
                        f"连续 PK 完成：{opponent.nickname or opponent.user_id}，"
                        f"共 {completed} 场；金币 {gold:+.0f}，心情 {mood:+.0f}，"
                        f"体力 -{hunger:.0f}，清洁 -{clean:.0f}"
                    )
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 手动连续 PK 全部完成并经服务器验证："
                        f"QQ {opponent.user_id}，共 {completed} 场，金币 {gold:+.0f}，"
                        f"心情 {mood:+.0f}；未写入自动 PK 每日进度"
                    )
                    self.manual_pk_lookup_button.configure(state=tk.NORMAL)
                    self.manual_pk_run_button.configure(state=tk.NORMAL)
                    self.manual_pk_refresh_button.configure(state=tk.NORMAL)
                    self.manual_pk_count_spinbox.configure(state=tk.NORMAL)
                elif kind == "manual_pk_batch_error":
                    opponent, results, requested, error = payload
                    completed = len(results)
                    self._show_notice(
                        "连续 PK 已停止",
                        f"已成功 {completed}/{requested} 场；{error}",
                        "error",
                    )
                    self.manual_pk_status_var.set(
                        f"连续 PK 已停止：成功 {completed}/{requested} 场；{error}"
                    )
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 手动连续 PK 中途停止："
                        f"QQ {opponent.user_id}，已成功 {completed}/{requested} 场；{error}"
                    )
                    self.manual_pk_lookup_button.configure(state=tk.NORMAL)
                    self.manual_pk_run_button.configure(state=tk.NORMAL)
                    self.manual_pk_refresh_button.configure(state=tk.NORMAL)
                    self.manual_pk_count_spinbox.configure(state=tk.NORMAL)
                elif kind == "manual_pk_error":
                    self.manual_pk_status_var.set(f"手动 PK 失败：{payload}")
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 手动 PK 失败：{payload}"
                    )
                    self.manual_pk_lookup_button.configure(state=tk.NORMAL)
                    self.manual_pk_run_button.configure(state=tk.NORMAL)
                    self.manual_pk_refresh_button.configure(state=tk.NORMAL)
                    self.manual_pk_count_spinbox.configure(state=tk.NORMAL)
                elif kind == "school_courses":
                    stage, courses = payload
                    previous = int(self.config_store.data["school"].get("course_sub_event", 0))
                    options = {"自动选择当前属性最短时长": 0}
                    selected_label = "自动选择当前属性最短时长"
                    for course in courses:
                        if not course.can_do:
                            continue
                        label = f"{course.name}｜{course.duration}｜{course.reward}"
                        options[label] = course.sub_event_type
                        if course.sub_event_type == previous:
                            selected_label = label
                    self.course_options = options
                    self.course_combo.configure(values=tuple(options))
                    self.course_var.set(selected_label)
                    test_options = {
                        label: sub_event
                        for label, sub_event in options.items()
                        if sub_event > 0
                    }
                    self.test_course_combo.configure(values=tuple(test_options))
                    self.test_course_var.set(
                        next(iter(test_options), "当前阶段没有可执行课程")
                    )
                    stage_name = {
                        0: "学前辅导",
                        1: "初级学园",
                        2: "中级学园",
                        3: "高级学园",
                        4: "进修学院",
                    }.get(stage, f"阶段 {stage}")
                    self.course_stage_label.configure(
                        text=f"服务器当前阶段：{stage_name}；共 {len(courses)} 门课程"
                    )
                    self.course_refresh_button.configure(state=tk.NORMAL)
                elif kind == "school_courses_error":
                    self.course_stage_label.configure(text=f"课程读取失败：{payload}")
                    self.course_refresh_button.configure(state=tk.NORMAL)
                elif kind == "work_jobs":
                    catalog = payload
                    overview, jobs = catalog.overview, catalog.jobs
                    config = self.config_store.data
                    previous = int(config["work"].get("job_sub_event", 0))
                    automatic = "自动选择开放职业中最短时长岗位"
                    options = {automatic: (0, 0)}
                    selected_label = automatic
                    for job in jobs:
                        if not job.can_do:
                            continue
                        label = (
                            f"{job.career_name}｜{job.name}｜"
                            f"{job.duration}｜收益 {job.reward}"
                        )
                        options[label] = (job.career_type, job.sub_event_type)
                        if job.sub_event_type == previous:
                            selected_label = label
                    self.job_options = options
                    self.job_combo.configure(values=tuple(options))
                    self.job_var.set(selected_label)
                    test_options = {
                        label: target
                        for label, target in options.items()
                        if target != (0, 0)
                    }
                    self.test_job_combo.configure(values=tuple(test_options))
                    self.test_job_var.set(
                        next(iter(test_options), "当前没有可执行岗位")
                    )
                    readable_careers = {
                        career.career_type
                        for career in overview.careers
                        if career.available
                    } | {job.career_type for job in jobs}
                    open_count = len(readable_careers)
                    rejected_count = len(catalog.rejected_careers)
                    rejected_text = (
                        f"；{rejected_count} 个职业尚未满足参与要求，已跳过"
                        if rejected_count
                        else ""
                    )
                    self.job_status_label.configure(
                        text=(
                            f"服务器可读取 {open_count} 个职业；读取到 {len(test_options)} 个可执行岗位"
                            f"{rejected_text}"
                        )
                    )
                    self.job_refresh_button.configure(state=tk.NORMAL)
                elif kind == "work_jobs_error":
                    self.job_status_label.configure(text=f"岗位读取失败：{payload}")
                    self.job_refresh_button.configure(state=tk.NORMAL)
                elif kind == "adventure_options":
                    previous = str(
                        self.config_store.data["adventure"].get("option_name", "")
                    )
                    automatic = "自动选择服务器当前可用冒险"
                    options = {automatic: ""}
                    selected_label = automatic
                    available_count = 0
                    for option in payload:
                        status = "可执行" if option.can_do else "暂不可用"
                        label = (
                            f"{option.name}｜{option.duration}｜"
                            f"{option.cost}｜{status}"
                        )
                        options[label] = option.name
                        if option.can_do:
                            available_count += 1
                        if option.name == previous:
                            selected_label = label
                    self.adventure_options = options
                    self.adventure_combo.configure(values=tuple(options))
                    self.adventure_var.set(selected_label)
                    test_options = {
                        label: name
                        for label, name in options.items()
                        if name and "｜可执行" in label
                    }
                    self.test_adventure_combo.configure(values=tuple(test_options))
                    self.test_adventure_var.set(
                        next(iter(test_options), "当前天气没有可执行冒险")
                    )
                    self.adventure_status_label.configure(
                        text=f"服务器返回 {len(payload)} 项；当前可执行 {available_count} 项"
                    )
                    self.adventure_refresh_button.configure(state=tk.NORMAL)
                elif kind == "adventure_options_error":
                    self.adventure_status_label.configure(text=f"冒险读取失败：{payload}")
                    self.adventure_refresh_button.configure(state=tk.NORMAL)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / f"{datetime.now():%Y-%m-%d}.log").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def _close(self) -> None:
        self._stop()
        self.destroy()


def run_console() -> None:
    """启动完整控制台 GUI。

    macOS 打包版（或显式传 --menubar）默认后台运行：菜单栏图标 + 自动开始调度 +
    主窗口隐藏；关闭主窗口返回后台。其它平台/源码运行保持原行为（显示窗口、手动启动）。
    """
    instance = SingleInstance(ROOT / "runs" / ".console.lock")
    if not instance.acquire():
        popup = tk.Tk()
        popup.withdraw()
        messagebox.showinfo("QQ 宠物助手", "控制台已经在运行，无需重复启动。")
        popup.destroy()
        raise SystemExit(0)
    try:
        use_menubar = sys.platform == "darwin" and (
            getattr(sys, "frozen", False) or "--menubar" in sys.argv
        )
        auto_start = use_menubar or "--autostart" in sys.argv[1:]
        win = MainWindow(auto_start=auto_start)
        if use_menubar:
            from menubar_integration import attach_menubar

            globals()["_menubar_controller"] = attach_menubar(win)
            win.withdraw()  # 默认后台（不显示主窗口）
        win.mainloop()
    finally:
        instance.release()


if __name__ == "__main__":
    run_console()
