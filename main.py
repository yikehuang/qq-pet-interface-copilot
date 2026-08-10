from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from qqpet_app.client import NapCatClient, PKOpponent
from qqpet_app.config import ConfigStore
from qqpet_app.friend_visits import FriendVisitProgress, eligible_friends
from qqpet_app.friend_pet_cache import load_latest_friend_pet_capture
from qqpet_app.notifications import NotificationManager
from qqpet_app.scheduler import Scheduler
from qqpet_app.single_instance import SingleInstance


ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
CONFIG_PATH = ROOT / "config.yaml"
PROGRESS_PATH = ROOT / "runs" / "daily_progress.json"
LOG_DIR = ROOT / "runs" / "logs"
FRIEND_VISIT_DIR = ROOT / "runs"


SETTING_FIELDS = [
    ("napcat.url", "本机接口地址", str),
    ("napcat.token", "本机接口令牌", str),
    ("napcat.timeout_seconds", "接口请求超时（秒）", float),
    ("napcat.auto_reconnect", "接口断开后自动重连", bool),
    ("napcat.reconnect_initial_seconds", "自动重连初始间隔（秒）", float),
    ("napcat.reconnect_max_seconds", "自动重连最大间隔（秒）", float),
    ("account.uin", "QQ 号", str),
    ("account.pet_id", "宠物 ID", str),
    ("scheduler.interval_seconds", "轮询间隔（秒）", int),
    ("scheduler.coin_threshold", "学习金币阈值", float),
    ("school.enabled", "启用学习", bool),
    ("school.attribute", "学习属性 culture/physical/art", str),
    ("work.enabled", "启用打工", bool),
    ("work.times_per_day", "每日打工上限（0 不限）", int),
    ("work.employ_friend", "有可用好友时优先雇佣", bool),
    ("adventure.enabled", "启用冒险", bool),
    ("adventure.start_time", "冒险开始时间 HH:MM", str),
    ("adventure.times_per_day", "每日冒险上限", int),
    ("pk.enabled", "启用自动 PK", bool),
    ("pk.start_time", "自动 PK 开始时间 HH:MM", str),
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
    ("friend_care.check_interval_seconds", "好友照顾检查间隔（秒）", float),
    ("friend_care.hunger_threshold", "好友体力喂食阈值", float),
    ("friend_care.verify_delay_seconds", "好友喂食后验证等待（秒）", float),
    ("friend_care.failure_cooldown_seconds", "好友照顾失败冷却（秒）", float),
    ("care.enabled", "启用状态照顾", bool),
    ("care.hunger_threshold", "体力喂食阈值", float),
    ("care.clean_threshold", "清洁洗澡阈值", float),
    ("care.auto_buy_supplies", "道具不足时自动用金币购买", bool),
    ("care.food_purchase_count", "每次购买饼干数量", int),
    ("care.soap_purchase_count", "每次购买香皂片数量", int),
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
    "story.employed_recall_mode": {
        "等到 25/75（收益分成最高）": "best_split",
        "立刻召回": "immediate",
    },
}

