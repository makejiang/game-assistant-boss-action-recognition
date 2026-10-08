#!/usr/bin/env python3
"""
游戏选择提醒弹窗（纯展示）
  skill 触发（体验 Boss 招式识别助手意图）时，由 agent 先调用本脚本弹窗提醒：
  显著位置展示「已支持游戏列表（不断完善中，欢迎玩家贡献）」，列表下方附
  Vibe Coding 引导语。无论用户原话是否带游戏名都会弹出。

  弹窗纯展示、不可点选、不收集任何输入，不改变后续流程。已支持列表为
  固定常量（本 Demo 仅适配《鬼武者：剑之道》），新增游戏时改 SUPPORTED_GAMES。

用法:
    python game_notice_dialog.py

15 秒无操作自动关闭（倒计时显示在「关闭」按钮上）。

输出（stdout 仅一行 JSON；错误与日志走 stderr）:
    {"status": "acknowledged"}                 # 用户点「关闭」/ × / Esc 或倒计时归零
    {"status": "error", "message": "..."}      # tkinter 不可用等异常
"""

from __future__ import annotations

import json
import sys

# 已支持游戏列表：一项一行，新增游戏在列表里追加即可
SUPPORTED_GAMES = [
    "《鬼武者：剑之道》（Boss：佐佐木岩流）",
]
LIST_TITLE = "已支持游戏列表（不断完善中，欢迎玩家贡献）"
VIBE_TAGLINE = "更多游戏支持 Vibe Coding 自由创作，欢迎玩家自行探索与尝试"
# 列表超过此行数时固定高度 + 滚动条，窗口不随游戏数量无限拉高
MAX_VISIBLE_ROWS = 6
# 无操作自动关闭倒计时（秒）：提醒弹窗不该一直挡在屏幕上
AUTO_CLOSE_SECONDS = 15


def _detect_dark() -> bool:
    """跟随系统深色模式（读不到时按浅色处理），与 deploy.py FilePickerDialog 一致。"""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return val == 0
    except Exception:
        return False


