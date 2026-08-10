from __future__ import annotations

import queue
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from qqpet_app.bootstrap import (
    active_sessions,
    dependency_state,
    ensure_napcat_runtime,
    login_qrcode_path,
    start_napcat,
    wait_for_session,
)
from qqpet_app.client import NapCatClient
from qqpet_app.config import ConfigStore


ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
CONFIG_PATH = ROOT / "config.yaml"
DOWNLOAD_DIR = (
    Path(os.environ.get("LOCALAPPDATA") or ROOT)
    / "QQPetInterfaceCopilot"
    / "downloads"
)
NAPCAT_STARTUP_LOG = (
    Path(os.environ.get("LOCALAPPDATA") or ROOT)
    / "QQPetInterfaceCopilot"
    / "logs"
    / "napcat-startup.log"
)


def _configured_identity(store: ConfigStore) -> tuple[str, str, str, str]:
    config = store.data
    url = str(config["napcat"].get("url") or "")
    token = str(config["napcat"].get("token") or "")
    uin = str(config["account"].get("uin") or "")
    pet_id = str(config["account"].get("pet_id") or "")
    if token == "CHANGE_ME_LOCAL_TOKEN":
        token = ""
    if uin == "YOUR_QQ_UIN":
        uin = ""
    if pet_id == "YOUR_PET_ID":
        pet_id = ""
    return url, token, uin, pet_id


