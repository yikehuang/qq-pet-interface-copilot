from __future__ import annotations

import queue
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from qqpet_app import __version__
from qqpet_app.bootstrap import ensure_vc_runtime
from qqpet_app.config import ConfigStore
from qqpet_app.mobile_protocol import reader_from_config
from qqpet_app.scheduler import Scheduler
from qqpet_app.updater import (
    UpdateInfo,
    download_update,
    extract_executable,
    fetch_latest,
    is_newer,
    schedule_windows_install,
)


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
def console_process_spec(frozen: bool | None = None) -> tuple[list[str], dict[str, str]]:
    """Return an independent console command and environment for this build."""
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    command = [sys.executable, str(ROOT / "main.py")]
    child_env = os.environ.copy()
    if is_frozen:
        command = [sys.executable, "--console"]
        # A one-file PyInstaller child must unpack independently. Otherwise it
        # inherits the launcher's temporary _MEI directory, which is deleted
        # when this window exits.
        child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return command, child_env


def _configured_identity(store: ConfigStore) -> tuple[str, str]:
    config = store.data
    uin = str(config["account"].get("uin") or "")
    pet_id = str(config["account"].get("pet_id") or "")
    if uin == "YOUR_QQ_UIN":
        uin = ""
    if pet_id == "YOUR_PET_ID":
        pet_id = ""
    return uin, pet_id


def save_manual_connection(store: ConfigStore, adb_path: str, adb_serial: str) -> None:
    """Persist launcher connection overrides; blank values keep auto discovery."""
    path_text = os.path.expandvars(adb_path.strip().strip('"'))
    if path_text and not Path(path_text).is_file():
        raise ValueError("手动指定的 ADB 程序不存在，请选择模拟器目录中的 adb")
    serial = adb_serial.strip()
    if serial and not (
        serial.startswith("emulator-")
        or (":" in serial and serial.rsplit(":", 1)[1].isdigit())
    ):
        raise ValueError("模拟器连接地址格式不正确，例如：127.0.0.1:16384")
    config = store.data
    config["mobile_protocol"]["adb_path"] = path_text
    config["mobile_protocol"]["adb_serial"] = serial
    store.save(config)


