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

import json
import os
import sys
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
from .comment_crawler import CommentCrawler
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

        # 评论爬取状态
        self._crawler: Optional[CommentCrawler] = None
        self._crawling = False

        # UI 变量
        self._login_status_var = tk.StringVar(value="未登录")
        self._status_bar_var = tk.StringVar(value="就绪")

        self._config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
        )

        self._build_ui()
        self._load_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._check_login_on_start()

    # ─── 配置持久化 ─────────────────────────────────────────────

    def _load_config(self) -> None:
        """从 config.json 恢复上次填入的数据。"""
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self._uid_entry.delete(0, tk.END)
            self._uid_entry.insert(0, cfg.get("query_uid", "2"))
            self._crawl_uid_entry.delete(0, tk.END)
            self._crawl_uid_entry.insert(0, cfg.get("crawl_uid", "2"))
            self._crawl_days_var.set(cfg.get("crawl_days", "30"))
            self._crawl_max_var.set(cfg.get("crawl_max", "5"))
            self._crawl_proxy_entry.delete(0, tk.END)
            self._crawl_proxy_entry.insert(0, cfg.get("proxy", ""))
            self._search_uid_entry.delete(0, tk.END)
            self._search_uid_entry.insert(0, cfg.get("search_uid", "2"))
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def _save_config(self) -> None:
        """保存当前GUI输入值到 config.json。"""
        cfg = {
            "query_uid": self._uid_entry.get().strip(),
            "crawl_uid": self._crawl_uid_entry.get().strip(),
            "crawl_days": self._crawl_days_var.get(),
            "crawl_max": self._crawl_max_var.get(),
            "proxy": self._crawl_proxy_entry.get().strip(),
            "search_uid": self._search_uid_entry.get().strip(),
        }
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self) -> None:
        """窗口关闭时保存配置。"""
        self._save_config()
        self.root.destroy()

    # ─── 待爬队列 ───────────────────────────────────────────────

    @property
    def _queue_path(self) -> str:
        return os.path.join(os.path.dirname(self._config_path), "crawl_queue.json")

    def _load_queue(self) -> list[str]:
        try:
            with open(self._queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_queue(self, uids: list[str]) -> None:
        with open(self._queue_path, "w", encoding="utf-8") as f:
            json.dump(uids, f, ensure_ascii=False)

    def _add_to_queue(self) -> None:
        """将当前UID添加到待爬队列。"""
        uid = self._crawl_uid_entry.get().strip()
        if not uid.isdigit():
            return
        queue = self._load_queue()
        if uid in queue:
            self._set_status(f"UID {uid} 已在队列中")
            return
        queue.append(uid)
        self._save_queue(queue)
        self._refresh_queue_display()
        self._set_status(f"UID {uid} 已加入待爬队列")

    def _clear_queue(self) -> None:
        self._save_queue([])
        self._refresh_queue_display()
        self._set_status("待爬队列已清空")

    def _pop_next_uid(self) -> str | None:
        """从队列取下一个UID (不移除,最后由爬取完成时移除)。"""
        queue = self._load_queue()
        return queue[0] if queue else None

    def _remove_current_from_queue(self, uid: str) -> None:
        """爬取完成后将当前UID从队列移除。"""
        queue = self._load_queue()
        if uid in queue:
            queue.remove(uid)
            self._save_queue(queue)
        self._refresh_queue_display()

    def _refresh_queue_display(self) -> None:
        queue = self._load_queue()
        if queue:
            self._queue_var.set(f"队列({len(queue)}): {' → '.join(queue[:8])}" + ("..." if len(queue) > 8 else ""))
        else:
            self._queue_var.set("队列: (空)")

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

        # 标签页 3: 评论爬取
        self._crawler_tab = tk.Frame(self._notebook, bg=_COLOR_CARD)
        self._build_crawler_tab(self._crawler_tab)
        self._notebook.add(self._crawler_tab, text="  💬 评论爬取  ")

        self._notebook.pack(fill=tk.BOTH, expand=True)

    def _build_crawler_tab(self, parent: tk.Frame) -> None:
        """构建评论爬取标签页的 UI。"""
        # ── 参数配置区 ──
        cfg = tk.LabelFrame(parent, text="爬取参数", font=_FONT_HEADING,
                            bg=_COLOR_CARD, padx=10, pady=8)
        cfg.pack(fill=tk.X, padx=6, pady=(6, 4))

        row1 = tk.Frame(cfg, bg=_COLOR_CARD)
        row1.pack(fill=tk.X, pady=2)
        tk.Label(row1, text="目标UID:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._crawl_uid_entry = tk.Entry(row1, font=_FONT_BODY, width=18)
        self._crawl_uid_entry.pack(side=tk.LEFT, padx=6)
        self._crawl_uid_entry.insert(0, "2")

        tk.Button(row1, text="+队列", command=self._add_to_queue,
                  bg="#8a8a8a", fg="white", font=("Microsoft YaHei", 8),
                  cursor="hand2", relief=tk.FLAT, padx=6, pady=1).pack(side=tk.LEFT, padx=4)

        tk.Label(row1, text="最近天数:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(16, 0))
        self._crawl_days_var = tk.StringVar(value="30")
        tk.Spinbox(row1, textvariable=self._crawl_days_var, from_=0, to=365,
                   width=5, font=_FONT_BODY).pack(side=tk.LEFT, padx=4)
        tk.Label(row1, text="(0=不限)", font=("Microsoft YaHei", 8),
                 bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT)

        tk.Label(row1, text="最大视频:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(16, 0))
        self._crawl_max_var = tk.StringVar(value="5")
        tk.Spinbox(row1, textvariable=self._crawl_max_var, from_=0, to=500,
                   width=5, font=_FONT_BODY).pack(side=tk.LEFT, padx=4)
        tk.Label(row1, text="(0=不限)", font=("Microsoft YaHei", 8),
                 bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT)

        row2 = tk.Frame(cfg, bg=_COLOR_CARD)
        row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="代理:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._crawl_proxy_entry = tk.Entry(row2, font=_FONT_BODY, width=38)
        self._crawl_proxy_entry.pack(side=tk.LEFT, padx=6)
        tk.Label(row2, text="(留空=flclash自动检测 / haipproxy池)", font=("Microsoft YaHei", 8),
                 bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT)

        # 待爬队列
        queue_row = tk.Frame(cfg, bg=_COLOR_CARD)
        queue_row.pack(fill=tk.X, pady=(4, 0))
        self._queue_var = tk.StringVar(value="队列: (空)")
        tk.Label(queue_row, textvariable=self._queue_var, font=("Microsoft YaHei", 8),
                 bg=_COLOR_CARD, fg=_COLOR_BILI_BLUE).pack(side=tk.LEFT)
        tk.Button(queue_row, text="清空", command=self._clear_queue,
                  font=("Microsoft YaHei", 7), relief=tk.FLAT, padx=4, pady=0,
                  cursor="hand2").pack(side=tk.RIGHT)
        self._refresh_queue_display()

        # ── 控制按钮 ──
        btn_row = tk.Frame(cfg, bg=_COLOR_CARD)
        btn_row.pack(fill=tk.X, pady=(6, 0))
        self._crawl_start_btn = tk.Button(
            btn_row, text="▶ 开始爬取", command=self._start_crawl,
            bg=_COLOR_BILI_PINK, fg="white", font=_FONT_BODY,
            cursor="hand2", relief=tk.FLAT, padx=16, pady=3,
        )
        self._crawl_start_btn.pack(side=tk.LEFT, padx=4)
        self._crawl_stop_btn = tk.Button(
            btn_row, text="⏹ 停止", command=self._stop_crawl,
            bg="#e74c3c", fg="white", font=_FONT_BODY,
            cursor="hand2", relief=tk.FLAT, padx=16, pady=3,
            state=tk.DISABLED,
        )
        self._crawl_stop_btn.pack(side=tk.LEFT, padx=4)

        # 基准测试按钮
        tk.Label(btn_row, text="基准:", font=("Microsoft YaHei", 9), bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT, padx=(12, 2))
        for label, mode, sec in [("快速", "quick", 30), ("中测", "medium", 120), ("通宵", "overnight", 480)]:
            btn = tk.Button(btn_row, text=f"{mode}", width=4,
                            command=lambda m=mode: self._start_benchmark(m),
                            bg="#8a8a8a", fg="white", font=("Microsoft YaHei", 8),
                            relief=tk.FLAT, padx=4, pady=1, cursor="hand2")
            btn.pack(side=tk.LEFT, padx=1)
            tk.Tooltip = type("Tooltip", (), {})
            # 简单tooltip: 用title属性
            setattr(btn, "tooltip_timer", None)
            def _enter(_e, t=f"{label}({sec}min)"): pass  # 简单的title提示
        tk.Label(btn_row, text="", font=("Microsoft YaHei", 8), bg=_COLOR_CARD).pack(side=tk.LEFT)

        # 基准测试实时指标
        self._bench_metrics_var = tk.StringVar(value="")
        tk.Label(btn_row, textvariable=self._bench_metrics_var,
                 font=("Microsoft YaHei", 8), bg=_COLOR_CARD, fg=_COLOR_BILI_BLUE).pack(side=tk.LEFT, padx=6)

        self._crawl_stats_var = tk.StringVar(value="就绪")
        tk.Label(btn_row, textvariable=self._crawl_stats_var,
                 font=("Microsoft YaHei", 9), bg=_COLOR_CARD, fg="#666").pack(side=tk.RIGHT)

        # ── 进度条 ──
        progress_row = tk.Frame(cfg, bg=_COLOR_CARD)
        progress_row.pack(fill=tk.X, pady=(4, 0))
        self._crawl_progress = ttk.Progressbar(
            progress_row, mode="determinate", length=400,
        )
        self._crawl_progress.pack(fill=tk.X, side=tk.LEFT, expand=True)
        self._crawl_progress_label = tk.Label(
            progress_row, text="", font=("Microsoft YaHei", 8),
            bg=_COLOR_CARD, fg="#888", width=20, anchor=tk.W,
        )
        self._crawl_progress_label.pack(side=tk.RIGHT, padx=(6, 0))

        # ── 速率控制面板 ──
        rate_cfg = tk.LabelFrame(cfg, text="速率控制", font=_FONT_HEADING,
                                 bg=_COLOR_CARD, padx=8, pady=6)
        rate_cfg.pack(fill=tk.X, pady=(6, 2))

        row_r1 = tk.Frame(rate_cfg, bg=_COLOR_CARD)
        row_r1.pack(fill=tk.X)
        tk.Label(row_r1, text="基础延迟(s):", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._rate_base_var = tk.StringVar(value="2.0")
        tk.Spinbox(row_r1, textvariable=self._rate_base_var, from_=0.5, to=60, increment=0.5,
                   width=5, font=_FONT_BODY).pack(side=tk.LEFT, padx=4)
        tk.Label(row_r1, text="抖动(s):", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(12, 0))
        self._rate_jitter_var = tk.StringVar(value="2.0")
        tk.Spinbox(row_r1, textvariable=self._rate_jitter_var, from_=0.3, to=30, increment=0.3,
                   width=5, font=_FONT_BODY).pack(side=tk.LEFT, padx=4)

        tk.Label(row_r1, text="沉睡(min):", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(12, 0))
        self._snooze_var = tk.StringVar(value="10")
        tk.Spinbox(row_r1, textvariable=self._snooze_var, from_=1, to=120, increment=1,
                   width=5, font=_FONT_BODY).pack(side=tk.LEFT, padx=4)

        row_r2 = tk.Frame(rate_cfg, bg=_COLOR_CARD)
        row_r2.pack(fill=tk.X, pady=(4, 0))
        self._auto_tune_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row_r2, text="自适应提速", variable=self._auto_tune_var,
                       bg=_COLOR_CARD, font=_FONT_BODY).pack(side=tk.LEFT, padx=2)
        self._auto_snooze_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row_r2, text="自适应沉睡", variable=self._auto_snooze_var,
                       bg=_COLOR_CARD, font=_FONT_BODY).pack(side=tk.LEFT, padx=2)

        self._rate_live_var = tk.StringVar(value="状态: --")
        tk.Label(row_r2, textvariable=self._rate_live_var,
                 font=("Microsoft YaHei", 8), bg=_COLOR_CARD, fg="#888").pack(side=tk.RIGHT, padx=6)

        # ── 评论检索 ──
        search_row = tk.Frame(parent, bg=_COLOR_CARD)
        search_row.pack(fill=tk.X, padx=6, pady=(6, 0))
        tk.Label(search_row, text="检索评论(UID):", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._search_uid_entry = tk.Entry(search_row, font=_FONT_BODY, width=18)
        self._search_uid_entry.pack(side=tk.LEFT, padx=6)
        self._search_uid_entry.bind("<Return>", lambda _e: self._search_comments())
        tk.Button(search_row, text="搜索", command=self._search_comments,
                  bg=_COLOR_BILI_BLUE, fg="white", font=_FONT_BODY,
                  cursor="hand2", relief=tk.FLAT, padx=12, pady=2).pack(side=tk.LEFT, padx=4)
        self._search_count_var = tk.StringVar(value="")
        tk.Label(search_row, textvariable=self._search_count_var,
                 font=("Microsoft YaHei", 9), bg=_COLOR_CARD, fg="#888").pack(side=tk.RIGHT)

        # ── 日志输出区 ──
        self._crawl_log = scrolledtext.ScrolledText(
            parent, font=_FONT_MONO, wrap=tk.WORD,
            state=tk.DISABLED, bg="#1e1e1e", fg="#d4d4d4",
            relief=tk.FLAT, insertbackground="white",
        )
        self._crawl_log.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 6))

    # ─── 评论爬取逻辑 ─────────────────────────────────────────

    def _start_crawl(self) -> None:
        """启动评论爬取。"""
        if self._crawling:
            return
        uid = self._crawl_uid_entry.get().strip()
        if not uid.isdigit():
            # 输入为空时尝试从队列取第一个UID
            queue = self._load_queue()
            if queue:
                uid = queue[0]
                self._crawl_uid_entry.delete(0, tk.END)
                self._crawl_uid_entry.insert(0, uid)
            else:
                messagebox.showwarning("提示", "请输入有效的目标 UID 或先添加到待爬队列")
                return

        # 解析参数
        days = int(self._crawl_days_var.get() or 0)
        max_videos = int(self._crawl_max_var.get() or 0)
        proxy = self._crawl_proxy_entry.get().strip()
        proxies = [proxy] if proxy else []

        # 时间过滤
        since_ts = 0
        if days > 0:
            from datetime import datetime, timedelta
            since_ts = int((datetime.now() - timedelta(days=days)).timestamp())

        self._crawling = True
        self._current_crawl_uid = uid
        self._queue_continue = True
        self._crawl_start_btn.configure(state=tk.DISABLED)
        self._crawl_stop_btn.configure(state=tk.NORMAL)
        self._crawl_stats_var.set("正在初始化...")
        self._crawl_progress["value"] = 0
        self._crawl_progress_label.configure(text="")
        self._crawl_log_clear()
        self._crawl_log_append(f"=== 开始爬取 UID={uid} ===\n")
        if days:
            self._crawl_log_append(f"时间范围: 最近 {days} 天\n")
        if max_videos:
            self._crawl_log_append(f"视频限制: 最多 {max_videos} 个\n")
        if proxy:
            self._crawl_log_append(f"代理: {proxy}\n")
        self._crawl_log_append("")

        def _run() -> None:
            # 进度回调: 当前视频号 / 总数 / 标题
            def _on_progress(current: int, total: int, label: str):
                self.root.after(0, lambda: self._update_crawl_progress(current, total, label))

            crawler = CommentCrawler()
            # 读取速率控制参数
            rate_base = float(self._rate_base_var.get() or 2.0)
            rate_jitter = float(self._rate_jitter_var.get() or 2.0)
            snooze_min = int(self._snooze_var.get() or 10)
            auto_tune = self._auto_tune_var.get()
            auto_snooze = self._auto_snooze_var.get()

            crawler.configure(
                since_ts=since_ts, until_ts=0,
                max_videos=max_videos, proxies=proxies,
                progress_callback=_on_progress,
                rate_base=rate_base, rate_jitter=rate_jitter,
                snooze_minutes=snooze_min,
                auto_tune=auto_tune, auto_snooze=auto_snooze,
            )
            self._crawler = crawler

            # 重定向 print 到日志窗口
            import io
            old_stdout = sys.stdout
            log_buffer = io.StringIO()
            gui_log_append = self._crawl_log_append
            gui_root = self.root

            class _LogWriter:
                def write(self, s):
                    log_buffer.write(s)
                    if s.strip():
                        self.flush()
                def flush(self):
                    text = log_buffer.getvalue()
                    log_buffer.truncate(0)
                    log_buffer.seek(0)
                    if text:
                        gui_root.after(0, lambda t=text: gui_log_append(t))

            sys.stdout = _LogWriter()

            try:
                if not crawler.setup():
                    self.root.after(0, lambda: self._crawl_done("初始化失败: Cookie 无效"))
                    return
                result = crawler.crawl_by_uid(uid)
                self.root.after(0, lambda r=result: self._crawl_done(
                    f"完成! 一级:{r.get('total_root',0)} 子评论:{r.get('total_subs',0)} 总计:{r.get('db_total',0)}"
                ))
            except Exception as e:
                self.root.after(0, lambda: self._crawl_done(f"出错: {e}"))
            finally:
                sys.stdout = old_stdout

        threading.Thread(target=_run, daemon=True).start()

    def _stop_crawl(self) -> None:
        """停止爬取。"""
        if self._crawler:
            self._crawler.cancel()
        self._crawling = False
        self._queue_continue = False  # 阻止队列自动继续
        self._crawl_start_btn.configure(state=tk.NORMAL)
        self._crawl_stop_btn.configure(state=tk.DISABLED)
        self._crawl_log_append("\n[!] 已发送停止信号,等待当前请求完成...\n")

    def _start_benchmark(self, mode: str) -> None:
        """启动基准测试 (quick/medium/overnight)。"""
        try:
            import benchmark
        except ImportError:
            self._crawl_log_append("[X] 无法导入 benchmark.py,请确认文件在项目根目录\n")
            return
        PRESETS = benchmark.PRESETS
        BenchmarkRunner = benchmark.BenchmarkRunner
        if mode not in PRESETS:
            return
        cfg = PRESETS[mode]
        uid = self._crawl_uid_entry.get().strip() or "2"
        self._crawl_log_append(f"\n=== 基准测试: {cfg['label']} ===\n")

        self._crawling = True
        self._crawl_start_btn.configure(state=tk.DISABLED)
        self._crawl_stop_btn.configure(state=tk.NORMAL)

        runner = BenchmarkRunner(duration_min=cfg["duration_min"], uid=uid)
        self._bench_runner = runner

        def _run() -> None:
            import sys, io
            old_stdout = sys.stdout
            log_buffer = io.StringIO()
            gui_log = self._crawl_log_append
            gui_root = self.root

            class _BW:
                def write(self, s):
                    log_buffer.write(s)
                    if s.strip():
                        self.flush()
                def flush(self):
                    t = log_buffer.getvalue()
                    log_buffer.truncate(0); log_buffer.seek(0)
                    if t:
                        gui_root.after(0, lambda x=t: gui_log(x))
            sys.stdout = _BW()
            try:
                report = runner.run()
            except Exception as e:
                self.root.after(0, lambda: gui_log(f"\n[X] 基准测试异常: {e}\n"))
                report = {"error": str(e)}
            finally:
                sys.stdout = old_stdout
            self.root.after(0, lambda r=report: self._bench_done(r))

        threading.Thread(target=_run, daemon=True).start()

        # 启动实时指标轮询
        self._poll_bench_metrics()
        # 开始速率状态轮询
        if not self._crawling:
            self._poll_rate_status()

    def _poll_rate_status(self) -> None:
        """定时刷新速率控制状态显示。"""
        if not self._crawling:
            return
        crawler = self._crawler
        if crawler and hasattr(crawler, '_rate_ctrl'):
            rc = crawler._rate_ctrl
            state = rc.get_state()
            dmin, dmax = rc.get_delay_range()
            total_req = rc._total_requests
            req_rate = rc._compute_current_rate() if hasattr(rc, '_compute_current_rate') else 0
            snooze_info = ""
            if hasattr(rc, '_snooze_locked') and rc._snooze_locked:
                snooze_info = f" 沉睡锁{rc._global_snooze_duration/60:.0f}min"
            elif hasattr(rc, '_snooze_duration'):
                snooze_info = f" 沉睡{rc._snooze_duration/60:.0f}min"
            self._rate_live_var.set(
                f"状态:{state} | {dmin:.1f}~{dmax:.1f}s | {req_rate:.0f}rpm | {total_req}请求{snooze_info}"
            )
        self.root.after(5000, self._poll_rate_status)  # 每5秒刷新

    def _poll_bench_metrics(self) -> None:
        """定时轮询基准测试实时指标。"""
        if not self._crawling:
            return
        runner = getattr(self, "_bench_runner", None)
        if runner:
            m = runner.get_live_metrics()
            if m:
                elapsed = m.get("elapsed_min", 0)
                remaining = m.get("remaining_min", 0)
                req = m.get("req_per_min", 0)
                state = m.get("state", "?")
                self._bench_metrics_var.set(
                    f"{elapsed:.0f}/{elapsed+remaining:.0f}min | {req:.0f}rpm | {state}"
                )
        self.root.after(3000, self._poll_bench_metrics)  # 每3秒刷新

    def _bench_done(self, report: dict) -> None:
        """基准测试完成。"""
        self._crawling = False
        self._crawl_start_btn.configure(state=tk.NORMAL)
        self._crawl_stop_btn.configure(state=tk.DISABLED)
        self._bench_metrics_var.set("完成")

        import benchmark
        import io, sys
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        benchmark.print_report(report)
        sys.stdout = old
        self._crawl_log_append(buf.getvalue())
        self._set_status(f"基准测试完成: {report.get('total_requests',0)}请求")

    def _update_crawl_progress(self, current: int, total: int, label: str):
        """更新进度条和标签。"""
        self._crawl_progress["maximum"] = total
        self._crawl_progress["value"] = current
        self._crawl_progress_label.configure(text=f"视频 {current}/{total}: {label}")

    def _crawl_done(self, msg: str) -> None:
        """爬取完成后更新 UI。"""
        self._crawling = False
        self._crawl_start_btn.configure(state=tk.NORMAL)
        self._crawl_stop_btn.configure(state=tk.DISABLED)
        self._crawl_stats_var.set(msg)
        self._rate_live_var.set("状态: 已停止")
        self._crawl_progress["value"] = self._crawl_progress["maximum"]
        self._crawl_log_append(f"\n=== {msg} ===\n")
        self._set_status("评论爬取 " + msg)
        # 检查待爬队列
        self._try_queue_next()

    def _crawl_log_clear(self) -> None:
        self._crawl_log.configure(state=tk.NORMAL)
        self._crawl_log.delete("1.0", tk.END)
        self._crawl_log.configure(state=tk.DISABLED)

    def _crawl_log_append(self, text: str) -> None:
        self._crawl_log.configure(state=tk.NORMAL)
        self._crawl_log.insert(tk.END, text)
        self._crawl_log.see(tk.END)
        self._crawl_log.configure(state=tk.DISABLED)

    def _try_queue_next(self) -> None:
        """爬取完成后检查待爬队列,若有下一条则自动启动。"""
        if not getattr(self, "_queue_continue", False):
            return
        current = getattr(self, "_current_crawl_uid", None)
        if current:
            self._remove_current_from_queue(current)
        next_uid = self._pop_next_uid()
        if next_uid:
            self._crawl_log_append(f"\n=== 队列中还有 UID={next_uid}, 自动继续... ===\n")
            self._crawl_uid_entry.delete(0, tk.END)
            self._crawl_uid_entry.insert(0, next_uid)
            self.root.after(1000, self._start_crawl)  # 1秒后自动启动

    def _search_comments(self) -> None:
        """双源检索: 本地DB + 在线API 融合查询。"""
        uid = self._search_uid_entry.get().strip()
        if not uid.isdigit():
            self._search_count_var.set("请输入有效UID")
            return

        self._search_count_var.set("查询中...")
        threading.Thread(target=self._do_search_comments, args=(uid,), daemon=True).start()

    def _do_search_comments(self, uid: str) -> None:
        """后台线程: 并行查询本地DB和在线API,融合结果。"""
        import os, sqlite3, time, requests

        # 1. 本地DB查询
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "comments.db")
        local_rows: list[dict] = []
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT rpid,oid,ctime,message,parent FROM comments WHERE mid=? ORDER BY ctime DESC LIMIT 500",
                (int(uid),),
            ).fetchall()
            conn.close()
            for rpid, oid, ctime, msg, parent in rows:
                local_rows.append({"rpid": rpid, "oid": oid, "ctime": ctime,
                                    "message": msg, "parent": parent, "source": "本地"})

        # 2. 在线API查询 (aicu.cc)
        online_rows: list[dict] = []
        online_available = False
        try:
            seen_rpids = {r["rpid"] for r in local_rows}
            for pn in range(1, 6):  # 最多5页
                resp = requests.get("https://api.aicu.cc/api/v3/search/getreply",
                                    params={"uid": uid, "pn": pn, "ps": 100, "mode": 0},
                                    timeout=8)
                if resp.status_code == 502:
                    break
                data = resp.json()
                if data.get("code") != 0:
                    break
                replies = data.get("data", {}).get("replies", [])
                if not replies:
                    break
                online_available = True
                for r in replies:
                    rpid = r.get("rpid")
                    if rpid not in seen_rpids:
                        seen_rpids.add(rpid)
                        online_rows.append({
                            "rpid": rpid, "oid": r.get("oid", 0),
                            "ctime": r.get("ctime", 0),
                            "message": r.get("message", ""),
                            "parent": r.get("parent", 0),
                            "source": "在线",
                        })
                if data.get("data", {}).get("cursor", {}).get("is_end"):
                    break
                time.sleep(0.3)
        except Exception:
            pass  # 在线API不可用,静默fallback

        # 3. 融合: 本地 + 在线去重
        merged = local_rows + online_rows
        merged.sort(key=lambda x: x["ctime"], reverse=True)

        if not merged:
            self.root.after(0, lambda: self._search_count_var.set(f"未找到 UID={uid} 的评论"))
            return

        local_count = len(local_rows)
        online_count = len(online_rows)
        self.root.after(0, lambda: self._search_count_var.set(
            f"本地{local_count} + 在线{online_count} = {len(merged)}条"
        ))
        source_note = f"[本地{local_count}条 + 在线API{f'新增{online_count}条' if online_available else '不可用'}]"
        self.root.after(0, lambda: self._show_comment_table_v2(uid, merged, source_note))

    def _show_comment_table_v2(self, uid: str, rows: list[dict], note: str) -> None:
        """弹出融合结果表格窗口 (含来源列)。"""
        import time
        win = tk.Toplevel(self.root)
        win.title(f"UID={uid} 的评论 ({len(rows)}条) {note}")
        win.geometry("920x520")
        win.configure(bg=_COLOR_CARD)

        # 工具栏
        toolbar = tk.Frame(win, bg=_COLOR_CARD)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(toolbar, text=f"共 {len(rows)} 条评论", font=_FONT_HEADING, bg=_COLOR_CARD).pack(side=tk.LEFT)
        tk.Label(toolbar, text=note, font=("Microsoft YaHei", 8), bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT, padx=10)
        tk.Button(toolbar, text="导出Excel", command=lambda: self._export_to_excel_v2(uid, rows),
                  bg=_COLOR_BILI_BLUE, fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=2, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        copy_btn = tk.Button(toolbar, text="复制选中行", command=lambda: self._copy_selected_rows(tree),
                             bg="#666", fg="white", font=_FONT_BODY,
                             relief=tk.FLAT, padx=12, pady=2, cursor="hand2")
        copy_btn.pack(side=tk.RIGHT, padx=4)

        # 表格
        tree_frame = tk.Frame(win, bg=_COLOR_CARD)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        columns = ("time", "source", "level", "oid", "rpid", "text")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
        tree.heading("time", text="时间")
        tree.heading("source", text="来源")
        tree.heading("level", text="层级")
        tree.heading("oid", text="视频oid")
        tree.heading("rpid", text="rpid")
        tree.heading("text", text="评论内容")
        tree.column("time", width=130, anchor="center")
        tree.column("source", width=50, anchor="center")
        tree.column("level", width=50, anchor="center")
        tree.column("oid", width=110, anchor="center")
        tree.column("rpid", width=110, anchor="center")
        tree.column("text", width=420)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)

        for r in rows:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ctime"]))
            level = "二级" if r["parent"] > 0 else "一级"
            text = str(r["message"])[:100].replace("\n", " ")
            tree.insert("", tk.END, values=(ts, r["source"], level, r["oid"], r["rpid"], text))

        def _on_double_click(event):
            item = tree.selection()
            if item:
                oid = tree.item(item[0], "values")[3]
                import webbrowser
                webbrowser.open(f"https://www.bilibili.com/video/av{oid}")
        tree.bind("<Double-1>", _on_double_click)

        # 右键菜单
        rmenu = tk.Menu(win, tearoff=0)
        rmenu.add_command(label="复制选中行", command=lambda: self._copy_selected_rows(tree))
        rmenu.add_command(label="全选 (Ctrl+A)", command=lambda: tree.selection_set(tree.get_children()))
        def _on_right_click(event):
            try: rmenu.tk_popup(event.x_root, event.y_root)
            finally: rmenu.grab_release()
        tree.bind("<Button-3>", _on_right_click)
        # Ctrl+C 快捷键
        win.bind("<Control-c>", lambda e: self._copy_selected_rows(tree))

    def _copy_selected_rows(self, tree: ttk.Treeview) -> None:
        """复制 Treeview 中选中行的内容到剪贴板。"""
        items = tree.selection()
        if not items:
            return
        lines = []
        for item in items:
            vals = tree.item(item, "values")
            # 格式: 时间 | 来源 | 层级 | oid | rpid | 内容
            lines.append(f"{vals[0]}\t{vals[1]}\t{vals[2]}\t{vals[3]}\t{vals[4]}\t{vals[5]}")
        text = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status(f"已复制 {len(items)} 行到剪贴板")

    def _export_to_excel_v2(self, uid: str, rows: list[dict]) -> None:
        """导出融合结果为 Excel。"""
        from tkinter import filedialog, messagebox
        import time
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel文件", "*.xlsx")],
            initialfile=f"{uid}_评论数据.xlsx")
        if not filepath:
            return
        try:
            import openpyxl; wb = openpyxl.Workbook(); ws = wb.active
            ws.title = f"UID={uid}"; ws.append(["来源","rpid","视频oid","时间","层级","评论内容"])
            for r in rows:
                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ctime"]))
                ws.append([r["source"], r["rpid"], r["oid"], ts,
                           "二级" if r["parent"] > 0 else "一级", str(r["message"])])
            wb.save(filepath); messagebox.showinfo("导出成功", f"已保存到:\n{filepath}")
        except ImportError:
            filepath = filepath.replace(".xlsx", ".csv")
            import csv
            with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f); w.writerow(["来源","rpid","视频oid","时间","层级","评论内容"])
                for r in rows:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ctime"]))
                    w.writerow([r["source"], r["rpid"], r["oid"], ts,
                                "二级" if r["parent"] > 0 else "一级", str(r["message"])])
            messagebox.showinfo("导出成功", f"已保存为CSV:\n{filepath}")

    def _export_to_excel(self, uid: str, rows: list) -> None:
        """将检索结果导出为 Excel 文件。"""
        from tkinter import filedialog, messagebox
        import time, os

        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx")],
            initialfile=f"{uid}_评论数据.xlsx",
        )
        if not filepath:
            return

        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = f"UID={uid}"
            ws.append(["rpid", "视频oid", "时间", "层级", "评论内容"])
            for rpid, oid, ctime, msg, parent in rows:
                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ctime))
                level = "二级" if parent > 0 else "一级"
                ws.append([rpid, oid, ts, level, str(msg)])
            wb.save(filepath)
            messagebox.showinfo("导出成功", f"已保存到:\n{filepath}")
        except ImportError:
            # 回退到 CSV
            filepath = filepath.replace(".xlsx", ".csv")
            import csv
            with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["rpid", "视频oid", "时间", "层级", "评论内容"])
                for rpid, oid, ctime, msg, parent in rows:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ctime))
                    level = "二级" if parent > 0 else "一级"
                    writer.writerow([rpid, oid, ts, level, str(msg)])
            messagebox.showinfo("导出成功", f"已保存为CSV:\n{filepath}")

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
        # 同步到爬取标签页的 UID 输入框和检索 UID
        self._crawl_uid_entry.delete(0, tk.END)
        self._crawl_uid_entry.insert(0, uid_text)
        self._search_uid_entry.delete(0, tk.END)
        self._search_uid_entry.insert(0, uid_text)
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
        """在后台线程中执行用户信息、统计数据和视频列表查询。"""
        import requests

        # ── 公共请求头模板 ──
        base_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://space.bilibili.com/{uid}/",
            "Cookie": cookie,
        }

        # ── 第一步: 获取 WBI 密钥 (只需一次) ──
        try:
            img_key, sub_key = get_wbi_keys()
        except Exception as e:
            self.root.after(0, lambda: self._show_error(f"获取 WBI 密钥失败: {e}"))
            return

        # ── 第二步: 并行请求四个接口 ──
        # 接口1: 用户基本信息
        info_result = None
        try:
            signed = enc_wbi({"mid": uid}, img_key=img_key, sub_key=sub_key)
            resp = requests.get(
                "https://api.bilibili.com/x/space/wbi/acc/info",
                params=signed, headers=base_headers, timeout=10,
            )
            resp.raise_for_status()
            info_result = resp.json()
        except Exception:
            pass

        # 接口2: 关注/粉丝数统计
        stat_result = None
        try:
            signed_s = enc_wbi({"vmid": uid}, img_key=img_key, sub_key=sub_key)
            resp = requests.get(
                "https://api.bilibili.com/x/relation/stat",
                params=signed_s, headers=base_headers, timeout=10,
            )
            resp.raise_for_status()
            stat_result = resp.json()
        except Exception:
            pass

        # 接口3: 获赞/播放量统计
        upstat_result = None
        try:
            signed_u = enc_wbi({"mid": uid}, img_key=img_key, sub_key=sub_key)
            resp = requests.get(
                "https://api.bilibili.com/x/space/upstat",
                params=signed_u, headers=base_headers, timeout=10,
            )
            resp.raise_for_status()
            upstat_result = resp.json()
        except Exception:
            pass

        # 接口4: 视频列表
        video_result = None
        try:
            video_params = enc_wbi({
                "mid": uid, "ps": 30, "tid": 0, "pn": 1,
                "keyword": "", "order": "pubdate", "platform": "web",
                "web_location": 1550101, "order_avoided": "true",
            }, img_key=img_key, sub_key=sub_key)
            video_headers = dict(base_headers, Referer=f"https://space.bilibili.com/{uid}/video")
            resp = requests.get(
                "https://api.bilibili.com/x/space/wbi/arc/search",
                params=video_params, headers=video_headers, timeout=15,
            )
            resp.raise_for_status()
            video_result = resp.json()
        except Exception:
            pass

        # 任何接口都没拿到数据则报错
        if info_result is None and stat_result is None:
            self.root.after(0, lambda: self._show_error("查询失败: 网络异常或 Cookie 失效"))
            return

        self.root.after(
            0, lambda: self._display_results(
                uid, info_result, stat_result, upstat_result, video_result,
            )
        )

    def _display_results(
        self, uid: str,
        info: Optional[dict],
        stat: Optional[dict],
        upstat: Optional[dict],
        video: Optional[dict],
    ) -> None:
        """
        在主线程中展示查询结果。

        数据来源:
          info  — /x/space/wbi/acc/info   (用户名/等级/性别/签名/生日)
          stat  — /x/relation/stat        (粉丝数/关注数)
          upstat — /x/space/upstat         (获赞数/总播放量)
          video — /x/space/wbi/arc/search  (视频列表)
        """
        self._query_btn.configure(state=tk.NORMAL, text="🔍 查询")

        # ── 用户信息展示 ──
        if info and info.get("code") == 0:
            data = info["data"]

            # 从 stat 接口提取粉丝/关注数
            follower_num = 0
            following_num = 0
            if stat and stat.get("code") == 0:
                sd = stat["data"]
                follower_num = sd.get("follower", 0)
                following_num = sd.get("following", 0)

            # 从 upstat 接口提取获赞数/播放量
            likes_num = 0
            total_views = 0
            if upstat and upstat.get("code") == 0:
                ud = upstat["data"]
                likes_num = ud.get("likes", 0)
                archive = ud.get("archive", {})
                total_views = archive.get("view", 0) if isinstance(archive, dict) else 0

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
                f"  粉丝数   : {follower_num:,}",
                f"  关注数   : {following_num:,}",
                f"  获赞数   : {likes_num:,}",
                f"  总播放量 : {total_views:,}",
                "",
            ]
        else:
            lines = [
                f"❌ 查询失败: {info.get('message', '网络异常') if info else '无响应'}",
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
