"""
B站数据爬取工具 —— Tkinter 图形化界面。

功能:
  - 扫码登录 / Cookie 状态显示
  - 通过 UID 查询用户主页信息
  - 查看用户视频列表

用法:
    python gui.py
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

from .login import (
    get_cookie_string,
    is_logged_in,
    load_cookies,
    qr_login,
)
from .wbi import enc_wbi, get_wbi_keys

# ─── 颜色 / 字体常量 ─────────────────────────────────────────
_COLOR_BILI_PINK = "#fb7299"
_COLOR_BILI_BLUE = "#00a1d6"
_COLOR_BG = "#f5f5f5"
_COLOR_CARD = "#ffffff"
_FONT_TITLE = ("Microsoft YaHei", 16, "bold")
_FONT_HEADING = ("Microsoft YaHei", 11, "bold")
_FONT_BODY = ("Microsoft YaHei", 10)
_FONT_MONO = ("Consolas", 10)


class BiliSpiderGUI:
    """B站爬取工具主窗口。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BiliSpider - B站数据查询工具")
        self.root.geometry("960x720")
        self.root.minsize(800, 600)
        self.root.configure(bg=_COLOR_BG)

        # 状态
        self._logged_in = False
        self._username: Optional[str] = None
        self._uid: Optional[int] = None
        self._qr_window: Optional[tk.Toplevel] = None
        self._qr_login_active = False

        # UI 变量
        self._login_status_var = tk.StringVar(value="未登录")
        self._status_bar_var = tk.StringVar(value="就绪")

        self._build_ui()
        self._check_login_on_start()

    # ─── UI 构建 ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        """构建全部界面组件。"""
        self._build_title_bar()
        self._build_login_section()
        self._build_query_section()
        self._build_result_section()
        self._build_status_bar()

    def _build_title_bar(self) -> None:
        """顶部标题栏 (B站粉色)。"""
        bar = tk.Frame(self.root, bg=_COLOR_BILI_PINK, height=52)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Label(
            bar,
            text="BiliSpider — B站数据查询工具",
            fg="white",
            bg=_COLOR_BILI_PINK,
            font=_FONT_TITLE,
        ).pack(pady=10)

    def _build_login_section(self) -> None:
        """登录状态区域。"""
        frame = tk.LabelFrame(
            self.root, text="登录状态", font=_FONT_HEADING,
            bg=_COLOR_CARD, padx=12, pady=10,
        )
        frame.pack(fill=tk.X, padx=16, pady=(12, 6))

        row = tk.Frame(frame, bg=_COLOR_CARD)
        row.pack(fill=tk.X)

        tk.Label(
            row, textvariable=self._login_status_var,
            font=_FONT_BODY, bg=_COLOR_CARD, fg="#333",
        ).pack(side=tk.LEFT, padx=(0, 12))

        self._login_btn = tk.Button(
            row, text="🔐 扫码登录", command=self._start_qr_login,
            bg=_COLOR_BILI_PINK, fg="white",
            font=_FONT_BODY, cursor="hand2",
            relief=tk.FLAT, padx=16, pady=4,
        )
        self._login_btn.pack(side=tk.RIGHT, padx=4)

        self._refresh_btn = tk.Button(
            row, text="🔄 刷新状态", command=self._check_login,
            bg=_COLOR_BILI_BLUE, fg="white",
            font=_FONT_BODY, cursor="hand2",
            relief=tk.FLAT, padx=16, pady=4,
        )
        self._refresh_btn.pack(side=tk.RIGHT, padx=4)

    def _build_query_section(self) -> None:
        """UID 查询区域。"""
        frame = tk.LabelFrame(
            self.root, text="用户查询", font=_FONT_HEADING,
            bg=_COLOR_CARD, padx=12, pady=10,
        )
        frame.pack(fill=tk.X, padx=16, pady=6)

        row = tk.Frame(frame, bg=_COLOR_CARD)
        row.pack(fill=tk.X)

        tk.Label(
            row, text="目标 UID:",
            font=_FONT_BODY, bg=_COLOR_CARD,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self._uid_entry = tk.Entry(
            row, font=_FONT_BODY, width=20,
        )
        self._uid_entry.pack(side=tk.LEFT, padx=(0, 8))
        self._uid_entry.bind("<Return>", lambda _e: self._query_user())
        # 默认值: B站站长 bishi 的 UID
        self._uid_entry.insert(0, "2")

        self._query_btn = tk.Button(
            row, text="🔍 查询", command=self._query_user,
            bg=_COLOR_BILI_BLUE, fg="white",
            font=_FONT_BODY, cursor="hand2",
            relief=tk.FLAT, padx=20, pady=4,
        )
        self._query_btn.pack(side=tk.LEFT)

    def _build_result_section(self) -> None:
        """结果展示区域 (Notebook 双标签)。"""
        nb_frame = tk.Frame(self.root, bg=_COLOR_BG)
        nb_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(6, 4))

        self._notebook = ttk.Notebook(nb_frame)

        # 标签页 1: 用户信息
        self._info_tab = tk.Frame(self._notebook, bg=_COLOR_CARD)
        self._info_text = scrolledtext.ScrolledText(
            self._info_tab, font=_FONT_MONO, wrap=tk.WORD,
            state=tk.DISABLED, bg=_COLOR_CARD, relief=tk.FLAT,
        )
        self._info_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._notebook.add(self._info_tab, text="  📋 用户信息  ")

        # 标签页 2: 视频列表
        self._video_tab = tk.Frame(self._notebook, bg=_COLOR_CARD)
        self._video_text = scrolledtext.ScrolledText(
            self._video_tab, font=_FONT_MONO, wrap=tk.WORD,
            state=tk.DISABLED, bg=_COLOR_CARD, relief=tk.FLAT,
        )
        self._video_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._notebook.add(self._video_tab, text="  🎬 视频列表  ")

        self._notebook.pack(fill=tk.BOTH, expand=True)

    def _build_status_bar(self) -> None:
        """底部状态栏。"""
        bar = tk.Frame(self.root, bg="#e0e0e0", height=24)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)
        tk.Label(
            bar, textvariable=self._status_bar_var,
            font=("Microsoft YaHei", 9), bg="#e0e0e0", fg="#666",
            anchor=tk.W,
        ).pack(fill=tk.X, padx=12, pady=2)

    # ─── 登录逻辑 ───────────────────────────────────────────────

    def _check_login_on_start(self) -> None:
        """启动时检查登录状态。"""
        self.root.after(200, self._check_login)

    def _check_login(self) -> None:
        """检查当前 Cookie 是否有效并更新 UI。"""
        def _do() -> None:
            logged_in, username, uid = is_logged_in()
            self.root.after(0, lambda: self._update_login_ui(logged_in, username, uid))
        threading.Thread(target=_do, daemon=True).start()

    def _update_login_ui(
        self, logged_in: bool, username: Optional[str], uid: Optional[int],
    ) -> None:
        """根据登录状态刷新 UI。"""
        self._logged_in = logged_in
        self._username = username
        self._uid = uid
        if logged_in and username:
            self._login_status_var.set(f"✅ 已登录: {username} (UID: {uid})")
            self._login_btn.configure(text="🔄 重新登录")
        else:
            self._login_status_var.set("❌ 未登录 — 请扫码登录后使用查询功能")
            self._login_btn.configure(text="🔐 扫码登录")

    def _start_qr_login(self) -> None:
        """启动扫码登录 (弹出二维码窗口)。"""
        if self._qr_login_active:
            return
        self._qr_login_active = True
        self._set_status("正在生成登录二维码...")

        # 弹出二维码等待窗口
        self._qr_window = tk.Toplevel(self.root)
        self._qr_window.title("扫码登录")
        self._qr_window.geometry("420x520")
        self._qr_window.configure(bg=_COLOR_CARD)
        self._qr_window.resizable(False, False)
        self._qr_window.protocol(
            "WM_DELETE_WINDOW", self._cancel_qr_login,
        )

        tk.Label(
            self._qr_window,
            text="请使用哔哩哔哩 App 扫码登录",
            font=_FONT_HEADING, bg=_COLOR_CARD, fg="#333",
        ).pack(pady=(16, 8))

        # 二维码链接标签 (复制用)
        self._qr_url_var = tk.StringVar(value="正在生成...")
        url_label = tk.Label(
            self._qr_window,
            textvariable=self._qr_url_var,
            font=("Microsoft YaHei", 8), bg=_COLOR_CARD, fg="#888",
            wraplength=380,
        )
        url_label.pack(padx=16, pady=(0, 8))

        # 状态提示
        self._qr_status_var = tk.StringVar(value="⏳ 正在生成二维码...")
        tk.Label(
            self._qr_window,
            textvariable=self._qr_status_var,
            font=_FONT_BODY, bg=_COLOR_CARD, fg=_COLOR_BILI_BLUE,
        ).pack(pady=(0, 8))

        # 取消按钮
        tk.Button(
            self._qr_window,
            text="取消登录",
            command=self._cancel_qr_login,
            bg="#e0e0e0", fg="#333",
            font=_FONT_BODY, cursor="hand2",
            relief=tk.FLAT, padx=20, pady=4,
        ).pack(pady=(0, 16))

        # 在后台线程中执行登录
        cancel_event = threading.Event()
        self._qr_cancel_event = cancel_event

        def _status_callback(msg: str) -> None:
            if msg.startswith("__QRCODE_URL__:"):
                url = msg[len("__QRCODE_URL__:"):]
                self.root.after(0, lambda: self._qr_url_var.set(url))
            elif "扫描" in msg or "扫码" in msg or "确认" in msg:
                self.root.after(0, lambda: self._qr_status_var.set(f"📱 {msg}"))
            elif "成功" in msg:
                self.root.after(0, lambda: self._on_qr_success(msg))
            elif "过期" in msg or "取消" in msg or "失败" in msg:
                self.root.after(0, lambda: self._on_qr_failure(msg))

        def _login_thread() -> None:
            try:
                qr_login(
                    status_callback=_status_callback,
                    cancel_event=cancel_event,
                )
            except Exception as e:
                self.root.after(0, lambda: self._on_qr_failure(f"登录异常: {e}"))

        threading.Thread(target=_login_thread, daemon=True).start()

    def _on_qr_success(self, msg: str) -> None:
        """扫码成功后关闭窗口并更新状态。"""
        self._qr_status_var.set(f"✅ {msg}")
        self._qr_login_active = False
        if self._qr_window:
            self._qr_window.after(800, self._qr_window.destroy)
            self._qr_window = None
        self._set_status("登录成功")
        self._check_login()

    def _on_qr_failure(self, msg: str) -> None:
        """扫码失败后更新状态。"""
        self._qr_status_var.set(f"❌ {msg}")
        self._qr_login_active = False
        self._set_status(msg)
        # 可关闭窗口
        if self._qr_window:
            self._qr_window.title("扫码登录 — 失败")

    def _cancel_qr_login(self) -> None:
        """用户取消扫码。"""
        if hasattr(self, "_qr_cancel_event"):
            self._qr_cancel_event.set()
        self._qr_login_active = False
        self._set_status("已取消扫码登录")
        if self._qr_window:
            self._qr_window.destroy()
            self._qr_window = None

    # ─── 查询逻辑 ───────────────────────────────────────────────

    def _query_user(self) -> None:
        """根据输入的 UID 查询用户信息和视频列表。"""
        uid_text = self._uid_entry.get().strip()
        if not uid_text:
            messagebox.showwarning("提示", "请输入目标用户的 UID")
            return
        if not uid_text.isdigit():
            messagebox.showwarning("提示", "UID 必须是纯数字")
            return

        cookie = get_cookie_string()
        if not cookie:
            messagebox.showwarning("提示", "请先扫码登录后再查询")
            return

        uid = uid_text
        self._set_status(f"正在查询 UID={uid} 的用户信息...")
        self._query_btn.configure(state=tk.DISABLED, text="⏳ 查询中...")
        self._clear_result()

        threading.Thread(
            target=self._do_query, args=(uid, cookie), daemon=True,
        ).start()

    def _do_query(self, uid: str, cookie: str) -> None:
        """在后台线程中执行用户信息和视频列表查询。"""
        # ── 查询用户信息 ──
        try:
            img_key, sub_key = get_wbi_keys()
            import requests
            signed = enc_wbi({"mid": uid}, img_key=img_key, sub_key=sub_key)
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/119.0.0.0 Safari/537.36"
                ),
                "Referer": f"https://space.bilibili.com/{uid}/",
                "Cookie": cookie,
            }
            resp = requests.get(
                "https://api.bilibili.com/x/space/wbi/acc/info",
                params=signed, headers=headers, timeout=10,
            )
            resp.raise_for_status()
            info_result = resp.json()
        except Exception as e:
            self.root.after(0, lambda: self._show_error(f"用户信息查询失败: {e}"))
            return

        # ── 查询视频列表 ──
        try:
            import requests as req2
            img_key2, sub_key2 = get_wbi_keys()
            video_params = enc_wbi({
                "mid": uid, "ps": 30, "tid": 0, "pn": 1,
                "keyword": "", "order": "pubdate", "platform": "web",
                "web_location": 1550101, "order_avoided": "true",
            }, img_key=img_key2, sub_key=sub_key2)
            headers2 = {
                "User-Agent": headers["User-Agent"],
                "Referer": f"https://space.bilibili.com/{uid}/video",
                "Cookie": cookie,
            }
            resp2 = req2.get(
                "https://api.bilibili.com/x/space/wbi/arc/search",
                params=video_params, headers=headers2, timeout=15,
            )
            resp2.raise_for_status()
            video_result = resp2.json()
        except Exception as e:
            video_result = None

        self.root.after(0, lambda: self._display_results(uid, info_result, video_result))

    def _display_results(self, uid: str, info: dict, video: Optional[dict]) -> None:
        """在主线程中展示查询结果。"""
        self._query_btn.configure(state=tk.NORMAL, text="🔍 查询")

        # ── 用户信息展示 ──
        if info.get("code") == 0:
            data = info["data"]
            lines = [
                "═" * 50,
                f"  用户信息 (UID: {uid})",
                "═" * 50,
                f"  用户名   : {data.get('name', 'N/A')}",
                f"  UID      : {data.get('mid', 'N/A')}",
                f"  等级     : LV{data.get('level', '?')}",
                f"  性别     : {data.get('sex', 'N/A')}",
                f"  签名     : {data.get('sign', '')}",
                f"  生日     : {data.get('birthday', 'N/A')}",
                f"  粉丝数   : {data.get('follower', 0):,}",
                f"  关注数   : {data.get('following', 0):,}",
                f"  获赞数   : {data.get('likes', 0):,}",
                "",
            ]
        else:
            lines = [
                f"❌ 查询失败: code={info.get('code')}, {info.get('message', '')}",
                "",
            ]

        self._info_text.configure(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)
        self._info_text.insert(tk.END, "\n".join(lines))
        self._info_text.configure(state=tk.DISABLED)

        # ── 视频列表展示 ──
        if video and video.get("code") == 0:
            vdata = video["data"]
            vlist = vdata["list"]["vlist"]
            total = vdata["page"]["count"]
            vlines = [
                "═" * 60,
                f"  视频列表 (UID: {uid}) — 共 {total} 个视频，本页 {len(vlist)} 个",
                "═" * 60,
                "",
            ]
            for idx, v in enumerate(vlist, 1):
                vlines.append(
                    f"  {idx:2d}. {v['title'][:42]:42s}"
                    f" BVID:{v['bvid']:12s} 播放:{v['play']:,}"
                )
        elif video:
            vlines = [
                f"❌ 视频列表获取失败: code={video.get('code')}, {video.get('message', '')}",
            ]
        else:
            vlines = ["⚠️ 视频列表获取失败 (网络异常)", ""]

        self._video_text.configure(state=tk.NORMAL)
        self._video_text.delete("1.0", tk.END)
        self._video_text.insert(tk.END, "\n".join(vlines))
        self._video_text.configure(state=tk.DISABLED)

        self._set_status(f"查询完成 — UID={uid}")

    def _show_error(self, msg: str) -> None:
        """在 UI 中展示错误信息。"""
        self._query_btn.configure(state=tk.NORMAL, text="🔍 查询")
        self._info_text.configure(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)
        self._info_text.insert(tk.END, f"❌ {msg}\n")
        self._info_text.configure(state=tk.DISABLED)
        self._set_status(msg)

    def _clear_result(self) -> None:
        """清空结果展示区。"""
        for widget in (self._info_text, self._video_text):
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.configure(state=tk.DISABLED)

    def _set_status(self, msg: str) -> None:
        """更新底部状态栏。"""
        self._status_bar_var.set(msg)


def main() -> None:
    """GUI 入口函数。"""
    root = tk.Tk()

    # 尝试设置 DPI 感知 (Windows)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # 设置 ttk 主题
    style = ttk.Style()
    available = style.theme_names()
    if "vista" in available:
        style.theme_use("vista")
    elif "clam" in available:
        style.theme_use("clam")

    # 配置 Notebook 标签页样式
    style.configure("TNotebook", background=_COLOR_BG, borderwidth=0)
    style.configure("TNotebook.Tab", font=_FONT_BODY, padding=[16, 6])
    style.map(
        "TNotebook.Tab",
        background=[("selected", _COLOR_CARD), ("!selected", "#e8e8e8")],
    )

    BiliSpiderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
