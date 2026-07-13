"""
B站数据爬取工具 —— Tkinter 图形化界面。

功能:
  - 扫码登录 / Cookie 状态显示
  - 通过 UID 查询用户主页信息和视频列表
  - 评论爬取、队列管理、速率控制、基准测试
  - 数据协作：导出/导入/校验/统计
  - 本地 + 在线评论检索

用法:
    python gui.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

from .login import (
    get_cookie_string,
    is_logged_in,
    qr_login,
)
from .comment_crawler import CommentCrawler
from .dataset_tools import (
    export_comments as ds_export,
    import_jsonl as ds_import,
    validate_jsonl_files as ds_validate,
    get_db_stats as ds_get_stats,
    quick_validate,
    COMMENT_COLUMNS,
)
from .paths import CONFIG_PATH, CRAWL_QUEUE_PATH, COMMENTS_DB_PATH, ensure_data_dir
from .wbi import enc_wbi, get_wbi_keys

# ─── 颜色 / 字体常量 ─────────────────────────────────────────

_COLOR_BILI_PINK = "#fb7299"
_COLOR_BILI_BLUE = "#00a1d6"
_COLOR_BG = "#f0f2f5"
_COLOR_CARD = "#ffffff"
_COLOR_DARK_BG = "#1e1e1e"
_COLOR_DARK_FG = "#d4d4d4"
_COLOR_SUCCESS = "#52c41a"
_COLOR_DANGER = "#ff4d4f"
_COLOR_WARN = "#faad14"
_COLOR_BTN_PRIMARY = "#1890ff"
_COLOR_BTN_DANGER = "#ff4d4f"
_COLOR_BTN_NORMAL = "#595959"
_FONT_TITLE = ("Microsoft YaHei", 14, "bold")
_FONT_HEADING = ("Microsoft YaHei", 11, "bold")
_FONT_BODY = ("Microsoft YaHei", 10)
_FONT_SMALL = ("Microsoft YaHei", 9)
_FONT_MONO = ("Consolas", 10)


# ─── 按钮样式辅助 ──────────────────────────────────────────

def _btn_primary(parent, text, command, **kw):
    return tk.Button(parent, text=text, command=command,
                     bg=_COLOR_BTN_PRIMARY, fg="white", font=_FONT_BODY,
                     cursor="hand2", relief=tk.FLAT, padx=16, pady=4, **kw)

def _btn_danger(parent, text, command, **kw):
    return tk.Button(parent, text=text, command=command,
                     bg=_COLOR_BTN_DANGER, fg="white", font=_FONT_BODY,
                     cursor="hand2", relief=tk.FLAT, padx=16, pady=4, **kw)

def _btn_normal(parent, text, command, **kw):
    return tk.Button(parent, text=text, command=command,
                     bg=_COLOR_BTN_NORMAL, fg="white", font=_FONT_BODY,
                     cursor="hand2", relief=tk.FLAT, padx=12, pady=4, **kw)


class BiliSpiderGUI:
    """B站爬取工具主窗口。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BiliSpider - B站数据查询与协作工具")
        self.root.geometry("1120x760")
        self.root.minsize(960, 640)
        self.root.configure(bg=_COLOR_BG)

        # 状态
        self._logged_in = False
        self._username: Optional[str] = None
        self._uid: Optional[int] = None
        self._qr_window: Optional[tk.Toplevel] = None
        self._qr_login_active = False
        self._qr_cancel_event: Optional[threading.Event] = None

        # 评论爬取状态
        self._crawler: Optional[CommentCrawler] = None
        self._crawling = False
        self._bench_runner = None
        self._current_crawl_uid: Optional[str] = None
        self._queue_continue = False

        # UI 变量
        self._login_status_var = tk.StringVar(value="未登录")
        self._db_status_var = tk.StringVar(value="")
        self._status_bar_var = tk.StringVar(value="就绪")

        self._config_path = str(CONFIG_PATH)

        self._build_ui()
        self._load_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._check_login_on_start()
        self._refresh_db_status()

    # ─── 配置持久化 ─────────────────────────────────────────────

    def _load_config(self) -> None:
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}

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
        self._rate_base_var.set(cfg.get("rate_base", "1.5"))
        self._rate_jitter_var.set(cfg.get("rate_jitter", "1.0"))
        self._snooze_var.set(cfg.get("snooze", "10"))
        self._auto_tune_var.set(cfg.get("auto_tune", False))
        self._auto_snooze_var.set(cfg.get("auto_snooze", True))
        # 数据协作配置
        self._collab_uid_entry.delete(0, tk.END)
        self._collab_uid_entry.insert(0, cfg.get("collab_uid", "2"))
        self._collab_dir_var.set(cfg.get("collab_dir", "datasets"))
        self._collab_contributor_entry.delete(0, tk.END)
        self._collab_contributor_entry.insert(0, cfg.get("contributor", ""))

    def _save_config(self) -> None:
        cfg = {
            "query_uid": self._uid_entry.get().strip(),
            "crawl_uid": self._crawl_uid_entry.get().strip(),
            "crawl_days": self._crawl_days_var.get(),
            "crawl_max": self._crawl_max_var.get(),
            "proxy": self._crawl_proxy_entry.get().strip(),
            "search_uid": self._search_uid_entry.get().strip(),
            "rate_base": self._rate_base_var.get(),
            "rate_jitter": self._rate_jitter_var.get(),
            "snooze": self._snooze_var.get(),
            "auto_tune": self._auto_tune_var.get(),
            "auto_snooze": self._auto_snooze_var.get(),
            "collab_uid": self._collab_uid_entry.get().strip(),
            "collab_dir": self._collab_dir_var.get(),
            "contributor": self._collab_contributor_entry.get().strip(),
        }
        try:
            ensure_data_dir()
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self) -> None:
        self._save_config()
        self.root.destroy()

    # ─── 待爬队列 ───────────────────────────────────────────────

    @property
    def _queue_path(self) -> str:
        return str(CRAWL_QUEUE_PATH)

    def _load_queue(self) -> list[str]:
        try:
            with open(self._queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_queue(self, uids: list[str]) -> None:
        ensure_data_dir()
        with open(self._queue_path, "w", encoding="utf-8") as f:
            json.dump(uids, f, ensure_ascii=False)

    def _add_to_queue(self) -> None:
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
        queue = self._load_queue()
        return queue[0] if queue else None

    def _remove_current_from_queue(self, uid: str) -> None:
        queue = self._load_queue()
        if uid in queue:
            queue.remove(uid)
            self._save_queue(queue)
        self._refresh_queue_display()

    def _refresh_queue_display(self) -> None:
        queue = self._load_queue()
        if queue:
            self._queue_var.set(f"队列({len(queue)}): {' → '.join(queue[:5])}" + ("..." if len(queue) > 5 else ""))
        else:
            self._queue_var.set("队列: (空)")

    # ─── UI 构建 ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_status_header()
        self._build_notebook()
        self._build_status_bar()

    # ─── 顶部紧凑状态栏 ────────────────────────────────────────

    def _build_status_header(self) -> None:
        bar = tk.Frame(self.root, bg=_COLOR_CARD, height=40)
        bar.pack(fill=tk.X, padx=12, pady=(10, 4))
        bar.pack_propagate(False)

        # 左: 标题
        tk.Label(bar, text="BiliSpider", font=_FONT_TITLE,
                 bg=_COLOR_CARD, fg=_COLOR_BILI_PINK).pack(side=tk.LEFT, padx=(8, 20))

        # 中: 登录状态 + DB状态
        status_frame = tk.Frame(bar, bg=_COLOR_CARD)
        status_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(status_frame, textvariable=self._login_status_var,
                 font=_FONT_SMALL, bg=_COLOR_CARD, fg="#333").pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(status_frame, textvariable=self._db_status_var,
                 font=_FONT_SMALL, bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT)

        # 右: 按钮
        btn_frame = tk.Frame(bar, bg=_COLOR_CARD)
        btn_frame.pack(side=tk.RIGHT)
        self._login_btn = tk.Button(btn_frame, text="🔐 扫码登录", command=self._start_qr_login,
                                     bg=_COLOR_BILI_PINK, fg="white", font=_FONT_SMALL,
                                     cursor="hand2", relief=tk.FLAT, padx=12, pady=2)
        self._login_btn.pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(btn_frame, text="🔄", command=self._check_login,
                  bg=_COLOR_BILI_BLUE, fg="white", font=_FONT_SMALL,
                  cursor="hand2", relief=tk.FLAT, padx=8, pady=2).pack(side=tk.RIGHT, padx=4)

    # ─── Notebook 主容器 ──────────────────────────────────────

    def _build_notebook(self) -> None:
        nb_frame = tk.Frame(self.root, bg=_COLOR_BG)
        nb_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 4))

        self._notebook = ttk.Notebook(nb_frame)

        # 标签1: 用户查询
        self._query_tab = tk.Frame(self._notebook, bg=_COLOR_CARD)
        self._build_query_tab()
        self._notebook.add(self._query_tab, text="  用户查询  ")

        # 标签2: 评论爬取
        self._crawl_tab = tk.Frame(self._notebook, bg=_COLOR_CARD)
        self._build_crawl_tab()
        self._notebook.add(self._crawl_tab, text="  评论爬取  ")

        # 标签3: 数据协作 (NEW)
        self._collab_tab = tk.Frame(self._notebook, bg=_COLOR_CARD)
        self._build_collab_tab()
        self._notebook.add(self._collab_tab, text="  数据协作  ")

        # 标签4: 本地检索
        self._search_tab = tk.Frame(self._notebook, bg=_COLOR_CARD)
        self._build_search_tab()
        self._notebook.add(self._search_tab, text="  本地检索  ")

        self._notebook.pack(fill=tk.BOTH, expand=True)

    # ─── 标签1: 用户查询 ───────────────────────────────────────

    def _build_query_tab(self) -> None:
        # 查询输入行
        input_row = tk.Frame(self._query_tab, bg=_COLOR_CARD)
        input_row.pack(fill=tk.X, padx=10, pady=(10, 6))
        tk.Label(input_row, text="目标 UID:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(0, 6))
        self._uid_entry = tk.Entry(input_row, font=_FONT_BODY, width=20)
        self._uid_entry.pack(side=tk.LEFT, padx=(0, 8))
        self._uid_entry.bind("<Return>", lambda _e: self._query_user())
        self._uid_entry.insert(0, "2")
        _btn_primary(input_row, "🔍 查询", self._query_user).pack(side=tk.LEFT)

        # 结果区 (左右分栏: 用户信息 + 视频列表)
        paned = tk.PanedWindow(self._query_tab, orient=tk.HORIZONTAL,
                               bg=_COLOR_BG, sashwidth=3)
        paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 6))

        left = tk.Frame(paned, bg=_COLOR_CARD)
        tk.Label(left, text="用户信息", font=_FONT_HEADING, bg=_COLOR_CARD,
                 fg=_COLOR_BILI_PINK).pack(anchor=tk.W, padx=4, pady=(2, 0))
        self._info_text = scrolledtext.ScrolledText(
            left, font=_FONT_MONO, wrap=tk.WORD, state=tk.DISABLED,
            bg=_COLOR_CARD, relief=tk.FLAT)
        self._info_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        paned.add(left, stretch="always")

        right = tk.Frame(paned, bg=_COLOR_CARD)
        tk.Label(right, text="视频列表", font=_FONT_HEADING, bg=_COLOR_CARD,
                 fg=_COLOR_BILI_BLUE).pack(anchor=tk.W, padx=4, pady=(2, 0))
        self._video_text = scrolledtext.ScrolledText(
            right, font=_FONT_MONO, wrap=tk.WORD, state=tk.DISABLED,
            bg=_COLOR_CARD, relief=tk.FLAT)
        self._video_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        paned.add(right, stretch="always")

    # ─── 标签2: 评论爬取 ───────────────────────────────────────

    def _build_crawl_tab(self) -> None:
        # 参数区
        param_frame = tk.LabelFrame(self._crawl_tab, text="爬取参数", font=_FONT_HEADING,
                                     bg=_COLOR_CARD, padx=8, pady=6)
        param_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        row1 = tk.Frame(param_frame, bg=_COLOR_CARD)
        row1.pack(fill=tk.X, pady=(0, 4))
        tk.Label(row1, text="UP主UID:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._crawl_uid_entry = tk.Entry(row1, font=_FONT_BODY, width=16)
        self._crawl_uid_entry.pack(side=tk.LEFT, padx=6)
        self._crawl_uid_entry.insert(0, "2")

        tk.Label(row1, text="天数:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(12, 0))
        self._crawl_days_var = tk.StringVar(value="30")
        tk.Spinbox(row1, textvariable=self._crawl_days_var, from_=1, to=365,
                   width=5, font=_FONT_BODY).pack(side=tk.LEFT, padx=4)

        tk.Label(row1, text="最大视频:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(12, 0))
        self._crawl_max_var = tk.StringVar(value="5")
        tk.Spinbox(row1, textvariable=self._crawl_max_var, from_=1, to=500,
                   width=5, font=_FONT_BODY).pack(side=tk.LEFT, padx=4)

        tk.Label(row1, text="代理:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(12, 0))
        self._crawl_proxy_entry = tk.Entry(row1, font=_FONT_BODY, width=24)
        self._crawl_proxy_entry.pack(side=tk.LEFT, padx=6)

        # 控制按钮 + 队列
        ctrl_row = tk.Frame(param_frame, bg=_COLOR_CARD)
        ctrl_row.pack(fill=tk.X)
        self._crawl_start_btn = _btn_primary(ctrl_row, "▶ 开始爬取", self._start_crawl)
        self._crawl_start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._crawl_stop_btn = _btn_danger(ctrl_row, "⏹ 停止", self._stop_crawl)
        self._crawl_stop_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._crawl_stop_btn.configure(state=tk.DISABLED)

        _btn_normal(ctrl_row, "+ 加入队列", self._add_to_queue).pack(side=tk.LEFT, padx=4)
        _btn_normal(ctrl_row, "清空队列", self._clear_queue).pack(side=tk.LEFT, padx=4)

        self._queue_var = tk.StringVar(value="队列: (空)")
        tk.Label(ctrl_row, textvariable=self._queue_var,
                 font=_FONT_SMALL, bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT, padx=12)

        self._crawl_stats_var = tk.StringVar(value="")
        tk.Label(ctrl_row, textvariable=self._crawl_stats_var,
                 font=_FONT_SMALL, bg=_COLOR_CARD, fg=_COLOR_BILI_BLUE).pack(side=tk.RIGHT)

        # 进度区
        prog_frame = tk.Frame(self._crawl_tab, bg=_COLOR_CARD)
        prog_frame.pack(fill=tk.X, padx=8, pady=(2, 0))
        self._crawl_progress = ttk.Progressbar(prog_frame, mode="determinate")
        self._crawl_progress.pack(fill=tk.X, side=tk.LEFT, expand=True)
        self._crawl_progress_label = tk.Label(prog_frame, text="", font=_FONT_SMALL,
                                               bg=_COLOR_CARD, fg="#888", width=40, anchor=tk.W)
        self._crawl_progress_label.pack(side=tk.LEFT, padx=8)

        # 速率控制 (折叠)
        self._rate_frame = tk.LabelFrame(self._crawl_tab, text="速率控制", font=_FONT_SMALL,
                                          bg=_COLOR_CARD, padx=6, pady=4)
        rr = tk.Frame(self._rate_frame, bg=_COLOR_CARD)
        rr.pack(fill=tk.X)
        tk.Label(rr, text="基础延迟(s):", font=_FONT_SMALL, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._rate_base_var = tk.StringVar(value="1.5")
        tk.Spinbox(rr, textvariable=self._rate_base_var, from_=0.5, to=60, increment=0.5,
                   width=5, font=_FONT_SMALL).pack(side=tk.LEFT, padx=4)
        tk.Label(rr, text="抖动(s):", font=_FONT_SMALL, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(8, 0))
        self._rate_jitter_var = tk.StringVar(value="1.0")
        tk.Spinbox(rr, textvariable=self._rate_jitter_var, from_=0.3, to=30, increment=0.3,
                   width=5, font=_FONT_SMALL).pack(side=tk.LEFT, padx=4)
        tk.Label(rr, text="沉睡(min):", font=_FONT_SMALL, bg=_COLOR_CARD).pack(side=tk.LEFT, padx=(8, 0))
        self._snooze_var = tk.StringVar(value="10")
        tk.Spinbox(rr, textvariable=self._snooze_var, from_=1, to=120, increment=1,
                   width=5, font=_FONT_SMALL).pack(side=tk.LEFT, padx=4)
        self._auto_tune_var = tk.BooleanVar(value=True)
        tk.Checkbutton(rr, text="自适应提速", variable=self._auto_tune_var,
                       bg=_COLOR_CARD, font=_FONT_SMALL).pack(side=tk.LEFT, padx=(8, 2))
        self._auto_snooze_var = tk.BooleanVar(value=True)
        tk.Checkbutton(rr, text="自适应沉睡", variable=self._auto_snooze_var,
                       bg=_COLOR_CARD, font=_FONT_SMALL).pack(side=tk.LEFT, padx=2)
        self._rate_live_var = tk.StringVar(value="状态: --")
        tk.Label(rr, textvariable=self._rate_live_var,
                 font=_FONT_SMALL, bg=_COLOR_CARD, fg="#888").pack(side=tk.RIGHT, padx=6)

        # 日志区
        self._crawl_log = scrolledtext.ScrolledText(
            self._crawl_tab, font=_FONT_MONO, wrap=tk.WORD,
            state=tk.DISABLED, bg=_COLOR_DARK_BG, fg=_COLOR_DARK_FG,
            relief=tk.FLAT, insertbackground="white",
        )
        self._crawl_log.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 6))

    # ─── 标签3: 数据协作 (NEW) ─────────────────────────────────

    def _build_collab_tab(self) -> None:
        """数据协作标签页：导出 / 导入 / 校验 / 统计。"""
        # 顶部按钮行
        toolbar = tk.Frame(self._collab_tab, bg=_COLOR_CARD)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 4))

        _btn_primary(toolbar, "📤 导出全部", lambda: self._collab_export(all_mode=True)).pack(side=tk.LEFT, padx=2)
        _btn_primary(toolbar, "📤 按UID导出", lambda: self._collab_export(all_mode=False)).pack(side=tk.LEFT, padx=2)
        _btn_primary(toolbar, "📤 拆分导出", self._collab_split_export).pack(side=tk.LEFT, padx=2)
        _btn_normal(toolbar, "📥 导入JSONL", self._collab_import).pack(side=tk.LEFT, padx=2)
        _btn_normal(toolbar, "🔍 校验JSONL", self._collab_validate).pack(side=tk.LEFT, padx=2)
        _btn_normal(toolbar, "📊 数据库统计", self._collab_stats).pack(side=tk.LEFT, padx=2)

        # 参数行
        param_row = tk.Frame(self._collab_tab, bg=_COLOR_CARD)
        param_row.pack(fill=tk.X, padx=8, pady=(2, 4))

        tk.Label(param_row, text="UID:", font=_FONT_SMALL, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._collab_uid_entry = tk.Entry(param_row, font=_FONT_SMALL, width=14)
        self._collab_uid_entry.pack(side=tk.LEFT, padx=(2, 10))
        self._collab_uid_entry.insert(0, "2")

        tk.Label(param_row, text="导出目录:", font=_FONT_SMALL, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._collab_dir_var = tk.StringVar(value="datasets")
        tk.Entry(param_row, textvariable=self._collab_dir_var,
                 font=_FONT_SMALL, width=16).pack(side=tk.LEFT, padx=(2, 10))

        tk.Label(param_row, text="贡献者:", font=_FONT_SMALL, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._collab_contributor_entry = tk.Entry(param_row, font=_FONT_SMALL, width=12)
        self._collab_contributor_entry.pack(side=tk.LEFT, padx=2)

        # 结果区
        self._collab_result = scrolledtext.ScrolledText(
            self._collab_tab, font=_FONT_MONO, wrap=tk.WORD,
            state=tk.DISABLED, bg=_COLOR_CARD, relief=tk.FLAT,
        )
        self._collab_result.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 6))

    # ─── 标签4: 本地检索 ───────────────────────────────────────

    def _build_search_tab(self) -> None:
        search_row = tk.Frame(self._search_tab, bg=_COLOR_CARD)
        search_row.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(search_row, text="检索评论 (UID):", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT)
        self._search_uid_entry = tk.Entry(search_row, font=_FONT_BODY, width=18)
        self._search_uid_entry.pack(side=tk.LEFT, padx=6)
        self._search_uid_entry.bind("<Return>", lambda _e: self._search_comments())
        _btn_primary(search_row, "搜索", self._search_comments).pack(side=tk.LEFT, padx=4)

        self._search_count_var = tk.StringVar(value="")
        tk.Label(search_row, textvariable=self._search_count_var,
                 font=_FONT_SMALL, bg=_COLOR_CARD, fg="#888").pack(side=tk.RIGHT)

        self._search_result = scrolledtext.ScrolledText(
            self._search_tab, font=_FONT_MONO, wrap=tk.WORD,
            state=tk.DISABLED, bg=_COLOR_CARD, relief=tk.FLAT,
        )
        self._search_result.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 6))

    # ─── 底部状态栏 ────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self.root, bg="#e0e0e0", height=22)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)
        tk.Label(bar, textvariable=self._status_bar_var,
                 font=_FONT_SMALL, bg="#e0e0e0", fg="#666",
                 anchor=tk.W).pack(fill=tk.X, padx=10, pady=1)

    # ─── DB 状态刷新 ───────────────────────────────────────────

    def _refresh_db_status(self) -> None:
        """后台刷新数据库统计状态。"""
        def _run():
            stats = ds_get_stats()
            if stats["success"]:
                total = stats["total"]
                last = stats.get("last_crawl")
                last_str = ""
                if last:
                    last_str = datetime.fromtimestamp(last).strftime("%m-%d %H:%M")
                text = f"📦 {total:,} 条评论"
                if last_str:
                    text += f" | 最近: {last_str}"
                self.root.after(0, lambda: self._db_status_var.set(text))
        threading.Thread(target=_run, daemon=True).start()

    # ─── 登录逻辑 ───────────────────────────────────────────────

    def _check_login_on_start(self) -> None:
        self.root.after(200, self._check_login)

    def _check_login(self) -> None:
        def _do():
            logged_in, username, uid = is_logged_in()
            self.root.after(0, lambda: self._update_login_ui(logged_in, username, uid))
        threading.Thread(target=_do, daemon=True).start()

    def _update_login_ui(self, logged_in: bool, username: Optional[str], uid: Optional[int]) -> None:
        self._logged_in = logged_in
        self._username = username
        self._uid = uid
        if logged_in and username:
            self._login_status_var.set(f"✅ {username} (UID:{uid})")
            self._login_btn.configure(text="🔄 重新登录")
        else:
            self._login_status_var.set("❌ 未登录")
            self._login_btn.configure(text="🔐 扫码登录")

    def _start_qr_login(self) -> None:
        if self._qr_login_active:
            return
        self._qr_login_active = True
        self._set_status("正在生成登录二维码...")

        self._qr_window = tk.Toplevel(self.root)
        self._qr_window.title("扫码登录")
        self._qr_window.geometry("420x520")
        self._qr_window.configure(bg=_COLOR_CARD)
        self._qr_window.resizable(False, False)
        self._qr_window.protocol("WM_DELETE_WINDOW", self._cancel_qr_login)

        tk.Label(self._qr_window, text="请使用哔哩哔哩 App 扫码登录",
                 font=_FONT_HEADING, bg=_COLOR_CARD, fg="#333").pack(pady=(16, 8))
        self._qr_url_var = tk.StringVar(value="正在生成...")
        tk.Label(self._qr_window, textvariable=self._qr_url_var,
                 font=("Microsoft YaHei", 8), bg=_COLOR_CARD, fg="#888",
                 wraplength=380).pack(padx=16, pady=(0, 8))
        self._qr_status_var = tk.StringVar(value="⏳ 正在生成二维码...")
        tk.Label(self._qr_window, textvariable=self._qr_status_var,
                 font=_FONT_BODY, bg=_COLOR_CARD, fg=_COLOR_BILI_BLUE).pack(pady=(0, 8))
        tk.Button(self._qr_window, text="取消登录", command=self._cancel_qr_login,
                  bg="#e0e0e0", fg="#333", font=_FONT_BODY,
                  cursor="hand2", relief=tk.FLAT, padx=20, pady=4).pack(pady=(0, 16))

        cancel_event = threading.Event()
        self._qr_cancel_event = cancel_event

        def _status_callback(msg: str):
            if msg.startswith("__QRCODE_URL__:"):
                url = msg[len("__QRCODE_URL__:"):]
                self.root.after(0, lambda: self._qr_url_var.set(url))
            elif "扫描" in msg or "扫码" in msg or "确认" in msg:
                self.root.after(0, lambda: self._qr_status_var.set(f"📱 {msg}"))
            elif "成功" in msg:
                self.root.after(0, lambda: self._on_qr_success(msg))
            elif "过期" in msg or "取消" in msg or "失败" in msg:
                self.root.after(0, lambda: self._on_qr_failure(msg))

        def _login_thread():
            try:
                qr_login(status_callback=_status_callback, cancel_event=cancel_event)
            except Exception as e:
                self.root.after(0, lambda: self._on_qr_failure(f"登录异常: {e}"))

        threading.Thread(target=_login_thread, daemon=True).start()

    def _on_qr_success(self, msg: str) -> None:
        self._qr_status_var.set(f"✅ {msg}")
        self._qr_login_active = False
        if self._qr_window:
            self._qr_window.after(800, self._qr_window.destroy)
            self._qr_window = None
        self._set_status("登录成功")
        self._check_login()

    def _on_qr_failure(self, msg: str) -> None:
        self._qr_status_var.set(f"❌ {msg}")
        self._qr_login_active = False
        self._set_status(msg)
        if self._qr_window:
            self._qr_window.title("扫码登录 — 失败")

    def _cancel_qr_login(self) -> None:
        if self._qr_cancel_event:
            self._qr_cancel_event.set()
        self._qr_login_active = False
        self._set_status("已取消扫码登录")
        if self._qr_window:
            self._qr_window.destroy()
            self._qr_window = None

    # ─── 查询逻辑 ───────────────────────────────────────────────

    def _query_user(self) -> None:
        uid_text = self._uid_entry.get().strip()
        self._crawl_uid_entry.delete(0, tk.END)
        self._crawl_uid_entry.insert(0, uid_text)
        self._search_uid_entry.delete(0, tk.END)
        self._search_uid_entry.insert(0, uid_text)
        if not uid_text or not uid_text.isdigit():
            messagebox.showwarning("提示", "请输入有效的用户 UID")
            return
        cookie = get_cookie_string()
        if not cookie:
            messagebox.showwarning("提示", "请先扫码登录后再查询")
            return
        self._set_status(f"正在查询 UID={uid_text}...")
        self._clear_result()
        threading.Thread(target=self._do_query, args=(uid_text, cookie), daemon=True).start()

    def _do_query(self, uid: str, cookie: str) -> None:
        import requests
        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
            "Referer": f"https://space.bilibili.com/{uid}/",
            "Cookie": cookie,
        }
        try:
            img_key, sub_key = get_wbi_keys()
        except Exception as e:
            self.root.after(0, lambda: self._show_error(f"获取 WBI 密钥失败: {e}"))
            return

        # 四个接口
        info_result = stat_result = upstat_result = video_result = None
        try:
            resp = requests.get("https://api.bilibili.com/x/space/wbi/acc/info",
                                params=enc_wbi({"mid": uid}, img_key, sub_key),
                                headers=base_headers, timeout=10)
            resp.raise_for_status(); info_result = resp.json()
        except Exception: pass
        try:
            resp = requests.get("https://api.bilibili.com/x/relation/stat",
                                params=enc_wbi({"vmid": uid}, img_key, sub_key),
                                headers=base_headers, timeout=10)
            resp.raise_for_status(); stat_result = resp.json()
        except Exception: pass
        try:
            resp = requests.get("https://api.bilibili.com/x/space/upstat",
                                params=enc_wbi({"mid": uid}, img_key, sub_key),
                                headers=base_headers, timeout=10)
            resp.raise_for_status(); upstat_result = resp.json()
        except Exception: pass
        try:
            vp = enc_wbi({"mid": uid, "ps": 30, "tid": 0, "pn": 1, "keyword": "",
                          "order": "pubdate", "platform": "web", "web_location": 1550101,
                          "order_avoided": "true"}, img_key, sub_key)
            resp = requests.get("https://api.bilibili.com/x/space/wbi/arc/search",
                                params=vp, headers=dict(base_headers, Referer=f"https://space.bilibili.com/{uid}/video"),
                                timeout=15)
            resp.raise_for_status(); video_result = resp.json()
        except Exception: pass

        if info_result is None and stat_result is None:
            self.root.after(0, lambda: self._show_error("查询失败: 网络异常或 Cookie 失效"))
            return

        self.root.after(0, lambda: self._display_results(uid, info_result, stat_result, upstat_result, video_result))

    def _display_results(self, uid, info, stat, upstat, video) -> None:
        if info and info.get("code") == 0:
            data = info["data"]
            follower = following = likes = views = 0
            if stat and stat.get("code") == 0:
                sd = stat["data"]; follower = sd.get("follower", 0); following = sd.get("following", 0)
            if upstat and upstat.get("code") == 0:
                ud = upstat["data"]; likes = ud.get("likes", 0)
                arch = ud.get("archive", {})
                views = arch.get("view", 0) if isinstance(arch, dict) else 0
            lines = ["═" * 50, f"  用户信息 (UID: {uid})", "═" * 50,
                     f"  用户名   : {data.get('name', 'N/A')}",
                     f"  UID      : {data.get('mid', 'N/A')}",
                     f"  等级     : LV{data.get('level', '?')}",
                     f"  性别     : {data.get('sex', 'N/A')}",
                     f"  签名     : {data.get('sign', '')}",
                     f"  生日     : {data.get('birthday', 'N/A')}",
                     f"  粉丝数   : {follower:,}",
                     f"  关注数   : {following:,}",
                     f"  获赞数   : {likes:,}",
                     f"  总播放量 : {views:,}", ""]
        else:
            msg = info.get("message", "网络异常") if info else "无响应"
            lines = [f"❌ 查询失败: {msg}", ""]
        self._info_text.configure(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)
        self._info_text.insert(tk.END, "\n".join(lines))
        self._info_text.configure(state=tk.DISABLED)

        if video and video.get("code") == 0:
            vdata = video["data"]; vlist = vdata["list"]["vlist"]
            vlines = ["═" * 60, f"  视频列表 — 共 {vdata['page']['count']} 个，本页 {len(vlist)} 个", "═" * 60, ""]
            for idx, v in enumerate(vlist, 1):
                vlines.append(f"  {idx:2d}. {v['title'][:42]:42s} BVID:{v['bvid']:12s} 播放:{v['play']:,}")
        elif video:
            vlines = [f"❌ 视频列表获取失败: {video.get('message', '')}"]
        else:
            vlines = ["⚠️ 视频列表获取失败 (网络异常)", ""]
        self._video_text.configure(state=tk.NORMAL)
        self._video_text.delete("1.0", tk.END)
        self._video_text.insert(tk.END, "\n".join(vlines))
        self._video_text.configure(state=tk.DISABLED)
        self._set_status(f"查询完成 — UID={uid}")

    def _show_error(self, msg: str) -> None:
        self._info_text.configure(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)
        self._info_text.insert(tk.END, f"❌ {msg}\n")
        self._info_text.configure(state=tk.DISABLED)
        self._set_status(msg)

    def _clear_result(self) -> None:
        for w in (self._info_text, self._video_text):
            w.configure(state=tk.NORMAL); w.delete("1.0", tk.END); w.configure(state=tk.DISABLED)

    # ─── 评论爬取逻辑 ───────────────────────────────────────────

    def _start_crawl(self) -> None:
        if self._crawling:
            return
        uid = self._crawl_uid_entry.get().strip()
        if not uid.isdigit():
            queue = self._load_queue()
            if queue:
                uid = queue[0]
                self._crawl_uid_entry.delete(0, tk.END)
                self._crawl_uid_entry.insert(0, uid)
            else:
                messagebox.showwarning("提示", "请输入有效的 UID 或添加 UID 到待爬队列")
                return
        self._queue_continue = True
        self._current_crawl_uid = uid
        days = int(self._crawl_days_var.get() or 30)
        max_videos = int(self._crawl_max_var.get() or 5)
        proxy = self._crawl_proxy_entry.get().strip()
        since_ts = int(time.time() - days * 86400) if days > 0 else 0
        proxies = [p.strip() for p in proxy.split(",") if p.strip()] if proxy else []

        self._crawling = True
        self._crawl_start_btn.configure(state=tk.DISABLED)
        self._crawl_stop_btn.configure(state=tk.NORMAL)
        self._crawl_stats_var.set("正在初始化...")
        self._crawl_progress["value"] = 0
        self._crawl_progress_label.configure(text="")
        self._crawl_log_clear()
        self._crawl_log_append(f"=== 开始爬取 UID={uid} ===\n")
        if days: self._crawl_log_append(f"时间范围: 最近 {days} 天\n")
        if max_videos: self._crawl_log_append(f"视频限制: 最多 {max_videos} 个\n")
        if proxy: self._crawl_log_append(f"代理: {proxy}\n")
        self._crawl_log_append("")

        def _run():
            def _on_progress(current, total, label):
                self.root.after(0, lambda: self._update_crawl_progress(current, total, label))
            crawler = CommentCrawler()
            crawler.configure(
                since_ts=since_ts, until_ts=0, max_videos=max_videos, proxies=proxies,
                progress_callback=_on_progress,
                rate_base=float(self._rate_base_var.get() or 2.0),
                rate_jitter=float(self._rate_jitter_var.get() or 2.0),
                snooze_minutes=int(self._snooze_var.get() or 10),
                auto_tune=self._auto_tune_var.get(),
                auto_snooze=self._auto_snooze_var.get(),
            )
            self._crawler = crawler

            import io
            old_stdout = sys.stdout
            log_buffer = io.StringIO()
            gui_log = self._crawl_log_append
            gui_root = self.root
            class _LW:
                def write(self, s):
                    log_buffer.write(s)
                    if s.strip(): self.flush()
                def flush(self):
                    t = log_buffer.getvalue(); log_buffer.truncate(0); log_buffer.seek(0)
                    if t: gui_root.after(0, lambda x=t: gui_log(x))
            sys.stdout = _LW()
            try:
                if not crawler.setup():
                    self.root.after(0, lambda: self._crawl_done("初始化失败: Cookie 无效"))
                    return
                r = crawler.crawl_by_uid(uid)
                self.root.after(0, lambda rr=r: self._crawl_done(
                    f"完成! 一级:{rr.get('total_root',0)} 子评论:{rr.get('total_subs',0)} 总计:{rr.get('db_total',0)}"))
            except Exception as e:
                self.root.after(0, lambda: self._crawl_done(f"出错: {e}"))
            finally:
                sys.stdout = old_stdout

        threading.Thread(target=_run, daemon=True).start()

    def _stop_crawl(self) -> None:
        if self._crawler:
            self._crawler.cancel()
        self._crawling = False
        self._queue_continue = False
        self._crawl_start_btn.configure(state=tk.NORMAL)
        self._crawl_stop_btn.configure(state=tk.DISABLED)
        self._crawl_log_append("\n[!] 已发送停止信号\n")

    def _update_crawl_progress(self, current, total, label):
        self._crawl_progress["maximum"] = total
        self._crawl_progress["value"] = current
        self._crawl_progress_label.configure(text=f"视频 {current}/{total}: {label}")

    def _crawl_done(self, msg: str) -> None:
        self._crawling = False
        self._crawl_start_btn.configure(state=tk.NORMAL)
        self._crawl_stop_btn.configure(state=tk.DISABLED)
        self._crawl_stats_var.set(msg)
        self._rate_live_var.set("状态: 已停止")
        self._crawl_progress["value"] = self._crawl_progress["maximum"]
        self._crawl_log_append(f"\n=== {msg} ===\n")
        self._set_status("评论爬取 " + msg)
        self._refresh_db_status()
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
        if not self._queue_continue:
            return
        current = self._current_crawl_uid
        if current:
            self._remove_current_from_queue(current)
        next_uid = self._pop_next_uid()
        if next_uid:
            self._crawl_log_append(f"\n=== 队列中还有 UID={next_uid}, 自动继续... ===\n")
            self._crawl_uid_entry.delete(0, tk.END)
            self._crawl_uid_entry.insert(0, next_uid)
            self.root.after(1000, self._start_crawl)

    # ─── 评论检索逻辑 ───────────────────────────────────────────

    def _search_comments(self) -> None:
        uid = self._search_uid_entry.get().strip()
        if not uid.isdigit():
            self._search_count_var.set("请输入有效UID")
            return
        self._search_count_var.set("查询中...")
        threading.Thread(target=self._do_search_comments, args=(uid,), daemon=True).start()

    def _do_search_comments(self, uid: str) -> None:
        import requests
        # 本地 DB
        db_path = str(COMMENTS_DB_PATH)
        local_rows: list[dict] = []
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT rpid,oid,ctime,message,parent FROM comments WHERE mid=? ORDER BY ctime DESC LIMIT 500",
                (int(uid),)).fetchall()
            conn.close()
            for rpid, oid, ctime, msg, parent in rows:
                local_rows.append({"rpid": rpid, "oid": oid, "ctime": ctime,
                                    "message": msg, "parent": parent, "source": "本地"})

        # 在线 API
        online_rows: list[dict] = []
        online_available = False
        try:
            seen_rpids = {r["rpid"] for r in local_rows}
            for pn in range(1, 6):
                resp = requests.get("https://api.aicu.cc/api/v3/search/getreply",
                                    params={"uid": uid, "pn": pn, "ps": 100, "mode": 0}, timeout=8)
                if resp.status_code == 502: break
                data = resp.json()
                if data.get("code") != 0: break
                replies = data.get("data", {}).get("replies", [])
                if not replies: break
                online_available = True
                for r in replies:
                    rpid = r.get("rpid")
                    if rpid not in seen_rpids:
                        seen_rpids.add(rpid)
                        online_rows.append({"rpid": rpid, "oid": r.get("oid", 0),
                                            "ctime": r.get("ctime", 0), "message": r.get("message", ""),
                                            "parent": r.get("parent", 0), "source": "在线"})
                if data.get("data", {}).get("cursor", {}).get("is_end"): break
                time.sleep(0.3)
        except Exception: pass

        merged = local_rows + online_rows
        merged.sort(key=lambda x: x["ctime"], reverse=True)
        if not merged:
            self.root.after(0, lambda: self._search_count_var.set(f"未找到 UID={uid} 的评论"))
            return
        local_c = len(local_rows); online_c = len(online_rows)
        self.root.after(0, lambda: self._search_count_var.set(f"本地{local_c} + 在线{online_c} = {len(merged)}条"))
        source_note = f"[本地{local_c}条 + 在线API{'新增'+str(online_c)+'条' if online_available else '不可用'}]"
        self.root.after(0, lambda: self._show_search_results(uid, merged, source_note))

    def _show_search_results(self, uid: str, rows: list[dict], note: str) -> None:
        """在检索标签页的 ScrolledText 中展示结果。"""
        lines = [f"UID={uid} 的评论 ({len(rows)}条) {note}", "═" * 60, ""]
        for r in rows[:200]:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ctime"]))
            level = "二级" if r["parent"] > 0 else "一级"
            msg = str(r["message"]).replace("\n", " ")[:100]
            lines.append(f"[{ts}] [{r['source']}] [{level}] rpid={r['rpid']} oid={r['oid']}")
            lines.append(f"  {msg}")
            lines.append("")
        if len(rows) > 200:
            lines.append(f"... 还有 {len(rows) - 200} 条")
        self._search_result.configure(state=tk.NORMAL)
        self._search_result.delete("1.0", tk.END)
        self._search_result.insert(tk.END, "\n".join(lines))
        self._search_result.configure(state=tk.DISABLED)
        self._set_status(f"检索完成: UID={uid}, {len(rows)} 条")

    # ─── 数据协作逻辑 ───────────────────────────────────────────

    def _collab_append_result(self, text: str) -> None:
        self._collab_result.configure(state=tk.NORMAL)
        self._collab_result.insert(tk.END, text)
        self._collab_result.see(tk.END)
        self._collab_result.configure(state=tk.DISABLED)

    def _collab_clear_result(self) -> None:
        self._collab_result.configure(state=tk.NORMAL)
        self._collab_result.delete("1.0", tk.END)
        self._collab_result.configure(state=tk.DISABLED)

    def _collab_export(self, all_mode: bool = True) -> None:
        """导出评论（全部 / 按UID）。"""
        uid_text = self._collab_uid_entry.get().strip()
        if not all_mode and not uid_text.isdigit():
            messagebox.showwarning("提示", "请输入有效的 UID")
            return
        uid = int(uid_text) if not all_mode else None
        out_dir = self._collab_dir_var.get().strip() or "datasets"

        # 生成文件名
        if uid:
            filename = f"comments_uid_{uid}.jsonl"
        else:
            filename = f"comments_all_{time.strftime('%Y-%m-%d')}.jsonl"
        out_path = Path(out_dir) / filename

        self._collab_clear_result()
        self._collab_append_result(f"📤 正在导出到 {out_path} ...\n")
        self._set_status("正在导出...")

        def _run():
            result = ds_export(uid=uid, out_path=str(out_path))
            if result["success"]:
                text = (f"✅ 导出完成: {result['exported']} 条评论\n"
                        f"   覆盖 UID: {len(result['uids'])} | 覆盖 OID: {len(result['oids'])}\n"
                        f"   文件: {out_path}\n"
                        f"   大小: {out_path.stat().st_size / 1024:.1f} KB\n")
                # 校验
                qv = quick_validate(out_path)
                if qv["success"]:
                    text += f"   ✅ 格式校验通过 ({qv['rows']} 条)\n"
                else:
                    text += f"   ❌ 校验出错: {qv['errors'][:3]}\n"
            else:
                text = f"❌ 导出失败: {result['error']}\n"
            self.root.after(0, lambda: self._collab_append_result(text))
            self.root.after(0, lambda: self._set_status("导出完成"))
            self.root.after(0, self._refresh_db_status)

        threading.Thread(target=_run, daemon=True).start()

    def _collab_split_export(self) -> None:
        """拆分导出（选 split_by 模式）。"""
        choice = messagebox.askquestion("拆分导出", "按 UID 拆分？\n选择「是」按 UID 拆分，选择「否」按 OID 拆分。")
        if choice is None or choice == "":
            return
        split_by = "uid" if choice == "yes" else "oid"
        out_dir = self._collab_dir_var.get().strip() or "datasets"

        self._collab_clear_result()
        self._collab_append_result(f"📤 正在按 {split_by.upper()} 拆分导出到 {out_dir}/ ...\n")
        self._set_status("正在拆分导出...")

        def _run():
            result = ds_export(split_by=split_by, out_dir=out_dir)
            if result["success"]:
                text = (f"✅ 拆分导出完成: {result['exported']} 条评论, {len(result['outputs'])} 个文件\n"
                        f"   覆盖 UID: {len(result['uids'])} | 覆盖 OID: {len(result['oids'])}\n")
                for p in result["outputs"][:5]:
                    text += f"   - {p.name}\n"
                if len(result["outputs"]) > 5:
                    text += f"   ... 还有 {len(result['outputs']) - 5} 个\n"
            else:
                text = f"❌ 导出失败: {result['error']}\n"
            self.root.after(0, lambda: self._collab_append_result(text))
            self.root.after(0, lambda: self._set_status("拆分导出完成"))

        threading.Thread(target=_run, daemon=True).start()

    def _collab_import(self) -> None:
        """导入 JSONL 文件。"""
        files = filedialog.askopenfilenames(
            title="选择要导入的 JSONL 文件",
            initialdir=self._collab_dir_var.get().strip() or "datasets",
            filetypes=[("JSONL 文件", "*.jsonl"), ("所有文件", "*.*")],
        )
        if not files:
            return
        self._collab_clear_result()
        self._collab_append_result(f"📥 正在导入 {len(files)} 个文件...\n")
        self._set_status("正在导入...")

        def _run():
            result = ds_import(list(files))
            if result["success"]:
                text = (f"✅ 导入完成:\n"
                        f"   文件: {result['files']} | 读取: {result['read']} | "
                        f"新增: {result['inserted']} | 跳过: {result['skipped']}\n"
                        f"   覆盖 UID: {len(result['uids'])} | 覆盖 OID: {len(result['oids'])}\n")
                if result["errors"]:
                    text += f"   ⚠ 错误: {len(result['errors'])} 条\n"
                    for e in result["errors"][:5]:
                        text += f"     {e}\n"
            else:
                text = f"❌ 导入失败: {result.get('error', '未知错误')}\n"
            self.root.after(0, lambda: self._collab_append_result(text))
            self.root.after(0, lambda: self._set_status("导入完成"))
            self.root.after(0, self._refresh_db_status)

        threading.Thread(target=_run, daemon=True).start()

    def _collab_validate(self) -> None:
        """校验 JSONL 文件。"""
        files = filedialog.askopenfilenames(
            title="选择要校验的 JSONL 文件",
            initialdir=self._collab_dir_var.get().strip() or "datasets",
            filetypes=[("JSONL 文件", "*.jsonl"), ("所有文件", "*.*")],
        )
        if not files:
            return
        self._collab_clear_result()
        self._collab_append_result(f"🔍 正在校验 {len(files)} 个文件...\n")
        self._set_status("正在校验...")

        def _run():
            result = ds_validate(list(files))
            if result["success"]:
                text = (f"✅ 校验通过:\n"
                        f"   文件: {result['files']} | 有效行: {result['valid_rows']} | "
                        f"唯一主键: {result['unique_keys']}\n"
                        f"   覆盖 UID: {result['unique_uids']} | 覆盖 OID: {result['unique_oids']}\n")
            else:
                text = (f"❌ 校验发现 {len(result['errors'])} 个错误:\n")
                for e in result["errors"][:15]:
                    text += f"   [ERROR] {e}\n"
                if len(result["errors"]) > 15:
                    text += f"   ... 还有 {len(result['errors']) - 15} 个\n"
            if result["warnings"]:
                text += f"\n⚠ 警告:\n"
                for w in result["warnings"][:10]:
                    text += f"   {w}\n"
            self.root.after(0, lambda: self._collab_append_result(text))
            self.root.after(0, lambda: self._set_status(
                f"校验{'通过' if result['success'] else '失败'}"))

        threading.Thread(target=_run, daemon=True).start()

    def _collab_stats(self) -> None:
        """查看数据库统计。"""
        self._collab_clear_result()
        self._collab_append_result("📊 正在查询数据库统计...\n")
        self._set_status("正在查询统计...")

        def _run():
            result = ds_get_stats()
            if result["success"]:

                def _fmt(ts):
                    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"
                text = (
                    f"📦 数据库统计\n"
                    f"{'═' * 40}\n"
                    f"  总评论     : {result['total']:,}\n"
                    f"  一级评论   : {result['root']:,}\n"
                    f"  子评论     : {result['sub']:,}\n"
                    f"  覆盖 UID   : {result['unique_uids']:,}\n"
                    f"  覆盖 OID   : {result['unique_oids']:,}\n"
                    f"  最早评论   : {_fmt(result['first_ctime'])}\n"
                    f"  最新评论   : {_fmt(result['last_ctime'])}\n"
                    f"  最近爬取   : {_fmt(result['last_crawl'])}\n"
                    f"  文件大小   : {result['file_size']:,} bytes\n"
                    f"\n  Top UID:\n"
                )
                for uid, cnt in result["top_uids"][:10]:
                    text += f"    {uid}: {cnt:,}\n"
                text += f"\n  Top OID:\n"
                for oid, cnt in result["top_oids"][:10]:
                    text += f"    {oid}: {cnt:,}\n"
            else:
                text = f"❌ 查询失败: {result['error']}\n"
            self.root.after(0, lambda: self._collab_append_result(text))
            self.root.after(0, lambda: self._set_status("统计查询完成"))

        threading.Thread(target=_run, daemon=True).start()

    # ─── 状态辅助 ───────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status_bar_var.set(msg)


def main() -> None:
    root = tk.Tk()

    # DPI 感知 (Windows)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # ttk 主题
    style = ttk.Style()
    available = style.theme_names()
    if "vista" in available:
        style.theme_use("vista")
    elif "clam" in available:
        style.theme_use("clam")

    style.configure("TNotebook", background=_COLOR_BG, borderwidth=0)
    style.configure("TNotebook.Tab", font=_FONT_BODY, padding=[18, 6])
    style.map("TNotebook.Tab", background=[("selected", _COLOR_CARD), ("!selected", "#e8e8e8")])

    BiliSpiderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
