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
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
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
from .wordcloud_utils import (
    add_user_stop_word,
    clear_user_stop_words,
    generate_wordcloud,
    load_user_stop_words,
    normalize_stop_words,
    save_user_stop_words,
    USER_STOPWORDS_PATH,
)
from .dataset_tools import (
    export_comments as ds_export,
    import_jsonl as ds_import,
    validate_jsonl_files as ds_validate,
    get_db_stats as ds_get_stats,
    quick_validate,
    COMMENT_COLUMNS,
)
from .remote_sync import DEFAULT_REMOTE_MANIFEST_URL, sync_remote_datasets
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
        self._qr_image_label: Optional[tk.Label] = None
        self._qr_photo = None

        # 评论爬取状态
        self._crawler: Optional[CommentCrawler] = None
        self._crawling = False
        self._bench_runner = None
        self._current_crawl_uid: Optional[str] = None
        self._queue_continue = False
        self._wordcloud_context: dict | None = None
        self._remote_sync_running = False
        self._publish_running = False
        self._config: dict = {}

        # UI 变量
        self._login_status_var = tk.StringVar(value="未登录")
        self._db_status_var = tk.StringVar(value="")
        self._remote_sync_enabled_var = tk.BooleanVar(value=False)
        self._remote_sync_status_var = tk.StringVar(value="远端同步: 未开启")
        self._status_bar_var = tk.StringVar(value="就绪")

        self._config_path = str(CONFIG_PATH)

        self._build_ui()
        self._load_config()
        self._refresh_queue_display()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._check_login_on_start()
        self._refresh_db_status()
        self.root.after(600, self._remote_sync_startup_check)

    # ─── 配置持久化 ─────────────────────────────────────────────

    def _load_config(self) -> None:
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        self._config = cfg

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
        self._remote_sync_enabled_var.set(bool(cfg.get("remote_sync_enabled", False)))

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
            "remote_sync_enabled": self._remote_sync_enabled_var.get(),
            "remote_sync_prompted": bool(self._config.get("remote_sync_prompted", False)),
            "remote_manifest_url": self._config.get("remote_manifest_url", DEFAULT_REMOTE_MANIFEST_URL),
        }
        self._config = cfg
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
            with open(self._queue_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    return []
                queue: list[str] = []
                seen: set[str] = set()
                for item in data:
                    uid = str(item).strip()
                    if uid.isdigit() and uid not in seen:
                        queue.append(uid)
                        seen.add(uid)
                return queue
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
            self._refresh_queue_display()
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
        """数据协作标签页：导出、导入、校验、统计和文件清理。"""
        toolbar = tk.Frame(self._collab_tab, bg=_COLOR_CARD)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 4))

        _btn_primary(toolbar, "导出全部", lambda: self._collab_export(all_mode=True)).pack(side=tk.LEFT, padx=2)
        _btn_primary(toolbar, "按UID导出", lambda: self._collab_export(all_mode=False)).pack(side=tk.LEFT, padx=2)
        _btn_primary(toolbar, "拆分导出", self._collab_split_export).pack(side=tk.LEFT, padx=2)
        _btn_normal(toolbar, "批量删除", self._collab_batch_delete).pack(side=tk.LEFT, padx=2)
        _btn_normal(toolbar, "导入JSONL", self._collab_import).pack(side=tk.LEFT, padx=2)
        _btn_normal(toolbar, "校验JSONL", self._collab_validate).pack(side=tk.LEFT, padx=2)
        _btn_normal(toolbar, "数据库统计", self._collab_stats).pack(side=tk.LEFT, padx=2)
        _btn_normal(toolbar, "一键导出并发布(我专用)", self._collab_export_publish_remote).pack(side=tk.LEFT, padx=(10, 2))

        sync_row = tk.Frame(self._collab_tab, bg=_COLOR_CARD)
        sync_row.pack(fill=tk.X, padx=8, pady=(0, 4))

        _btn_normal(sync_row, "立即同步远端数据", self._remote_sync_manual).pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(
            sync_row,
            text="启动时自动同步",
            variable=self._remote_sync_enabled_var,
            command=self._remote_sync_toggle,
            bg=_COLOR_CARD,
            font=_FONT_SMALL,
        ).pack(side=tk.LEFT, padx=(8, 2))
        tk.Label(sync_row, textvariable=self._remote_sync_status_var,
                 font=_FONT_SMALL, bg=_COLOR_CARD, fg="#888").pack(side=tk.RIGHT, padx=6)

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
        self._qr_image_label = tk.Label(
            self._qr_window,
            text="二维码生成中...",
            font=_FONT_BODY,
            bg=_COLOR_CARD,
            fg="#888",
            width=30,
            height=14,
        )
        self._qr_image_label.pack(padx=16, pady=(0, 8))
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
                self.root.after(0, lambda: self._render_qr_code(url))
            elif "扫描" in msg or "扫码" in msg or "确认" in msg:
                self.root.after(0, lambda: self._qr_status_var.set(f"📱 {msg}"))
            elif "成功" in msg:
                self.root.after(0, lambda: self._on_qr_success(msg))
            elif "过期" in msg or "取消" in msg or "失败" in msg:
                self.root.after(0, lambda: self._on_qr_failure(msg))

        def _login_thread():
            try:
                qr_login(
                    status_callback=_status_callback,
                    cancel_event=cancel_event,
                    show_terminal_qr=False,
                )
            except Exception as e:
                self.root.after(0, lambda: self._on_qr_failure(f"登录异常: {e}"))

        threading.Thread(target=_login_thread, daemon=True).start()

    def _render_qr_code(self, url: str) -> None:
        """Render the login QR code into the GUI dialog."""
        if not self._qr_window or not self._qr_image_label:
            return
        try:
            import qrcode  # type: ignore
            from PIL import ImageTk  # type: ignore

            qr = qrcode.QRCode(border=2, box_size=8)
            qr.add_data(url)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            image = image.resize((260, 260))
            self._qr_photo = ImageTk.PhotoImage(image)
            self._qr_image_label.configure(image=self._qr_photo, text="", width=260, height=260)
            self._qr_status_var.set("请使用哔哩哔哩 App 扫码")
        except Exception as exc:
            self._qr_photo = None
            self._qr_image_label.configure(
                image="",
                text=f"二维码渲染失败，请复制下方链接打开：{exc}",
                wraplength=320,
                width=36,
                height=8,
            )

    def _on_qr_success(self, msg: str) -> None:
        self._qr_status_var.set(f"✅ {msg}")
        self._qr_login_active = False
        if self._qr_window:
            self._qr_window.after(800, self._qr_window.destroy)
            self._qr_window = None
        self._qr_image_label = None
        self._qr_photo = None
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
        self._qr_image_label = None
        self._qr_photo = None

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
        _first, last = self._crawl_log.yview()
        should_follow = last >= 0.995
        self._crawl_log.configure(state=tk.NORMAL)
        self._crawl_log.insert(tk.END, text)
        if should_follow:
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

        db_path = str(COMMENTS_DB_PATH)
        local_rows: list[dict] = []
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT rpid, oid, ctime, message, parent FROM comments WHERE mid=? ORDER BY ctime DESC LIMIT 500",
                (int(uid),),
            ).fetchall()
            conn.close()
            for rpid, oid, ctime, msg, parent in rows:
                local_rows.append({
                    "rpid": rpid,
                    "oid": oid,
                    "ctime": ctime,
                    "message": msg or "",
                    "parent": parent,
                    "source": "本地",
                })

        online_rows: list[dict] = []
        online_state = {"status": "unavailable", "message": "未请求"}
        try:
            seen_rpids = {r["rpid"] for r in local_rows}
            for pn in range(1, 6):
                resp = requests.get(
                    "https://api.aicu.cc/api/v3/search/getreply",
                    params={"uid": uid, "pn": pn, "ps": 100, "mode": 0},
                    timeout=8,
                )
                if resp.status_code == 502:
                    online_state = {"status": "unavailable", "message": "HTTP 502"}
                    break
                if resp.status_code != 200:
                    online_state = {"status": "unavailable", "message": f"HTTP {resp.status_code}"}
                    break
                try:
                    data = resp.json()
                except Exception:
                    online_state = {"status": "error", "message": "在线 API 返回非 JSON"}
                    break
                if data.get("code") != 0:
                    online_state = {
                        "status": "error",
                        "message": f"code={data.get('code')}: {data.get('message', 'unknown')}",
                    }
                    break
                replies = data.get("data", {}).get("replies", [])
                if not replies:
                    online_state = {"status": "empty", "message": "在线 API 无数据"}
                    break
                online_state = {"status": "available", "message": f"第 {pn} 页可用"}
                for r in replies:
                    row = self._online_reply_to_row(r)
                    rpid = row["rpid"]
                    if rpid not in seen_rpids:
                        seen_rpids.add(rpid)
                        online_rows.append(row)
                if data.get("data", {}).get("cursor", {}).get("is_end"):
                    break
                time.sleep(0.3)
        except requests.exceptions.Timeout:
            online_state = {"status": "unavailable", "message": "请求超时"}
        except requests.exceptions.RequestException as exc:
            online_state = {"status": "error", "message": str(exc)}
        except Exception as exc:
            online_state = {"status": "error", "message": str(exc)}

        merged = local_rows + online_rows
        merged.sort(key=lambda x: x["ctime"], reverse=True)
        local_c = len(local_rows)
        online_c = len(online_rows)

        if not merged:
            if online_state["status"] == "empty":
                summary = "未找到评论，本地 0 条，在线 API 无数据"
            else:
                summary = f"未找到评论，本地 0 条，在线 API 不可用：{online_state['message']}"
            self.root.after(0, lambda: self._search_count_var.set(summary))
            self.root.after(0, lambda: self._set_status(summary))
            return

        if online_state["status"] == "available" and online_c > 0:
            summary = f"本地 {local_c} 条 + 在线新增 {online_c} 条 = {len(merged)} 条"
        elif online_state["status"] == "available":
            summary = f"本地 {local_c} 条 = {len(merged)} 条"
        elif online_state["status"] == "empty":
            summary = f"本地 {local_c} 条 = {len(merged)} 条 | 在线 API 无数据"
        else:
            summary = f"本地 {local_c} 条 = {len(merged)} 条 | 在线 API 不可用：{online_state['message']}"

        self.root.after(0, lambda: self._search_count_var.set(summary))
        self.root.after(0, lambda: self._set_status(summary))
        self.root.after(0, lambda: self._show_comment_table_v2(uid, merged, summary))

    def _to_int(self, value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _online_reply_to_row(self, reply: dict) -> dict:
        """Normalize AICU online reply records to the local table shape."""
        dyn = reply.get("dyn") if isinstance(reply.get("dyn"), dict) else {}
        return {
            "rpid": self._to_int(reply.get("rpid")),
            "oid": self._to_int(reply.get("oid", dyn.get("oid", 0))),
            "ctime": self._to_int(reply.get("ctime", reply.get("time", 0))),
            "message": reply.get("message", "") or "",
            "parent": reply.get("parent", 0),
            "source": "在线",
        }

    def _comment_parent_value(self, row: dict) -> int:
        """Return a numeric parent value from local DB rows or online API rows."""
        parent = row.get("parent", 0)
        if isinstance(parent, dict):
            for key in ("rpid", "id", "parent", "root", "parentid", "rootid"):
                value = parent.get(key)
                if value not in (None, "", 0, "0"):
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return 1
            return 1 if parent else 0
        try:
            return int(parent or 0)
        except (TypeError, ValueError):
            return 0

    def _comment_level(self, row: dict) -> str:
        return "二级" if self._comment_parent_value(row) > 0 else "一级"

    def _show_comment_table_v2(self, uid: str, rows: list[dict], note: str) -> None:
        """弹出融合结果表格窗口 (含来源列、关键词筛选、复制、导出)。"""
        win = tk.Toplevel(self.root)
        win.title(f"UID={uid} 的评论 ({len(rows)}条) {note}")
        win.geometry("920x520")
        win.configure(bg=_COLOR_CARD)

        # 工具栏
        toolbar = tk.Frame(win, bg=_COLOR_CARD)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(toolbar, text=f"共 {len(rows)} 条评论", font=_FONT_HEADING,
                 bg=_COLOR_CARD).pack(side=tk.LEFT)
        tk.Label(toolbar, text=note, font=("Microsoft YaHei", 8),
                 bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT, padx=10)

        # 表格（先创建，因为按钮需要引用 tree）
        tree_frame = tk.Frame(win, bg=_COLOR_CARD)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))
        columns = ("time", "source", "level", "oid", "rpid", "text")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
        tree.heading("time", text="时间"); tree.column("time", width=130)
        tree.heading("source", text="来源"); tree.column("source", width=50)
        tree.heading("level", text="层级"); tree.column("level", width=50)
        tree.heading("oid", text="视频oid"); tree.column("oid", width=100)
        tree.heading("rpid", text="rpid"); tree.column("rpid", width=100)
        tree.heading("text", text="评论内容"); tree.column("text", width=400)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # 工具栏按钮放在 tree 创建之后
        copy_btn = tk.Button(toolbar, text="复制选中行",
                             command=lambda: self._copy_selected_rows(tree),
                             bg="#666", fg="white", font=_FONT_BODY,
                             relief=tk.FLAT, padx=12, pady=2, cursor="hand2")
        copy_btn.pack(side=tk.RIGHT, padx=4)
        # 关键词过滤
        filtered_rows = list(rows)
        filter_row = tk.Frame(win, bg=_COLOR_CARD)
        filter_row.pack(fill=tk.X, padx=8, pady=(0, 2))
        tk.Label(filter_row, text="关键词:", font=_FONT_BODY, bg=_COLOR_CARD).pack(side=tk.LEFT)
        filter_var = tk.StringVar()
        filter_entry = tk.Entry(filter_row, textvariable=filter_var, font=_FONT_BODY, width=25)
        filter_entry.pack(side=tk.LEFT, padx=6)
        filter_count_var = tk.StringVar(value=f"显示 {len(rows)} 条")
        tk.Label(filter_row, textvariable=filter_count_var, font=("Microsoft YaHei", 9),
                 bg=_COLOR_CARD, fg="#888").pack(side=tk.LEFT, padx=10)
        tk.Button(filter_row, text="清除", command=lambda: self._clear_filter(tree, rows, filter_entry, filter_count_var),
                  font=("Microsoft YaHei", 8), relief=tk.FLAT, padx=8, cursor="hand2").pack(side=tk.LEFT)

        tk.Button(toolbar, text="导出Excel",
                  command=lambda: self._export_to_excel_v2(uid, list(filtered_rows)),
                  bg=_COLOR_BILI_BLUE, fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=2, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(toolbar, text="词云",
                  command=lambda: self._generate_wordcloud_thread(uid, list(filtered_rows)),
                  bg="#8e44ad", fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=2, cursor="hand2").pack(side=tk.RIGHT, padx=4)


        def _row_search_text(r: dict) -> str:
            level = self._comment_level(r)
            parts = (
                r.get("source", ""),
                level,
                r.get("oid", ""),
                r.get("rpid", ""),
                r.get("message", ""),
            )
            return " ".join(str(part) for part in parts).casefold()

        def _insert_row(r: dict) -> None:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ctime"]))
            level = self._comment_level(r)
            msg = str(r["message"]).replace("\n", " ")[:120]
            tree.insert("", tk.END, values=(ts, r["source"], level, r["oid"], r["rpid"], msg))

        # 填充数据
        for r in rows:
            _insert_row(r)

        def _apply_filter(*_args):
            keyword = filter_var.get().strip().casefold()
            tree.delete(*tree.get_children())
            filtered_rows.clear()
            for r in rows:
                if not keyword or keyword in _row_search_text(r):
                    _insert_row(r)
                    filtered_rows.append(r)
            filter_count_var.set(f"显示 {len(filtered_rows)}/{len(rows)} 条")
        filter_var.trace_add("write", _apply_filter)
        filter_entry.bind("<KeyRelease>", _apply_filter)

        # 双击打开视频
        def _on_double_click(event):
            item = tree.selection()
            if item:
                values = tree.item(item[0], "values")
                oid = values[3]
                import webbrowser
                webbrowser.open(f"https://www.bilibili.com/video/av{oid}")
        tree.bind("<Double-1>", _on_double_click)

        self._set_status(f"检索完成: UID={uid}, {len(rows)} 条")

    def _generate_wordcloud_thread(self, uid: str, rows: list[dict]) -> None:
        """在后台线程生成词云,完成后在主线程打开预览。"""
        if not rows:
            messagebox.showinfo("词云", "当前没有可生成词云的数据", parent=self.root)
            return

        self._wordcloud_context = {"uid": uid, "rows": list(rows)}
        self._set_status("正在生成词云...")
        import threading

        def _run():
            try:
                png_bytes, msg, top_words = generate_wordcloud(rows)
            except Exception as e:
                png_bytes, msg, top_words = None, f"词云生成异常: {e}", []
            self.root.after(
                0,
                lambda: self._show_wordcloud_preview(uid, list(rows), png_bytes, msg, top_words),
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _show_wordcloud_preview(self, uid: str, rows: list[dict],
                                 png_bytes: bytes | None, msg: str,
                                 top_words: list[tuple[str, int]] | None = None) -> None:
        """显示词云预览窗口 (带保存按钮)。"""
        if png_bytes is None:
            self._set_status("词云: " + msg)
            messagebox.showinfo("词云", msg, parent=self.root)
            return

        self._set_status(msg)
        win = tk.Toplevel(self.root)
        win.title(f"UID={uid} 词云")
        win.geometry("980x720")
        win.minsize(720, 520)
        win.configure(bg=_COLOR_CARD)

        from io import BytesIO
        from PIL import Image, ImageTk

        source_img = Image.open(BytesIO(png_bytes)).convert("RGB")
        source_w, source_h = source_img.size

        # 顶部工具栏
        bar = tk.Frame(win, bg=_COLOR_CARD)
        bar.pack(fill=tk.X, padx=12, pady=(10, 8))
        tk.Label(
            bar,
            text=f"词云预览  {source_w}x{source_h}",
            font=_FONT_HEADING,
            bg=_COLOR_CARD,
            fg="#333",
        ).pack(side=tk.LEFT)
        scale_label = tk.Label(
            bar,
            text=msg,
            font=("Microsoft YaHei", 9),
            bg=_COLOR_CARD,
            fg="#888",
        )
        scale_label.pack(side=tk.LEFT, padx=12)

        body = tk.Frame(win, bg="#eef1f5")
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(2, weight=0, minsize=220)

        canvas = tk.Canvas(
            body,
            bg="#f8fafc",
            highlightthickness=1,
            highlightbackground="#d7dde6",
        )
        vsb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=canvas.yview)
        hsb = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        words_panel = tk.Frame(body, bg="#f8fafc", width=220)
        words_panel.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=(10, 0))
        words_panel.grid_propagate(False)
        tk.Label(words_panel, text="高频词", font=_FONT_HEADING,
                 bg="#f8fafc", fg="#333").pack(anchor=tk.W, padx=8, pady=(8, 4))
        tk.Label(words_panel, text="双击或选中后点屏蔽",
                 font=("Microsoft YaHei", 8), bg="#f8fafc", fg="#888").pack(anchor=tk.W, padx=8)

        word_tree_frame = tk.Frame(words_panel, bg="#f8fafc")
        word_tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        word_tree = ttk.Treeview(
            word_tree_frame,
            columns=("word", "count"),
            show="headings",
            selectmode="browse",
            height=18,
        )
        word_tree.heading("word", text="词")
        word_tree.heading("count", text="次数")
        word_tree.column("word", width=120, anchor=tk.W)
        word_tree.column("count", width=60, anchor=tk.E)
        word_vsb = ttk.Scrollbar(word_tree_frame, orient=tk.VERTICAL, command=word_tree.yview)
        word_tree.configure(yscrollcommand=word_vsb.set)
        word_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        word_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        for word, count in (top_words or [])[:50]:
            word_tree.insert("", tk.END, values=(word, count))

        preview_state = {
            "photo": None,
            "scale": 1.0,
            "fit": True,
            "after_id": None,
        }

        def _resample_filter():
            return getattr(getattr(Image, "Resampling", Image), "LANCZOS")

        def _render_preview() -> None:
            canvas_w = max(canvas.winfo_width(), 1)
            canvas_h = max(canvas.winfo_height(), 1)
            padding = 24
            if preview_state["fit"]:
                fit_scale = min(
                    1.0,
                    max((canvas_w - padding * 2) / source_w, 0.05),
                    max((canvas_h - padding * 2) / source_h, 0.05),
                )
                preview_state["scale"] = fit_scale

            scale = float(preview_state["scale"])
            draw_w = max(1, int(source_w * scale))
            draw_h = max(1, int(source_h * scale))
            if scale == 1.0:
                display_img = source_img
            else:
                display_img = source_img.resize((draw_w, draw_h), _resample_filter())

            photo = ImageTk.PhotoImage(display_img)
            preview_state["photo"] = photo

            canvas.delete("all")
            x = max(padding, (canvas_w - draw_w) // 2)
            y = max(padding, (canvas_h - draw_h) // 2)
            canvas.create_image(x, y, image=photo, anchor=tk.NW)
            canvas.configure(scrollregion=(0, 0, draw_w + padding * 2, draw_h + padding * 2))
            scale_label.configure(text=f"{msg} · 缩放 {scale * 100:.0f}%")

        def _schedule_render(_event=None) -> None:
            after_id = preview_state.get("after_id")
            if after_id:
                win.after_cancel(after_id)
            preview_state["after_id"] = win.after(80, _render_preview)

        def _set_zoom(scale: float, fit: bool = False) -> None:
            preview_state["fit"] = fit
            if not fit:
                preview_state["scale"] = max(0.1, min(scale, 2.0))
            _render_preview()

        def _zoom(delta: float) -> None:
            _set_zoom(float(preview_state["scale"]) * delta, fit=False)

        def _refresh_from_same_rows() -> None:
            if win.winfo_exists():
                win.destroy()
            self._generate_wordcloud_thread(uid, rows)

        def _open_editor() -> None:
            self._open_wordcloud_stopwords_editor(uid, rows, win)

        tk.Button(bar, text="适应窗口", command=lambda: _set_zoom(1.0, fit=True),
                  bg="#666", fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=2, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="100%", command=lambda: _set_zoom(1.0),
                  bg="#666", fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=10, pady=2, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="+", command=lambda: _zoom(1.25),
                  bg="#666", fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=10, pady=2, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="-", command=lambda: _zoom(0.8),
                  bg="#666", fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=10, pady=2, cursor="hand2").pack(side=tk.RIGHT, padx=4)

        def _save():
            default_name = f"uid_{uid}_wordcloud.png"
            filepath = filedialog.asksaveasfilename(
                parent=win, defaultextension=".png",
                filetypes=[("PNG 图片", "*.png")],
                initialfile=default_name,
            )
            if filepath:
                try:
                    with open(filepath, "wb") as f:
                        f.write(png_bytes)
                    messagebox.showinfo("保存成功", f"词云已保存到:\n{filepath}", parent=win)
                except Exception as e:
                    messagebox.showerror("保存失败", str(e), parent=win)

        tk.Button(bar, text="保存PNG", command=_save,
                  bg="#8e44ad", fg="white", font=("Microsoft YaHei", 10),
                  relief=tk.FLAT, padx=16, pady=3, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="停用词", command=_open_editor,
                  bg=_COLOR_BILI_BLUE, fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=2, cursor="hand2").pack(side=tk.RIGHT, padx=4)

        def _selected_word() -> str:
            selected = word_tree.selection()
            if not selected:
                return ""
            values = word_tree.item(selected[0], "values")
            return str(values[0]).strip() if values else ""

        def _block_selected_word(_event=None) -> None:
            word = _selected_word()
            if not word:
                messagebox.showinfo("词云", "请先选择一个高频词", parent=win)
                return
            try:
                add_user_stop_word(word)
            except Exception as e:
                messagebox.showerror("停用词保存失败", str(e), parent=win)
                return
            self._set_status(f"已加入停用词: {word}")
            _refresh_from_same_rows()

        word_tree.bind("<Double-1>", _block_selected_word)
        tk.Button(words_panel, text="屏蔽选中词", command=_block_selected_word,
                  bg=_COLOR_BTN_NORMAL, fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=10, pady=4, cursor="hand2").pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(words_panel, text="编辑停用词", command=_open_editor,
                  bg=_COLOR_BILI_BLUE, fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=10, pady=4, cursor="hand2").pack(fill=tk.X, padx=8, pady=(0, 8))

        def _on_mousewheel(event) -> str:
            if event.state & 0x0004:
                _zoom(1.1 if event.delta > 0 else 0.9)
            else:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        canvas.bind("<Configure>", _schedule_render)
        canvas.bind("<MouseWheel>", _on_mousewheel)
        win.after(50, _render_preview)

    def _open_wordcloud_stopwords_editor(self, uid: str, rows: list[dict],
                                         preview_win: tk.Toplevel | None = None) -> None:
        """打开用户停用词编辑窗口。"""
        editor = tk.Toplevel(self.root)
        editor.title("词云停用词")
        editor.geometry("520x560")
        editor.minsize(420, 420)
        editor.configure(bg=_COLOR_CARD)

        tk.Label(editor, text="用户停用词 (一行一个词)", font=_FONT_HEADING,
                 bg=_COLOR_CARD, fg="#333").pack(anchor=tk.W, padx=12, pady=(12, 4))
        tk.Label(editor, text=f"保存位置: {USER_STOPWORDS_PATH}",
                 font=("Microsoft YaHei", 8), bg=_COLOR_CARD, fg="#888").pack(anchor=tk.W, padx=12)

        text = scrolledtext.ScrolledText(editor, font=("Microsoft YaHei", 10), height=20)
        text.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        try:
            words = sorted(load_user_stop_words())
        except Exception as e:
            words = []
            messagebox.showwarning("读取停用词失败", str(e), parent=editor)
        text.insert("1.0", "\n".join(words))

        btn_row = tk.Frame(editor, bg=_COLOR_CARD)
        btn_row.pack(fill=tk.X, padx=12, pady=(0, 12))

        def _refresh_preview() -> None:
            if preview_win is not None and preview_win.winfo_exists():
                preview_win.destroy()
            self._generate_wordcloud_thread(uid, rows)

        def _save_and_refresh() -> None:
            try:
                normalized = save_user_stop_words(text.get("1.0", tk.END))
            except Exception as e:
                messagebox.showerror("保存失败", str(e), parent=editor)
                return
            self._set_status(f"已保存 {len(normalized)} 个用户停用词")
            editor.destroy()
            _refresh_preview()

        def _reset_default() -> None:
            if not messagebox.askyesno("恢复默认", "清空用户停用词,仅保留内置默认词?", parent=editor):
                return
            try:
                clear_user_stop_words()
            except Exception as e:
                messagebox.showerror("恢复默认失败", str(e), parent=editor)
                return
            text.delete("1.0", tk.END)
            self._set_status("已清空用户停用词")
            _refresh_preview()

        def _import_txt() -> None:
            filepath = filedialog.askopenfilename(
                parent=editor,
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            )
            if not filepath:
                return
            try:
                imported = Path(filepath).read_text(encoding="utf-8-sig")
            except Exception as e:
                messagebox.showerror("导入失败", str(e), parent=editor)
                return
            current = text.get("1.0", tk.END)
            merged = normalize_stop_words(current + "\n" + imported)
            text.delete("1.0", tk.END)
            text.insert("1.0", "\n".join(merged))

        def _export_txt() -> None:
            filepath = filedialog.asksaveasfilename(
                parent=editor,
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                initialfile="wordcloud_stopwords.txt",
            )
            if not filepath:
                return
            try:
                words = normalize_stop_words(text.get("1.0", tk.END))
                Path(filepath).write_text("\n".join(words) + ("\n" if words else ""),
                                          encoding="utf-8", newline="\n")
            except Exception as e:
                messagebox.showerror("导出失败", str(e), parent=editor)
                return
            messagebox.showinfo("导出成功", f"已导出到:\n{filepath}", parent=editor)

        tk.Button(btn_row, text="保存并重新生成", command=_save_and_refresh,
                  bg="#8e44ad", fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=4, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(btn_row, text="恢复默认", command=_reset_default,
                  bg=_COLOR_BTN_DANGER, fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=4, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(btn_row, text="导出txt", command=_export_txt,
                  bg=_COLOR_BTN_NORMAL, fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="导入txt", command=_import_txt,
                  bg=_COLOR_BTN_NORMAL, fg="white", font=_FONT_BODY,
                  relief=tk.FLAT, padx=12, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=4)

    def _clear_filter(self, tree: ttk.Treeview, rows: list[dict],
                      filter_entry: tk.Entry, count_var: tk.StringVar) -> None:
        """清除关键词过滤，恢复全部行。"""
        filter_entry.delete(0, tk.END)
        tree.delete(*tree.get_children())
        for r in rows:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ctime"]))
            level = self._comment_level(r)
            tree.insert("", tk.END, values=(
                ts, r["source"], level, r["oid"], r["rpid"],
                str(r["message"]).replace("\n", " ")[:120]))
        count_var.set(f"显示 {len(rows)} 条")

    def _copy_selected_rows(self, tree: ttk.Treeview) -> None:
        """复制 Treeview 选中行到剪贴板。"""
        items = tree.selection()
        if not items:
            return
        lines = []
        for item in items:
            vals = tree.item(item, "values")
            lines.append(f"{vals[0]}\t{vals[1]}\t{vals[2]}\t{vals[3]}\t{vals[4]}\t{vals[5]}")
        text = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status(f"已复制 {len(items)} 行到剪贴板")

    def _export_to_excel_v2(self, uid: str, rows: list[dict]) -> None:
        """导出融合结果为 Excel（含来源列）。"""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx")],
            initialfile=f"{uid}_评论数据.xlsx")
        if not filepath:
            return
        try:
            import openpyxl
            wb = openpyxl.Workbook(); ws = wb.active
            ws.title = f"UID={uid}"
            ws.append(["来源", "rpid", "视频oid", "时间", "层级", "评论内容"])
            for r in rows:
                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ctime"]))
                ws.append([r["source"], r["rpid"], r["oid"], ts,
                           self._comment_level(r), str(r["message"])])
            wb.save(filepath)
            messagebox.showinfo("导出成功", f"已保存到:\n{filepath}")
        except ImportError:
            # 回退到 CSV
            filepath = filepath.replace(".xlsx", ".csv")
            import csv
            with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["来源", "rpid", "视频oid", "时间", "层级", "评论内容"])
                for r in rows:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ctime"]))
                    w.writerow([r["source"], r["rpid"], r["oid"], ts,
                                self._comment_level(r), str(r["message"])])
            messagebox.showinfo("导出成功", f"已保存为CSV:\n{filepath}")

    # ─── 数据协作逻辑 ───────────────────────────────────────────

    # ─── 远端数据同步 ─────────────────────────────────────────────

    def _collab_export_publish_remote(self) -> None:
        if self._publish_running:
            messagebox.showinfo("一键导出并发布", "发布任务正在进行中。", parent=self.root)
            return
        if not messagebox.askyesno(
            "一键导出并发布（我专用）",
            "将导出当前本地 comments.db 的全量 JSONL，压缩为 jsonl.gz，"
            "生成远端同步 manifest，并上传到当前 GitHub latest release。\n\n确认继续？",
            parent=self.root,
        ):
            return

        self._publish_running = True
        self._collab_clear_result()
        self._collab_append_result("=== 一键导出并发布远端数据包 ===\n")
        self._set_status("正在导出并发布远端数据包...")

        def log(message: str) -> None:
            self.root.after(0, lambda m=message: self._collab_append_result(m + "\n"))

        def sha256_file(path: Path) -> str:
            sha = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    sha.update(chunk)
            return sha.hexdigest()

        def find_gh() -> str:
            gh = shutil.which("gh")
            if gh:
                return gh
            candidates = [
                Path(os.environ.get("ProgramFiles", "")) / "GitHub CLI" / "gh.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "GitHub CLI" / "gh.exe",
                Path(os.environ.get("ProgramFiles(x86)", "")) / "GitHub CLI" / "gh.exe",
            ]
            for candidate in candidates:
                if candidate.exists():
                    return str(candidate)
            raise RuntimeError("未找到 GitHub CLI: gh.exe")

        def run_checked(args: list[str]) -> str:
            completed = subprocess.run(
                args,
                cwd=Path(__file__).resolve().parent.parent,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if completed.returncode != 0:
                output = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(f"命令失败: {' '.join(args)}\n{output}")
            return completed.stdout.strip()

        def _run() -> None:
            try:
                out_dir = Path(self._collab_dir_var.get().strip() or "datasets")
                out_dir.mkdir(parents=True, exist_ok=True)
                date_str = time.strftime("%Y-%m-%d")
                jsonl_path = out_dir / f"comments_all_{date_str}.jsonl"
                gz_path = out_dir / f"{jsonl_path.name}.gz"
                manifest_path = out_dir / "bilispider-data-manifest.json"

                log(f"导出全量 JSONL: {jsonl_path}")
                result = ds_export(out_path=str(jsonl_path))
                if not result.get("success"):
                    raise RuntimeError(f"导出失败: {result.get('error', '未知错误')}")
                log(f"导出完成: {result.get('exported', 0)} 条")

                qv = quick_validate(jsonl_path)
                if not qv.get("success"):
                    raise RuntimeError(f"JSONL 校验失败: {qv.get('errors', [])[:3]}")
                log(f"校验通过: {qv.get('rows', 0)} 行")

                log(f"压缩: {gz_path}")
                with jsonl_path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)

                gz_sha = sha256_file(gz_path)
                generated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                manifest = {
                    "version": 1,
                    "generated_at": generated_at,
                    "files": [
                        {
                            "name": gz_path.name,
                            "sha256": gz_sha,
                            "size_bytes": gz_path.stat().st_size,
                            "comments": int(result.get("exported", 0) or 0),
                            "generated_at": generated_at,
                        }
                    ],
                }
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                log(f"写入远端 manifest: {manifest_path}")

                gh = find_gh()
                log("检查 GitHub 登录状态...")
                run_checked([gh, "auth", "status"])
                tag = run_checked([gh, "release", "view", "--json", "tagName", "--jq", ".tagName"])
                if not tag:
                    raise RuntimeError("无法获取 latest release tag")
                log(f"latest release: {tag}")

                log("上传数据包和 manifest 到 GitHub Release...")
                run_checked([gh, "release", "upload", tag, str(gz_path), str(manifest_path), "--clobber"])
                log("发布完成。")

                def finish_ok() -> None:
                    self._publish_running = False
                    self._set_status("远端数据包发布完成")
                    messagebox.showinfo(
                        "发布完成",
                        f"已上传到 {tag}:\n{gz_path.name}\n{manifest_path.name}",
                        parent=self.root,
                    )

                self.root.after(0, finish_ok)
            except Exception as exc:
                exc_text = str(exc)

                def finish_error(message: str = exc_text) -> None:
                    self._publish_running = False
                    self._set_status("远端数据包发布失败")
                    self._collab_append_result(f"发布失败: {message}\n")
                    messagebox.showerror("发布失败", message, parent=self.root)

                self.root.after(0, finish_error)

        threading.Thread(target=_run, daemon=True).start()

    def _remote_sync_manifest_url(self) -> str:
        return str(self._config.get("remote_manifest_url") or DEFAULT_REMOTE_MANIFEST_URL)

    def _remote_sync_startup_check(self) -> None:
        prompted = bool(self._config.get("remote_sync_prompted", False))
        if not prompted:
            ok = messagebox.askyesno(
                "远端数据同步",
                "是否开启启动时自动同步远端评论数据集？\n\n"
                "开启后每次启动只会先检查远端清单，有新数据时才下载并合并到本地数据库。",
                parent=self.root,
            )
            self._config["remote_sync_prompted"] = True
            self._remote_sync_enabled_var.set(bool(ok))
            self._save_config()
            if ok:
                self._remote_sync_run(auto=True)
            else:
                self._remote_sync_status_var.set("远端同步: 已关闭")
            return

        if self._remote_sync_enabled_var.get():
            self._remote_sync_run(auto=True)
        else:
            self._remote_sync_status_var.set("远端同步: 已关闭")

    def _remote_sync_toggle(self) -> None:
        self._config["remote_sync_prompted"] = True
        self._save_config()
        if self._remote_sync_enabled_var.get():
            self._remote_sync_status_var.set("远端同步: 已开启")
            self._remote_sync_run(auto=False)
        else:
            self._remote_sync_status_var.set("远端同步: 已关闭")
            self._set_status("已关闭启动时自动同步")

    def _remote_sync_manual(self) -> None:
        self._config["remote_sync_prompted"] = True
        self._save_config()
        self._remote_sync_run(auto=False)

    def _remote_sync_run(self, auto: bool = False) -> None:
        if self._remote_sync_running:
            if not auto:
                messagebox.showinfo("远端同步", "远端同步正在进行中。", parent=self.root)
            return
        self._remote_sync_running = True
        self._remote_sync_status_var.set("远端同步: 检查中...")
        self._set_status("正在同步远端数据...")
        if not auto:
            self._collab_append_result("\n=== 开始同步远端数据集 ===\n")

        def progress(message: str) -> None:
            self.root.after(0, lambda m=message: self._remote_sync_status_var.set(f"远端同步: {m}"))
            if not auto:
                self.root.after(0, lambda m=message: self._collab_append_result(f"{m}\n"))

        def _run() -> None:
            result = sync_remote_datasets(
                self._remote_sync_manifest_url(),
                progress_callback=progress,
            )

            def finish() -> None:
                self._remote_sync_running = False
                if result.get("success"):
                    if result.get("up_to_date"):
                        summary = "远端同步: 已是最新"
                    else:
                        summary = (
                            f"远端同步: 新增 {result.get('inserted', 0)} 条, "
                            f"跳过 {result.get('skipped', 0)} 条"
                        )
                    self._remote_sync_status_var.set(summary)
                    self._set_status(summary)
                    text = (
                        f"同步完成: 检查 {result.get('checked', 0)} 个文件, "
                        f"下载 {result.get('downloaded', 0)} 个, "
                        f"读取 {result.get('read', 0)} 条, "
                        f"新增 {result.get('inserted', 0)} 条, "
                        f"跳过 {result.get('skipped', 0)} 条\n"
                    )
                    if not auto or not result.get("up_to_date"):
                        self._collab_append_result(text)
                    self._refresh_db_status()
                else:
                    errors = result.get("errors") or ["未知错误"]
                    summary = f"远端同步失败: {errors[0]}"
                    self._remote_sync_status_var.set("远端同步: 失败")
                    self._set_status(summary)
                    self._collab_append_result(summary + "\n")
                    if not auto:
                        messagebox.showerror("远端同步失败", errors[0], parent=self.root)

            self.root.after(0, finish)

        threading.Thread(target=_run, daemon=True).start()

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

    def _ask_split_mode(self) -> str | None:
        """Return 'uid', 'oid', or None when the split export dialog is cancelled."""
        dialog = tk.Toplevel(self.root)
        dialog.title("拆分导出")
        dialog.configure(bg=_COLOR_CARD)
        dialog.resizable(False, False)
        dialog.transient(self.root)

        result = tk.StringVar(value="")

        def choose(value: str | None) -> None:
            result.set(value or "")
            dialog.destroy()

        tk.Label(
            dialog,
            text="选择拆分方式",
            font=_FONT_HEADING,
            bg=_COLOR_CARD,
            fg="#333",
        ).pack(padx=24, pady=(18, 6))
        tk.Label(
            dialog,
            text="取消或关闭窗口不会开始导出。",
            font=_FONT_SMALL,
            bg=_COLOR_CARD,
            fg="#777",
        ).pack(padx=24, pady=(0, 14))

        btn_row = tk.Frame(dialog, bg=_COLOR_CARD)
        btn_row.pack(padx=18, pady=(0, 18))
        _btn_primary(btn_row, "按 UID 拆分", lambda: choose("uid")).pack(side=tk.LEFT, padx=4)
        _btn_primary(btn_row, "按 OID 拆分", lambda: choose("oid")).pack(side=tk.LEFT, padx=4)
        _btn_normal(btn_row, "取消", lambda: choose(None)).pack(side=tk.LEFT, padx=4)

        dialog.protocol("WM_DELETE_WINDOW", lambda: choose(None))
        dialog.bind("<Escape>", lambda _e: choose(None))
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        dialog.wait_window()
        value = result.get()
        return value if value in {"uid", "oid"} else None

    def _format_file_size(self, size: int) -> str:
        units = ("B", "KB", "MB", "GB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"

    def _scan_dataset_files(self, directory: str | Path) -> list[dict]:
        base = Path(directory)
        if not base.exists() or not base.is_dir():
            return []
        files: list[dict] = []
        for path in sorted(base.glob("*.jsonl"), key=lambda p: p.name.lower()):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append({
                "path": path,
                "name": path.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        return files

    def _collab_batch_delete(self) -> None:
        """Delete selected JSONL files from the current dataset directory."""
        directory = Path(self._collab_dir_var.get().strip() or "datasets")
        try:
            safe_directory = directory.resolve(strict=False)
        except OSError:
            safe_directory = directory.absolute()
        win = tk.Toplevel(self.root)
        win.title(f"批量删除 JSONL - {directory}")
        win.geometry("760x480")
        win.configure(bg=_COLOR_CARD)
        win.transient(self.root)

        top = tk.Frame(win, bg=_COLOR_CARD)
        top.pack(fill=tk.X, padx=10, pady=(10, 6))
        info_var = tk.StringVar(value="")
        tk.Label(top, textvariable=info_var, font=_FONT_BODY, bg=_COLOR_CARD, fg="#555").pack(side=tk.LEFT)

        tree_frame = tk.Frame(win, bg=_COLOR_CARD)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        columns = ("name", "size", "mtime")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        tree.heading("name", text="文件名")
        tree.heading("size", text="大小")
        tree.heading("mtime", text="修改时间")
        tree.column("name", width=430)
        tree.column("size", width=90, anchor=tk.E)
        tree.column("mtime", width=160)
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        file_map: dict[str, Path] = {}

        def refresh() -> None:
            tree.delete(*tree.get_children())
            file_map.clear()
            files = self._scan_dataset_files(directory)
            total_size = sum(item["size"] for item in files)
            info_var.set(f"{directory} | {len(files)} 个 JSONL | {self._format_file_size(total_size)}")
            for item in files:
                iid = str(item["path"])
                file_map[iid] = item["path"]
                tree.insert("", tk.END, iid=iid, values=(
                    item["name"], self._format_file_size(item["size"]), item["mtime"],
                ))

        def select_all() -> None:
            tree.selection_set(tree.get_children())

        def invert_selection() -> None:
            selected = set(tree.selection())
            for iid in tree.get_children():
                if iid in selected:
                    tree.selection_remove(iid)
                else:
                    tree.selection_add(iid)

        def delete_selected() -> None:
            selected = list(tree.selection())
            if not selected:
                messagebox.showinfo("批量删除", "请先选择要删除的 JSONL 文件。", parent=win)
                return
            paths = []
            for iid in selected:
                path = file_map.get(iid)
                if path is None:
                    continue
                try:
                    resolved = path.resolve(strict=False)
                except OSError:
                    continue
                if resolved.parent == safe_directory and resolved.suffix.lower() == ".jsonl":
                    paths.append(path)
            total_size = sum(path.stat().st_size for path in paths if path.exists())
            ok = messagebox.askyesno(
                "确认删除",
                f"将删除 {len(paths)} 个 JSONL 文件，合计 {self._format_file_size(total_size)}。\n"
                "只会删除当前目录下选中的 .jsonl 文件，不会删除数据库或目录。\n\n确认继续？",
                parent=win,
            )
            if not ok:
                return
            deleted = 0
            errors: list[str] = []
            for path in paths:
                try:
                    resolved = path.resolve(strict=False)
                    if (
                        resolved.parent != safe_directory
                        or path.suffix.lower() != ".jsonl"
                        or not path.is_file()
                    ):
                        continue
                    path.unlink()
                    deleted += 1
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")
            refresh()
            text = f"批量删除完成: {deleted} 个文件, {self._format_file_size(total_size)}\n"
            if errors:
                text += "错误:\n" + "\n".join(f"  {err}" for err in errors[:10]) + "\n"
            self._collab_append_result(text)

        btn_row = tk.Frame(win, bg=_COLOR_CARD)
        btn_row.pack(fill=tk.X, padx=10, pady=(0, 10))
        _btn_normal(btn_row, "全选", select_all).pack(side=tk.LEFT, padx=2)
        _btn_normal(btn_row, "反选", invert_selection).pack(side=tk.LEFT, padx=2)
        _btn_normal(btn_row, "刷新", refresh).pack(side=tk.LEFT, padx=2)
        tk.Button(
            btn_row, text="删除选中", command=delete_selected,
            bg="#e74c3c", fg="white", font=_FONT_BODY,
            cursor="hand2", relief=tk.FLAT, padx=12, pady=3,
        ).pack(side=tk.LEFT, padx=2)
        _btn_normal(btn_row, "关闭", win.destroy).pack(side=tk.RIGHT, padx=2)

        refresh()

    def _collab_split_export(self) -> None:
        """拆分导出，支持取消、Esc 和右上角关闭。"""
        split_by = self._ask_split_mode()
        if split_by is None:
            return
        out_dir = self._collab_dir_var.get().strip() or "datasets"

        self._collab_clear_result()
        self._collab_append_result(f"正在按 {split_by.upper()} 拆分导出到 {out_dir}/ ...\n")
        self._set_status("正在拆分导出...")

        def _run():
            result = ds_export(split_by=split_by, out_dir=out_dir)
            if result["success"]:
                text = (f"拆分导出完成: {result['exported']} 条评论, {len(result['outputs'])} 个文件\n"
                        f"   覆盖 UID: {len(result['uids'])} | 覆盖 OID: {len(result['oids'])}\n")
                for p in result["outputs"][:5]:
                    text += f"   - {p.name}\n"
                if len(result["outputs"]) > 5:
                    text += f"   ... 还有 {len(result['outputs']) - 5} 个\n"
            else:
                text = f"导出失败: {result['error']}\n"
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