class GameNoticeDialog:
    """纯展示提醒弹窗：展示已支持游戏列表，点「关闭」或倒计时归零即关。"""

    _LIGHT = {
        "bg": "#f5f5f5", "card": "#ffffff", "border": "#e0e0e0",
        "text": "#333333", "text_sec": "#666666",
        "accent": "#0078D4", "accent_h": "#106ebe", "btn_p_t": "#ffffff",
        "row": "#fafbfc",
    }
    _DARK = {
        "bg": "#1e1e1e", "card": "#2d2d2d", "border": "#404040",
        "text": "#e0e0e0", "text_sec": "#a0a0a0",
        "accent": "#4daafc", "accent_h": "#1a8ce8", "btn_p_t": "#ffffff",
        "row": "#383838",
    }

    def __init__(self, games: list[str]) -> None:
        import tkinter as tk

        self._tk = tk
        self.games = games
        self.result: dict | None = None
        self.c = self._DARK if _detect_dark() else self._LIGHT
        self._remaining = AUTO_CLOSE_SECONDS
        self._countdown_after: str | None = None
        self._build()

    def _build(self) -> None:
        tk = self._tk
        c = self.c

        self.root = tk.Tk()
        self.root.title("游戏助手 · 温馨提示")
        self.root.resizable(False, False)
        self.root.configure(bg=c["bg"])
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._ack)
        self.root.bind("<Escape>", lambda _e: self._ack())

        card = tk.Frame(self.root, bg=c["card"],
                        highlightthickness=1, highlightbackground=c["border"])
        card.pack(padx=1, pady=1, fill="both", expand=True)
        inner = tk.Frame(card, bg=c["card"], padx=28, pady=24)
        inner.pack(fill="both", expand=True)

        # 显著位置：主题色竖条 + 加粗列表标题
        head = tk.Frame(inner, bg=c["card"])
        head.pack(fill="x", pady=(0, 8))
        tk.Frame(head, bg=c["accent"], width=3, height=16).pack(side="left", padx=(0, 8))
        tk.Label(head, text=LIST_TITLE, font=("Microsoft YaHei UI", 11, "bold"),
                 fg=c["text"], bg=c["card"]).pack(side="left")

        if not self.games:
            tk.Label(inner, text="暂无已支持游戏", font=("Microsoft YaHei UI", 10),
                     fg=c["text_sec"], bg=c["card"], pady=12).pack(fill="x")
        else:
            self._build_game_rows(inner)

        # Vibe Coding 引导语（列表下方，次级色小字）
        tk.Label(inner, text=VIBE_TAGLINE, font=("Microsoft YaHei UI", 9),
                 fg=c["text_sec"], bg=c["card"], justify="left",
                 wraplength=470).pack(anchor="w", pady=(12, 0))

        btn_bar = tk.Frame(inner, bg=c["card"])
        btn_bar.pack(side="bottom", fill="x", pady=(18, 0))
        # 倒计时直接显示在按钮上，不另占一处 UI
        self._ack_btn = self._mk_btn(
            btn_bar, f"关闭（{self._remaining}s）", c["accent"], c["accent_h"],
            c["btn_p_t"], self._ack, bold=True,
        )
        self._ack_btn.pack(side="right")

        self._center_and_show()
        self._start_countdown()

    def _build_game_rows(self, page) -> None:
        """纯展示行（Label，不可点）：弹窗只负责提醒，不收集选择。"""
        tk = self._tk
        c = self.c

        if len(self.games) > MAX_VISIBLE_ROWS:
            canvas = tk.Canvas(page, bg=c["card"], highlightthickness=0,
                               height=MAX_VISIBLE_ROWS * 32)
            bar = tk.Scrollbar(page, orient="vertical", command=canvas.yview)
            body = tk.Frame(canvas, bg=c["card"])
            win_id = canvas.create_window((0, 0), window=body, anchor="nw")
            body.bind("<Configure>",
                      lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>",
                        lambda e: canvas.itemconfigure(win_id, width=e.width))

            def _on_wheel(event) -> None:
                canvas.yview_scroll(-1 * int(event.delta / 120), "units")

            canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
            canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

            canvas.pack(side="left", fill="both", expand=True)
            bar.pack(side="right", fill="y")
            container = body
        else:
            container = tk.Frame(page, bg=c["card"])
            container.pack(fill="x")

        for name in self.games:
            tk.Label(container, text=name, anchor="w",
                     font=("Microsoft YaHei UI", 11),
                     fg=c["text"], bg=c["row"], padx=14, pady=5,
                     ).pack(fill="x", pady=(0, 2))

    # ── 动作与小部件工具 ──────────────────────────────────────

    def _start_countdown(self) -> None:
        self._update_ack_btn()
        self._schedule_tick()

    def _schedule_tick(self) -> None:
        self._countdown_after = self.root.after(1000, self._tick_countdown)

    def _tick_countdown(self) -> None:
        if self.result is not None:
            return  # 用户已手动关闭，倒计时作废
        self._remaining -= 1
        if self._remaining <= 0:
            self._ack()
            return
        self._update_ack_btn()
        self._schedule_tick()

    def _update_ack_btn(self) -> None:
        self._ack_btn.config(text=f"关闭（{self._remaining}s）")

    def _ack(self) -> None:
        if self._countdown_after is not None:
            try:
                self.root.after_cancel(self._countdown_after)
            except Exception:
                pass
        self.result = {"status": "acknowledged"}
        self.root.destroy()

    def _mk_btn(self, parent, text, bg, bg_h, fg, cmd, bold=False):
        tk = self._tk
        weight = "bold" if bold else "normal"
        btn = tk.Button(
            parent, text=text, command=cmd,
            font=("Microsoft YaHei UI", 10, weight),
            bg=bg, fg=fg, activebackground=bg_h, activeforeground=fg,
            relief="flat", borderwidth=0, padx=18, pady=6, cursor="hand2",
        )
        btn.bind("<Enter>", lambda _e, b=btn, h=bg_h: b.config(bg=h))
        btn.bind("<Leave>", lambda _e, b=btn, n=bg: b.config(bg=n))
        return btn

    def _center_and_show(self) -> None:
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), 540)
        h = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        try:
            self.root.grab_set()  # 模态；个别环境下可能失败，失败只是不模态，不算致命
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    # stdout 是 agent 的解析契约（一行 JSON），与 walkthrough 同名脚本一致强制 UTF-8
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    result: dict
    try:
        import tkinter  # noqa: F401  提前探测：缺 tkinter 时走统一的 error JSON，而不是 traceback
        dialog = GameNoticeDialog(list(SUPPORTED_GAMES))
        dialog.run()
        result = dialog.result or {"status": "acknowledged"}
    except Exception as exc:
        print(f"game_notice_dialog failed: {exc}", file=sys.stderr)
        result = {"status": "error", "message": str(exc)}

    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