class Launcher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("QQ 宠物助手 · 一键启动")
        self.geometry("720x590")
        self.minsize(640, 540)
        self.store = ConfigStore(CONFIG_PATH)
        mobile = self.store.data["mobile_protocol"]
        self.adb_path_var = tk.StringVar(value=str(mobile.get("adb_path") or ""))
        self.adb_serial_var = tk.StringVar(value=str(mobile.get("adb_serial") or ""))
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
            text="连接电脑中的安卓模拟器和手机 QQ，成功后直接打开控制台。",
            foreground="#666",
        ).pack(anchor="w", pady=(6, 18))
        self.state_var = tk.StringVar(value="准备检查……")
        ttk.Label(body, textvariable=self.state_var, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(10, 14))

        connection = ttk.LabelFrame(body, text="模拟器连接（留空自动识别）", padding=10)
        connection.pack(fill=tk.X, pady=(0, 12))
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="ADB 程序").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(connection, textvariable=self.adb_path_var).grid(
            row=0, column=1, sticky="ew", pady=3
        )
        ttk.Button(connection, text="选择…", command=self._browse_adb).grid(
            row=0, column=2, padx=(8, 0), pady=3
        )
        ttk.Label(connection, text="连接地址").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(connection, textvariable=self.adb_serial_var).grid(
            row=1, column=1, sticky="ew", pady=3
        )
        ttk.Button(connection, text="恢复自动", command=self._clear_manual_connection).grid(
            row=1, column=2, padx=(8, 0), pady=3
        )
        ttk.Label(
            connection,
            text=(
                "示例：ADB 程序选择 …\\MuMu Player 12\\nx_main\\adb.exe；连接地址填写 127.0.0.1:16384"
                if sys.platform == "win32"
                else "macOS：ADB 程序留空自动识别 MuMu 模拟器 Pro；连接地址填写 127.0.0.1:5555"
            ),
            foreground="#666",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))

        self.log = tk.Text(body, height=11, state=tk.DISABLED, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True)
        actions = ttk.Frame(body)
        actions.pack(fill=tk.X, pady=(14, 0))
        self.connect_button = ttk.Button(actions, text="一键安装并打开", command=self.connect)
        self.connect_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.install_button = ttk.Button(actions, text="检查手机协议环境", command=self.install_mobile_runtime)
        self.install_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        self.update_button = ttk.Button(
            body,
            text=f"检查更新（当前 v{__version__}）",
            command=self.check_update,
        )
        self.update_button.pack(fill=tk.X, pady=(10, 0))

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

    def _browse_adb(self) -> None:
        if sys.platform == "win32":
            filetypes = (("ADB 程序", "adb.exe"), ("可执行程序", "*.exe"))
            title = "选择 MuMu 的 adb.exe"
        else:
            filetypes = (("ADB 程序", "adb"), ("所有文件", "*"))
            title = "选择 adb"
        selected = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if selected:
            self.adb_path_var.set(selected)

    def _clear_manual_connection(self) -> None:
        self.adb_path_var.set("")
        self.adb_serial_var.set("")

    def _save_connection_fields(self) -> bool:
        try:
            save_manual_connection(
                self.store, self.adb_path_var.get(), self.adb_serial_var.get()
            )
            return True
        except ValueError as exc:
            self.state_var.set("连接设置有误")
            messagebox.showerror("无法保存连接设置", str(exc))
            return False

    def connect(self) -> None:
        if not self._save_connection_fields():
            return
        self._run(self._connect_worker)

    def install_mobile_runtime(self) -> None:
        if not self._save_connection_fields():
            return
        self._run(self._install_worker)

    def check_update(self) -> None:
        if self.running:
            return
        self.update_button.configure(state=tk.DISABLED, text="正在检查更新……")

        def worker() -> None:
            try:
                self.events.put(("update_checked", fetch_latest()))
            except Exception as exc:
                self.events.put(("update_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _download_update(self, info: UpdateInfo) -> None:
        self.update_button.configure(state=tk.DISABLED, text=f"正在下载 {info.tag}……")

        def progress(received: int, total: int) -> None:
            percent = min(100, int(received * 100 / max(1, total)))
            self.events.put(("update_progress", (info.tag, percent)))

        def worker() -> None:
            try:
                update_root = DOWNLOAD_DIR.parent / "updates"
                archive = download_update(info, update_root, progress)
                executable = extract_executable(archive, update_root / info.tag)
                self.events.put(("update_ready", (info, executable)))
            except Exception as exc:
                self.events.put(("update_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _connect_worker(self) -> None:
        try:
            preferred_uin, pet_id = _configured_identity(self.store)
            self.events.put(("log", "正在检查软件必备运行环境……"))
            ensure_vc_runtime(
                DOWNLOAD_DIR, lambda message: self.events.put(("log", message))
            )
            self.events.put(("log", "正在连接安卓模拟器中的手机 QQ 协议……"))
            config = self.store.data
            config["mobile_protocol"]["enabled"] = True
            reader = reader_from_config(config)
            if reader is None:
                raise RuntimeError("手机协议未启用")
            serial = reader.prepare_runtime(
                DOWNLOAD_DIR, lambda message: self.events.put(("log", message))
            )
            config["mobile_protocol"]["adb_path"] = str(reader.adb_path or "")
            config["mobile_protocol"]["adb_serial"] = serial
            client = Scheduler._make_client(config)
            logged_in_uin = client.check_connection()
            self.events.put(("log", f"已连接模拟器手机 QQ {logged_in_uin}。"))
            if not pet_id or preferred_uin != logged_in_uin:
                self.events.put(("log", "正在从 QQ 宠物服务器一键读取宠物 ID……"))
                profile = client.query_own_pet_profile(logged_in_uin)
                pet_id = profile.pet_id
                client.pet_id = pet_id
                pet_label = f"“{profile.pet_name}”" if profile.pet_name else ""
                self.events.put(("log", f"已读取宠物{pet_label}，宠物 ID 已自动保存。"))
            config["account"]["uin"] = logged_in_uin
            config["account"]["pet_id"] = pet_id
            self.store.save(config)
            values = client.query_values()
            self.events.put(("log", f"手机协议验证成功，当前金币 {values.gold:.0f}。"))
            self.events.put(("launch", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _install_worker(self) -> None:
        try:
            ensure_vc_runtime(
                DOWNLOAD_DIR, lambda message: self.events.put(("log", message))
            )
            config = self.store.data
            config["mobile_protocol"]["enabled"] = True
            reader = reader_from_config(config)
            if reader is None:
                raise RuntimeError("手机协议未启用")
            serial = reader.prepare_runtime(
                DOWNLOAD_DIR, lambda message: self.events.put(("log", message))
            )
            config["mobile_protocol"]["adb_path"] = str(reader.adb_path or "")
            config["mobile_protocol"]["adb_serial"] = serial
            self.store.save(config)
            self.events.put(("log", "基础运行环境和 MuMu 手机协议均已准备完成。"))
            self.events.put(("retry", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))

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
                elif kind == "launch":
                    self.state_var.set("连接成功，正在打开控制台……")
                    self.progress.stop()
                    command, child_env = console_process_spec()
                    subprocess.Popen(command, cwd=ROOT, env=child_env)
                    self.after(300, self.destroy)
                elif kind == "retry":
                    self._finish_busy()
                    self.after(500, self.connect)
                elif kind == "error":
                    self._finish_busy()
                    self.state_var.set("需要处理")
                    self._append(f"失败：{payload}")
                    messagebox.showerror("一键启动未完成", str(payload))
                elif kind == "update_checked":
                    info = payload
                    self.update_button.configure(
                        state=tk.NORMAL, text=f"检查更新（当前 v{__version__}）"
                    )
                    if not is_newer(info.version, __version__):
                        messagebox.showinfo(
                            "已经是最新版",
                            f"当前版本 v{__version__}，GitHub 最新正式版 {info.tag}。",
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
                        messagebox.showinfo(
                            "新版已下载",
                            f"源码运行模式不会自动覆盖文件。新版已保存到：\n{executable}",
                        )
                    elif messagebox.askyesno(
                        "安装更新",
                        f"{info.tag} 已下载并通过 SHA-256 校验。\n\n"
                        "现在退出助手、安装并自动重新打开吗？",
                    ):
                        schedule_windows_install(executable)
                        self.destroy()
                elif kind == "update_error":
                    self.update_button.configure(
                        state=tk.NORMAL, text=f"检查更新（当前 v{__version__}）"
                    )
                    messagebox.showerror("更新失败", str(payload))
        except queue.Empty:
            pass
        self.after(100, self._drain)


if __name__ == "__main__":
    if "--console" in sys.argv:
        from main import MainWindow

        MainWindow().mainloop()
    else:
        Launcher().mainloop()