SETTING_SECTIONS = (
    ("connection", "连接与账号", ("napcat.", "account.")),
    ("scheduler", "自动调度", ("scheduler.",)),
    ("care", "自己的宠物照顾", ("care.",)),
    ("school", "学习", ("school.",)),
    ("work", "打工", ("work.",)),
    ("adventure", "冒险", ("adventure.",)),
    ("pk", "自动 PK", ("pk.",)),
    ("friend_visits", "好友访问与踩踩", ("friend_visits.",)),
    ("friend_care", "好友自动照顾", ("friend_care.",)),
    ("story", "被雇佣召回", ("story.",)),
    ("notifications", "外部通知", ("notifications.",)),
    ("safety", "安全与真实操作", ("safety.",)),
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
        self.course_var = tk.StringVar(value="自动选择当前属性最高收益")
        self.course_options: dict[str, int] = {"自动选择当前属性最高收益": 0}
        self.job_var = tk.StringVar(value="自动选择开放职业中总收益最高岗位")
        self.job_options: dict[str, tuple[int, int]] = {
            "自动选择开放职业中总收益最高岗位": (0, 0)
        }
        self.adventure_var = tk.StringVar(value="自动选择服务器当前可用冒险")
        self.adventure_options: dict[str, str] = {
            "自动选择服务器当前可用冒险": ""
        }
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
            adventure_section, text="将从服务器读取真实冒险目录", foreground="#666"
        )
        self.adventure_status_label.grid(
            row=adventure_row + 1, column=1, sticky="w", padx=6, pady=(0, 5)
        )
        ttk.Button(form, text="保存全部设置并立即生效", command=self._save_settings).pack(
            fill=tk.X, padx=6, pady=(10, 18)
        )

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
            text="只监控名单中的好友；体力低于阈值才喂食，并重新读取好友体力验证。",
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
            f"{state}；监控 {len(targets)} 位好友；低于 {float(care['hunger_threshold']):g} 自动喂食；"
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
                client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    config["account"]["pet_id"],
                    float(config["napcat"]["timeout_seconds"]),
                )
                fallback = self.manual_pk_cached_opponents.get(uin)
                opponent = client.resolve_pk_opponent(
                    uin, fallback or self._configured_pk_opponent(config)
                )
                friend_values_client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    opponent.pet_id,
                    float(config["napcat"]["timeout_seconds"]),
                )
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
            self.course_var.set("自动选择当前属性最高收益")
        career_type = int(config["work"].get("career_type", 0))
        job_sub_event = int(config["work"].get("job_sub_event", 0))
        if job_sub_event:
            label = f"已保存岗位编号 {job_sub_event}（刷新后显示名称）"
            self.job_options[label] = (career_type, job_sub_event)
            self.job_combo.configure(values=tuple(self.job_options))
            self.job_var.set(label)
        else:
            self.job_var.set("自动选择开放职业中总收益最高岗位")
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
                client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    config["account"]["pet_id"],
                    float(config["napcat"]["timeout_seconds"]),
                )
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
                url = str(self.setting_vars["napcat.url"][0].get()).strip()
                token = str(self.setting_vars["napcat.token"][0].get()).strip()
                timeout = float(self.setting_vars["napcat.timeout_seconds"][0].get())
                expected_uin = str(self.setting_vars["account.uin"][0].get()).strip()
                client = NapCatClient(url, token, "", timeout)
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
                client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    config["account"]["pet_id"],
                    float(config["napcat"]["timeout_seconds"]),
                )
                overview = client.query_work_overview()
                jobs = tuple(
                    job
                    for career in overview.careers
                    if career.available
                    for job in client.query_work_jobs(career.career_type)
                )
                self.events.put(("work_jobs", (overview, jobs)))
            except Exception as exc:
                self.events.put(("work_jobs_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_adventure_options(self) -> None:
        self.adventure_refresh_button.configure(state=tk.DISABLED)
        self.adventure_status_label.configure(text="正在读取服务器冒险目录…")

        def worker() -> None:
            try:
                config = self.config_store.data
                client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    config["account"]["pet_id"],
                    float(config["napcat"]["timeout_seconds"]),
                )
                options = client.query_adventure_options()
                self.events.put(("adventure_options", options))
            except Exception as exc:
                self.events.put(("adventure_options_error", str(exc)))

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
            config["work"]["strategy"] = "highest_total"
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

    def _check_once(self) -> None:
        def worker() -> None:
            scheduler = self._new_scheduler()
            try:
                scheduler.run_once()
            except Exception as exc:
                self.events.put(("log", f"[{datetime.now():%H:%M:%S}] 检查失败：{exc}"))
                self.events.put(("connection", "连接失败"))
                self.events.put(("notice", ("连接失败", str(exc), "error")))

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
                client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    config["account"]["pet_id"],
                    float(config["napcat"]["timeout_seconds"]),
                )
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
                client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    config["account"]["pet_id"],
                    float(config["napcat"]["timeout_seconds"]),
                )
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
                client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    config["account"]["pet_id"],
                    float(config["napcat"]["timeout_seconds"]),
                )
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
                client = NapCatClient(
                    config["napcat"]["url"],
                    config["napcat"]["token"],
                    config["account"]["pet_id"],
                    float(config["napcat"]["timeout_seconds"]),
                )
                friends = client.query_friend_list()
                visit_config = config["friend_visits"]
                candidates = eligible_friends(
                    friends,
                    str(config["account"]["uin"]),
                    str(visit_config.get("whitelist", "")),
                    str(visit_config.get("exclude", "")),
                )
                verified_pets = {
                    opponent.user_id: opponent
                    for opponent in load_latest_friend_pet_capture(FRIEND_VISIT_DIR)
                }
                candidates = tuple(
                    friend
                    for friend in candidates
                    if str(friend.user_id) in verified_pets
                )
                limit = int(visit_config.get("max_per_day", 0))
                if limit > 0:
                    candidates = candidates[:limit]
                protocol_state = "no_candidates"
                protocol_detail = "没有可用于协议检测的宠物好友"
                if candidates:
                    probe = verified_pets[str(candidates[0].user_id)]
                    try:
                        rules = client.query_friend_visit_rules(probe.pet_id)
                        if rules.allows(client.FRIEND_VISIT_PATH):
                            protocol_state = "rules_available"
                            protocol_detail = "服务器已下发真实好友访问路径"
                        elif rules.declared_count == 0:
                            protocol_state = "windows_unsupported"
                            protocol_detail = (
                                "Windows/NapCat 会话返回好友页面规则 count=0"
                            )
                        else:
                            protocol_state = "path_missing"
                            protocol_detail = "服务器响应中没有访问路径 1000/100/101"
                    except Exception as exc:
                        protocol_state = "probe_failed"
                        protocol_detail = f"好友协议检测失败：{exc}"
                progress = FriendVisitProgress(FRIEND_VISIT_DIR)
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
                if kind.endswith("_error") and kind != "manual_pk_batch_error":
                    self._show_notice("操作失败", str(payload), "error")
                if kind == "log":
                    self._append_log(payload)
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
                            f"今日喂食 {care_summary.get('feeds', 0)}"
                        )
                elif kind == "connection":
                    connection_text = str(payload)
                    self.status_vars["connection"].set(connection_text)
                    is_connected = connection_text == "已连接"
                    self.hero_connection_label.configure(
                        background="#e1f7ee" if is_connected else "#fff0d7",
                        foreground="#187d53" if is_connected else "#9b6109",
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
                    if protocol_state == "rules_available":
                        message += (
                            "真实协议已识别，但访问记录/奖励的二次验证尚未通过，"
                            "本轮未计为成功"
                        )
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
                        f"当前体力 {values.hunger:.1f}/100，自动照顾已启用"
                    )
                    self._append_log(
                        f"[{datetime.now():%H:%M:%S}] 已加入自动照顾名单："
                        f"{target['name']}（QQ {target['uin']}），"
                        f"petId={target['pet_id']}，当前体力 {values.hunger:.1f}"
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
                    options = {"自动选择当前属性最高收益": 0}
                    selected_label = "自动选择当前属性最高收益"
                    for course in courses:
                        label = f"{course.name}｜{course.duration}｜{course.reward}"
                        options[label] = course.sub_event_type
                        if course.sub_event_type == previous:
                            selected_label = label
                    self.course_options = options
                    self.course_combo.configure(values=tuple(options))
                    self.course_var.set(selected_label)
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
                    overview, jobs = payload
                    config = self.config_store.data
                    previous = int(config["work"].get("job_sub_event", 0))
                    automatic = "自动选择开放职业中总收益最高岗位"
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
                    open_count = sum(1 for career in overview.careers if career.available)
                    self.job_status_label.configure(
                        text=f"服务器开放 {open_count} 个职业；共 {len(jobs)} 个岗位"
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


if __name__ == "__main__":
    instance = SingleInstance(ROOT / "runs" / ".console.lock")
    if not instance.acquire():
        popup = tk.Tk()
        popup.withdraw()
        messagebox.showinfo("QQ 宠物助手", "控制台已经在运行，无需重复启动。")
        popup.destroy()
        raise SystemExit(0)
    try:
        MainWindow(auto_start="--autostart" in sys.argv[1:]).mainloop()
    finally:
        instance.release()
