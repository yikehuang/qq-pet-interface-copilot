#!/usr/bin/env python3
"""给 main.py 的 MainWindow 附加 macOS 菜单栏（NSStatusItem）。

单进程方案：菜单栏图标 + 主窗口 + 调度器都在同一进程里，天然同步、无竞态。

- 关闭主窗口 = 隐藏（withdraw），调度继续在后台跑；
- 菜单栏「主页面」= 重新显示主窗口；
- 菜单栏「退出」= 停止调度并真正退出。
"""
from __future__ import annotations

import objc
from AppKit import (
    NSApplication,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject


def attach_menubar(win, hide_on_close: bool = True) -> NSObject:
    """把菜单栏附加到 MainWindow（tkinter 窗口）。返回 controller 对象（需保持引用）。

    必须在 tkinter 窗口创建之后调用。内部顺序很关键（实测）：
    先 tk.Tk() → 再 setActivationPolicy(accessory) 隐藏 Dock → 再建 NSStatusItem；
    若在 tk.Tk() 之前就设 accessory，Tk 初始化会崩（NSApplication macOSVersion 找不到）。
    """
    # 1) 隐藏 Dock（accessory）。必须在 tkinter 窗口已创建的前提下调用。
    NSApplication.sharedApplication().setActivationPolicy_(1)

    class MenubarController(NSObject):
        def init(self):
            self = objc.super(MenubarController, self).init()
            if self is None:
                return None
            self.win = win
            self._build_status_item()
            return self

        def _build_status_item(self) -> None:
            self._status = NSStatusBar.systemStatusBar().statusItemWithLength_(
                NSVariableStatusItemLength
            )
            self._status.button().setTitle_("🐾 启动中")

            menu = NSMenu.alloc().init()
            menu.setTitle_("QQ宠物助手")

            self._detail_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "正在连接…", None, ""
            )
            self._detail_item.setEnabled_(False)
            menu.addItem_(self._detail_item)
            menu.addItem_(NSMenuItem.separatorItem())

            self._toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "停止托管", "toggleSchedule:", ""
            )
            self._toggle_item.setTarget_(self)
            menu.addItem_(self._toggle_item)

            show_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "主页面", "showWindow:", ""
            )
            show_item.setTarget_(self)
            menu.addItem_(show_item)

            menu.addItem_(NSMenuItem.separatorItem())
            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "退出", "quitApp:", "q"
            )
            quit_item.setTarget_(self)
            menu.addItem_(quit_item)

            self._status.setMenu_(menu)

        def showWindow_(self, _sender) -> None:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()

        def toggleSchedule_(self, _sender) -> None:
            try:
                running = bool(
                    self.win.scheduler_thread
                    and self.win.scheduler_thread.is_alive()
                )
                if running:
                    self.win._stop()
                else:
                    self.win._start()
            except Exception:  # noqa: BLE001
                pass

        def quitApp_(self, _sender) -> None:
            try:
                self.win._stop()  # 停止调度
            except Exception:  # noqa: BLE001
                pass
            self.win.destroy()  # 销毁窗口，退出 mainloop

    controller = MenubarController.alloc().init()

    if hide_on_close:
        win.protocol("WM_DELETE_WINDOW", win.withdraw)  # 关闭 = 隐藏，调度继续

    def _refresh() -> None:
        try:
            gold = win.status_vars.get("gold")
            gold_text = gold.get().strip() if gold else ""
            story = win.status_vars.get("story")
            story_text = story.get().strip() if story else ""

            # 连接断开检测：调度器的 activity 文本会实时更新（含「重连/暂停/异常」等），
            # 此时 _current_action 会停留在旧值（status 回调不再触发），需覆盖。
            if any(k in story_text for k in ("重连", "暂停", "异常", "未连接", "断开")):
                action = "连接断开"
            else:
                action = getattr(win, "_current_action", "") or "启动中"

            if gold_text:
                title = f"🐾 金币 {gold_text} · {action}"
                detail = f"金币 {gold_text}"
            else:
                title = f"🐾 {action}"
                detail = "等待连接…"

            for var_name, label in (
                ("mood", "心情"), ("hunger", "体力"), ("clean", "清洁"),
            ):
                v = win.status_vars.get(var_name)
                if v and v.get().strip():
                    detail += f" · {label} {v.get().strip()}"

            detail += f" · {action}"
            if story_text:
                detail += f" · {story_text}"

            controller._status.button().setTitle_(title)
            controller._detail_item.setTitle_(detail)
            running = bool(
                win.scheduler_thread and win.scheduler_thread.is_alive()
            )
            controller._toggle_item.setTitle_("停止托管" if running else "开始托管")
        except Exception:  # noqa: BLE001 - 窗口销毁后 after 可能抛错
            pass
        try:
            win.after(1000, _refresh)
        except Exception:  # noqa: BLE001
            pass

    win.after(1000, _refresh)
    return controller