class Launcher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("QQ 宠物助手 · 一键启动")
        self.geometry("620x460")
        self.minsize(560, 420)
        self.store = ConfigStore(CONFIG_PATH)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self._build()
        self.after(100, self._drain)
        self.after(350, self.connect)

    def _build(self) -> None:
        body = ttk.Frame(self, padding=24)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="QQ 宠物助手", font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text="自动安装 NapCat 完整环境、连接 QQ 会话，成功后直接打开控制台。",
            foreground="#666",
        ).pack(anchor="w", pady=(6, 18))
        self.state_var = tk.StringVar(value="准备检查……")
        ttk.Label(body, textvariable=self.state_var, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(10, 14))
        self.log = tk.Text(body, height=11, state=tk.DISABLED, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True)
        actions = ttk.Frame(body)
        actions.pack(fill=tk.X, pady=(14, 0))
        self.connect_button = ttk.Button(actions, text="一键安装并打开", command=self.connect)
        self.connect_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.install_button = ttk.Button(actions, text="修复运行环境", command=self.install_napcat)
        self.install_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

    def _append(self, message: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _run(self, target) -> None:
        if self.running:
            return
        self.running = True
        self.progress.start(12)
        self.connect_button.configure(state=tk.DISABLED)
        self.install_button.configure(state=tk.DISABLED)
        threading.Thread(target=target, daemon=True).start()

    def connect(self) -> None:
        self._run(self._connect_worker)

    def install_napcat(self) -> None:
        self._run(self._install_worker)

    def _connect_worker(self) -> None:
        try:
            url, token, preferred_uin, pet_id = _configured_identity(self.store)
            self.events.put(("log", "正在检查电脑版 QQ、NapCat 和本机接口……"))
            state = dependency_state(url, token)
            if not state.napcat_root:
                self.events.put(("log", "未发现 NapCat，开始自动安装全部运行组件。"))
                ensure_napcat_runtime(
                    DOWNLOAD_DIR, lambda message: self.events.put(("log", message))
                )
                self.events.put(
                    (
                        "log",
                        "当前使用 NapCat；SnowLuma 是并列的另一套框架，本助手无需重复安装。",
                    )
                )
                state = dependency_state(url, token)
                if not state.napcat_root:
                    raise RuntimeError("NapCat 安装后未通过完整性检查")
            if state.sessions:
                session = next(
                    (item for item in state.sessions if item.uin == preferred_uin),
                    state.sessions[0],
                )
            else:
                self.events.put(("log", "NapCat 尚未在线，正在启动登录；如出现二维码请扫码确认。"))
                login_started = time.time()
                napcat_process = start_napcat(
                    preferred_uin, state.qq_path, NAPCAT_STARTUP_LOG
                )
                qr_shown = False

                def show_qr_when_ready() -> None:
                    nonlocal qr_shown
                    if qr_shown:
                        return
                    return_code = napcat_process.poll()
                    if return_code not in (None, 0):
                        detail = ""
                        try:
                            lines = NAPCAT_STARTUP_LOG.read_text(
                                encoding="utf-8", errors="replace"
                            ).splitlines()
                            detail = "\n".join(lines[-8:]).strip()
                        except OSError:
                            pass
                        message = f"NapCat 启动失败（退出码 {return_code}）"
                        if detail:
                            message += f"：\n{detail}"
                        message += "\n请检查杀毒软件、QQ 版本和 VC++ x64 运行库。"
                        raise RuntimeError(message)
                    qr_path = login_qrcode_path()
                    if qr_path and qr_path.stat().st_mtime >= login_started - 2:
                        qr_shown = True
                        self.events.put(("show_qr", qr_path))

                session = wait_for_session(
                    url,
                    token,
                    preferred_uin,
                    timeout=180,
                    on_wait=show_qr_when_ready,
                )
                if session is None:
                    raise RuntimeError("等待 QQ/NapCat 登录超时，请完成登录后再点一次")
            self.events.put(("log", f"已连接 QQ {session.uin}（令牌仅保存在本机）。"))
            client = NapCatClient(session.endpoint.url, session.endpoint.token, pet_id, timeout=8)
            if not pet_id or preferred_uin != session.uin:
                self.events.put(("log", "正在从 QQ 宠物服务器一键读取宠物 ID……"))
                profile = client.query_own_pet_profile(session.uin)
                pet_id = profile.pet_id
                client.pet_id = pet_id
                pet_label = f"“{profile.pet_name}”" if profile.pet_name else ""
                self.events.put(("log", f"已读取宠物{pet_label}，宠物 ID 已自动保存。"))
            values = client.query_values()
            config = self.store.data
            config["napcat"]["url"] = session.endpoint.url
            config["napcat"]["token"] = session.endpoint.token
            config["account"]["uin"] = session.uin
            config["account"]["pet_id"] = pet_id
            self.store.save(config)
            self.events.put(("log", f"宠物接口验证成功，当前金币 {values.gold:.0f}。"))
            self.events.put(("launch", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _install_worker(self) -> None:
        try:
            ensure_napcat_runtime(
                DOWNLOAD_DIR, lambda message: self.events.put(("log", message))
            )
            self.events.put(("log", "运行环境检查完成，正在连接并打开助手……"))
            self.events.put(("retry", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _save_pet_id(self, session, pet_id: str) -> None:
        pet_id = pet_id.strip()
        if not pet_id:
            self.events.put(("error", "宠物 ID 不能为空"))
            return
        config = self.store.data
        config["napcat"]["url"] = session.endpoint.url
        config["napcat"]["token"] = session.endpoint.token
        config["account"]["uin"] = session.uin
        config["account"]["pet_id"] = pet_id
        self.store.save(config)
        self.running = False
        self.connect()

    def _finish_busy(self) -> None:
        self.running = False
        self.progress.stop()
        self.connect_button.configure(state=tk.NORMAL)
        self.install_button.configure(state=tk.NORMAL)

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.state_var.set(str(payload))
                    self._append(str(payload))
                elif kind == "need_pet_id":
                    self._finish_busy()
                    value = simpledialog.askstring(
                        "首次设置",
                        "已经取得 QQ 会话。请输入一次宠物 ID；验证成功后以后无需再填写：",
                        parent=self,
                    )
                    if value:
                        self._save_pet_id(payload, value)
                elif kind == "show_qr":
                    self.state_var.set("请使用手机 QQ 扫描登录二维码")
                    self._append(f"登录二维码已生成：{payload}")
                    try:
                        image = tk.PhotoImage(file=str(payload))
                        window = tk.Toplevel(self)
                        window.title("扫码登录 QQ")
                        window.resizable(False, False)
                        ttk.Label(
                            window,
                            text="请使用手机 QQ 扫描二维码并确认登录",
                            font=("Microsoft YaHei UI", 11, "bold"),
                        ).pack(padx=20, pady=(18, 10))
                        label = ttk.Label(window, image=image)
                        label.image = image
                        label.pack(padx=20, pady=(0, 18))
                        window.transient(self)
                        window.lift()
                        window.focus_force()
                    except (OSError, tk.TclError) as exc:
                        self._append(f"二维码显示失败，将继续等待并允许重试：{exc}")
                        messagebox.showerror(
                            "二维码显示失败",
                            f"二维码文件已经生成，但无法显示：{exc}\n\n文件位置：{payload}",
                            parent=self,
                        )
                elif kind == "launch":
                    self.state_var.set("连接成功，正在打开控制台……")
                    self.progress.stop()
                    command = [sys.executable, str(ROOT / "main.py")]
                    if getattr(sys, "frozen", False):
                        command = [sys.executable, "--console"]
                    subprocess.Popen(command, cwd=ROOT)
                    self.after(300, self.destroy)
                elif kind == "retry":
                    self._finish_busy()
                    self.after(500, self.connect)
                elif kind == "error":
                    self._finish_busy()
                    self.state_var.set("需要处理")
                    self._append(f"失败：{payload}")
                    messagebox.showerror("一键启动未完成", str(payload))
        except queue.Empty:
            pass
        self.after(100, self._drain)


if __name__ == "__main__":
    if "--console" in sys.argv:
        from main import MainWindow

        MainWindow().mainloop()
    else:
        Launcher().mainloop()
