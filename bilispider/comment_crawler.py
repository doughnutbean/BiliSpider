"""
B站评论爬取核心模块。

功能:
  - 通过 UP主 UID 获取其全部视频
  - 对每个视频的评论区进行逐页爬取（含子评论）
  - 以 SQLite 数据库持久化存储
  - 内置频率控制、风控应对、断点续爬

稳定性策略 (优先级高于效率):
  - 请求间隔: 2~4 秒随机延迟,模拟人类浏览行为
  - WBI 密钥: 每 10 次请求刷新一次
  - 风控应对: -352/-799 暂停 30s, -412 暂停 90s
  - 失败重试: 每个请求最多重试 3 次,指数退避
  - 断点续爬: 已完成的视频不会重复爬取
  - 单线程: 避免并发触发风控

⚠️ 风险警告:
  批量爬取评论属于高风险操作。B站对高频请求有严格的风控机制,
  过度爬取可能导致 IP/Cookie 被临时或永久封禁。请务必:
    1. 降低爬取频率 (默认每请求间隔 2~4 秒)
    2. 仅用于学习研究目的
    3. 不要爬取过大量数据
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Iterator, Optional

import requests as _plain_requests

# 尝试使用 curl_cffi 模拟真实浏览器 TLS 指纹,如果不可用则回退到 requests
try:
    from curl_cffi import requests as _curl_requests  # type: ignore
    _CURL_CFFI_AVAILABLE = True
    _IMPERSONATE_TARGET = "chrome120"
except ImportError:
    _curl_requests = None  # type: ignore
    _CURL_CFFI_AVAILABLE = False
    _IMPERSONATE_TARGET = ""

from .login import get_cookie_string
from .wbi import enc_wbi, get_wbi_keys

# ─── 常量 ─────────────────────────────────────────────────────

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_PROJECT_ROOT, "comments.db")

# 请求频率控制 (秒)
_MIN_DELAY = 2.0          # 最小间隔
_MAX_DELAY = 4.0          # 最大间隔
_WBI_REFRESH_TTL = 6 * 3600     # WBI 密钥缓存有效期: 6小时
_WBI_SIGN_FAIL_COOLING = 15.0   # 签名失败后短暂冷却时间(秒)
_MAX_RETRIES = 3           # 每个请求最大重试次数
_RETRY_BASE_DELAY = 5.0    # 重试基础延迟

# 风控暂停时间 (秒)
_PAUSE_ANTI_FREQ = 30.0    # -799 请求频繁
_PAUSE_RISK = 90.0         # -412 风控拦截

# ─── 速率控制器 (自适应风控) ─────────────────────────────────────

class RateController:
    """自适应速率控制器: 监控412事件,动态调整请求延迟。"""

    STATE_NORMAL = "normal"
    STATE_WARNING = "warning"
    STATE_COOLING = "cooling"
    STATE_RECOVERY = "recovery"
    STATE_SNOOZE = "snooze"

    def __init__(self) -> None:
        self._state = self.STATE_NORMAL
        self._412_events: list[dict] = []  # 所有412事件(持久化)
        self._412_archive: list[dict] = [] # 归档的412(不参与计数)
        self._request_times: list[float] = []  # 最近请求时间
        self._success_streak = 0            # 连续成功次数
        self._base_delay = 2.0              # 当前基础延迟
        self._jitter = 2.0                  # 当前抖动范围
        self._total_requests = 0            # 总请求计数
        self._total_success = 0             # 总成功计数
        # 自适应速率调优
        self._auto_tune_enabled = True      # 启用自动提速
        self._stable_since = 0.0             # 上次412后的时间戳
        self._tune_step = 0                  # 提速次数
        self._412_rates: list[float] = []    # 触发412时的速率 (req/min)
        self._global_max_rate = 0.0           # 学习到的安全速率上限 (0=未学习)
        self._tune_interval = 20 * 60        # 稳定20分钟后才尝试提速
        self._tune_delta = 0.3               # 每次提速步长
        # 自适应沉睡
        self._snooze_duration = 600.0         # 沉睡时长(秒), 起始10分钟
        self._snooze_until = 0.0              # 沉睡到的时间戳
        self._cooling_count = 0               # 进入冷却次数
        self._snooze_exit_time = 0.0          # 上次沉睡退出时间
        self._snooze_locked = False           # 是否已锁定最佳沉睡时长
        self._global_snooze_duration = 0.0    # 学习到的最佳沉睡时长

    # ── 公共接口 ──

    def on_request(self) -> float:
        """每次请求前调用,返回应等待的秒数。"""
        self._total_requests += 1
        self._request_times.append(time.time())
        cutoff = time.time() - 300
        self._request_times = [t for t in self._request_times if t > cutoff]
        # 自适应提速检查
        if self._auto_tune_enabled:
            self._try_tune_up()
        return self._base_delay + random.uniform(0, self._jitter)

    def _try_tune_up(self) -> None:
        """如果长时间无412,尝试略微提升速率。"""
        if self._state != self.STATE_NORMAL:
            return
        now = time.time()
        if not self._stable_since:
            self._stable_since = now
            return
        stable_duration = now - self._stable_since
        if stable_duration < self._tune_interval:
            return
        # 沉睡调优: 沉睡后稳定超过20分钟 -> 锁定当前沉睡时长
        if self._snooze_exit_time > 0 and not self._snooze_locked:
            stable_since_snooze = now - self._snooze_exit_time
            if stable_since_snooze > self._tune_interval:
                self._global_snooze_duration = self._snooze_duration
                self._snooze_locked = True
                print(f"  [TUNE] 沉睡时长锁定: {self._global_snooze_duration/60:.0f}min (恢复后稳定{stable_since_snooze/60:.0f}min)")
                self._snooze_exit_time = 0.0
        # 已学习到安全速率上限,将延迟锁定在安全值上
        if self._global_max_rate > 0:
            safe_delay = 60.0 / self._global_max_rate
            if self._base_delay < safe_delay:
                self._base_delay = safe_delay
                self._jitter = safe_delay * 0.5
                print(f"  [TUNE] 延迟已锁定到安全值: {self._base_delay:.1f}s (≤{self._global_max_rate:.1f}rpm)")
            return
        # 减速: 降低延迟 = 提高速率
        new_base = max(0.5, self._base_delay - self._tune_delta)
        new_jitter = max(0.3, self._jitter - 0.2)
        if new_base != self._base_delay:
            self._base_delay = new_base
            self._jitter = new_jitter
            self._tune_step += 1
            self._stable_since = now  # 重置计时器
            print(f"  [TUNE] 提速 #{self._tune_step}: 延迟降为 {self._base_delay:.1f}s~{self._base_delay+self._jitter:.1f}s")

    def _compute_current_rate(self) -> float:
        """计算当前请求速率 (req/min),基于最近5分钟的请求数。"""
        if not self._request_times:
            return 0.0
        now = time.time()
        recent = [t for t in self._request_times if now - t <= 60]
        if not recent:
            return 0.0
        return len(recent) / ((now - recent[0]) / 60) if len(recent) > 1 else 60.0

    def on_success(self) -> None:
        """请求成功后调用,累积恢复进度。"""
        self._total_success += 1
        self._success_streak += 1
        if self._state != self.STATE_NORMAL and self._success_streak >= 10:
            self._enter_recovery()

    def on_412(self, url: str, api_type: str) -> str:
        """遇到412时调用,返回状态变化描述。"""
        now = time.time()
        # 提取接口路径 (不含参数)
        api_path = url.split("?")[0] if "?" in url else url
        api_name = api_path.rsplit("/", 1)[-1] if "/" in api_path else api_path

        # 计算距上次412的间隔
        last_412 = self._412_events[-1]["time"] if self._412_events else None
        interval_since_last = round(now - last_412, 1) if last_412 else None

        entry = {
            "time": now,
            "time_str": time.strftime("%H:%M:%S", time.localtime(now)),
            "url": api_path[:80],
            "api": api_type,
            "api_name": api_name,
            "state_before": self._state,
            "total_requests": self._total_requests,
            "interval_since_last_412": interval_since_last,
            "recent_5min_requests": len(self._request_times),
        }
        self._412_events.append(entry)
        self._412_archive.append(entry)

        # 只保留最近30分钟的412用于速率控制决策
        recent_412 = [e for e in self._412_events if now - e["time"] < 1800]
        self._412_events = recent_412
        recent_count = len(recent_412)
        self._success_streak = 0
        self._stable_since = 0.0  # 重置稳定计时器

        # 记录触发412时的速率,学习安全上限
        if self._auto_tune_enabled:
            current_rate = self._compute_current_rate()
            if current_rate > 0:
                self._412_rates.append(current_rate)
                # 沉睡调优: 沉睡后很快又412 -> 沉睡时间不够
                if self._snooze_exit_time > 0 and not self._snooze_locked:
                    since_snooze = now - self._snooze_exit_time
                    if since_snooze < self._tune_interval:
                        self._snooze_duration *= 1.5
                        print(f"  [TUNE] 沉睡时长不足(恢复后{since_snooze/60:.0f}min就412), 增至{self._snooze_duration/60:.0f}min")
                entry["trigger_rate"] = round(current_rate, 1)
                print(f"  [TUNE] 412触发时速率: {current_rate:.1f} req/min")
                # 收集足够样本后,取最小触发速率,在下方设安全上限
                if len(self._412_rates) >= 3:
                    min_trigger_rate = min(self._412_rates)
                    safe_rate = min_trigger_rate * 0.85  # 取最小值的85%
                    if self._global_max_rate == 0 or safe_rate < self._global_max_rate:
                        self._global_max_rate = safe_rate
                        print(f"  [TUNE] 学习到安全速率上限: {self._global_max_rate:.1f} req/min "
                              f"(最小触发={min_trigger_rate:.1f} × 0.85)")

        if recent_count >= 3:
            return self._enter_cooling(recent_count)
        elif recent_count == 2:
            return self._enter_warning(recent_count)
        else:
            return self._enter_warning(recent_count)

    def get_state(self) -> str:
        return self._state

    def get_delay_range(self) -> tuple[float, float]:
        return (self._base_delay, self._base_delay + self._jitter)

    def get_412_count(self) -> int:
        return len(self._412_events)

    def get_412_log(self) -> list[dict]:
        return self._412_events[-10:]  # 最近10条

    def dump_report(self) -> str:
        """输出412触发画像复盘报告。"""
        if not self._412_archive:
            return "[RATE] 本次会话无412事件"

        lines = ["", "=" * 60, "  412 风控事件复盘报告", "=" * 60]

        # ── 总量统计 ──
        total_412 = len(self._412_archive)
        rate = total_412 / max(self._total_requests, 1) * 100
        lines.append(f"  总请求: {self._total_requests}  |  成功: {self._total_success}")
        lines.append(f"  412次数: {total_412}  |  412率: {rate:.1f}%")

        # ── 接口分布 ──
        api_counter: dict[str, int] = {}
        for e in self._412_archive:
            name = e["api_name"]
            api_counter[name] = api_counter.get(name, 0) + 1
        lines.append(f"\n  ── 412 接口分布 ──")
        for name, cnt in sorted(api_counter.items(), key=lambda x: -x[1]):
            pct = cnt / total_412 * 100
            bar = "█" * int(pct / 5 + 0.5)
            lines.append(f"    {name:20s} {cnt:3d}次 ({pct:5.1f}%) {bar}")

        # ── 时间分布 ──
        hour_buckets: dict[int, int] = {}
        for e in self._412_archive:
            h = time.localtime(e["time"]).tm_hour
            hour_buckets[h] = hour_buckets.get(h, 0) + 1
        if len(hour_buckets) > 1:
            lines.append(f"\n  ── 412 时段分布 ──")
            for h in sorted(hour_buckets):
                lines.append(f"    {h:02d}:00  {hour_buckets[h]}次")

        # ── 间隔分析 ──
        intervals = [
            e["interval_since_last_412"]
            for e in self._412_archive
            if e["interval_since_last_412"] is not None
        ]
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            min_interval = min(intervals)
            lines.append(f"\n  ── 412 触发间隔 ──")
            lines.append(f"    平均间隔: {avg_interval:.1f}s")
            lines.append(f"    最短间隔: {min_interval:.1f}s")
            # 聚簇检测
            short_clusters = [i for i in intervals if i < 30]
            if short_clusters:
                lines.append(f"    密集(间隔<30s): {len(short_clusters)}次 → 可能是频率型风控")

        # ── 状态转换链路 ──
        state_changes: list[str] = []
        for e in self._412_archive:
            state_changes.append(f"{e['state_before']}→")
        lines.append(f"\n  ── 状态转换链 ──")
        lines.append(f"    {' → '.join(state_changes[:20])}")

        # ── 自适应调速 ──
        if self._412_rates:
            lines.append(f"\n  ── 自适应调速 ──")
            lines.append(f"    提速次数: {self._tune_step}")
            lines.append(f"    触发速率样本: {[round(r,1) for r in self._412_rates]}")
            lines.append(f"    最小触发: {min(self._412_rates):.1f} req/min")
            if self._global_max_rate > 0:
                lines.append(f"    安全上限: {self._global_max_rate:.1f} req/min (延迟 ≥ {60/self._global_max_rate:.1f}s)")

        # ── 诊断结论 ──
        lines.append(f"\n  ── 诊断 ──")
        if rate > 5:
            if short_clusters and len(short_clusters) > 3:
                lines.append("    结论: 频率触发型 — 请求过于密集")
                lines.append("    建议: 增加基础延迟,减少并发")
            else:
                lines.append("    结论: 请求指纹标记型 — Cookie/UA/代理可能被标记")
                lines.append("    建议: 更换代理,刷新Cookie,多样化UA")
        elif api_counter.get("reply", 0) > api_counter.get("search", 0) * 2:
            lines.append("    结论: 接口敏感型 — 评论接口(reply)更易触发412")
            lines.append("    建议: 对reply接口使用更长延迟,减少子评论爬取范围")
        else:
            lines.append("    结论: 偶发型 — 控制尚可,维持现有策略")

        lines.append("=" * 60)
        return "\n".join(lines)

    def _enter_warning(self, count: int) -> str:
        self._state = self.STATE_WARNING
        self._base_delay = 5.0 + count * 2
        self._jitter = 5.0
        msg = f"[RATE] 进入警戒模式 (412x{count}) — 延迟={self._base_delay}s~{self._base_delay+self._jitter}s"
        print(f"  {msg}")
        return msg

    def _enter_cooling(self, count: int) -> str:
        self._state = self.STATE_COOLING
        self._base_delay = 30.0 + count * 5
        self._jitter = 30.0
        msg = f"[RATE] 进入冷却模式 (412x{count}) — 延迟={self._base_delay}s~{self._base_delay+self._jitter}s"
        print(f"  {msg}")
        return msg

    def _enter_recovery(self) -> str:
        self._state = self.STATE_RECOVERY
        # 逐步恢复: 每成功5次降低一次延迟
        self._base_delay = max(2.0, self._base_delay - 1.0)
        self._jitter = max(1.0, self._jitter - 1.0)
        if self._base_delay <= 2.5:
            self._state = self.STATE_NORMAL
            self._base_delay = 2.0
            self._jitter = 2.0
            msg = "[RATE] 恢复正常模式"
        else:
            msg = f"[RATE] 恢复模式 — 延迟={self._base_delay}s~{self._base_delay+self._jitter}s"
        print(f"  {msg}")
        return msg

    def _enter_snooze(self) -> None:
        """进入沉睡状态,时长自动调优。"""
        self._state = self.STATE_SNOOZE
        self._cooling_count += 1
        # 已锁定: 用最佳时长; 否则: 自适应倍增
        if self._snooze_locked and self._global_snooze_duration > 0:
            self._snooze_duration = self._global_snooze_duration
        else:
            self._snooze_duration = 600.0 * (2 ** (self._cooling_count - 1))
        self._base_delay = 2.0
        self._jitter = 2.0

    def _exit_snooze(self) -> None:
        """退出沉睡,恢复正常模式。"""
        self._state = self.STATE_NORMAL
        self._snooze_exit_time = time.time()
        self._stable_since = time.time()
        self._success_streak = 0
        self._412_events = []


# B站评论分页
_PAGE_SIZE = 20            # 每页条数
# 页数无上限,由B站API自然停止(返回空页时break)

# 代理配置 (支持 HTTP/HTTPS 代理轮换)
# 格式: ["http://host:port", "https://host:port", ...]
# 留空则直连
_PROXY_LIST: list[str] = []

# User-Agent 池 (随机轮换,模拟多浏览器)
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


# ─── 数据模型 ──────────────────────────────────────────────────

@dataclass
class CommentRecord:
    """一条评论的数据模型。"""
    rpid: int
    oid: int
    type: int          # 1=视频评论
    mid: int           # 发布者 UID
    parent: int        # 父评论 rpid (0 表示一级评论)
    root: int          # 根评论 rpid (0 表示一级评论)
    ctime: int         # 发布时间 (Unix 时间戳)
    message: str       # 评论内容
    like_count: int    # 点赞数
    sub_count: int     # 子评论总数
    crawl_time: int    # 爬取时间 (Unix 时间戳)


# ─── SQLite 数据库管理 ─────────────────────────────────────────

class CommentDatabase:
    """SQLite 评论数据库,支持增量写入和断点续爬。"""

    def __init__(self, db_path: str = _DB_PATH) -> None:
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    # ── 上下文管理 ──

    def __enter__(self) -> CommentDatabase:
        self.open()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def open(self) -> None:
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")        # 写前日志,性能更好
        self._conn.execute("PRAGMA synchronous=NORMAL")       # 平衡安全与速度
        self._conn.execute("PRAGMA busy_timeout=5000")        # 5秒忙等
        self._create_tables()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("数据库未打开,请使用 with CommentDatabase() as db:")
        return self._conn

    # ── 建表 ──

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS comments (
                rpid        INTEGER NOT NULL,
                oid         INTEGER NOT NULL,
                type        INTEGER NOT NULL DEFAULT 1,
                mid         INTEGER NOT NULL,
                parent      INTEGER NOT NULL DEFAULT 0,
                root        INTEGER NOT NULL DEFAULT 0,
                ctime       INTEGER NOT NULL,
                message     TEXT,
                like_count  INTEGER DEFAULT 0,
                sub_count   INTEGER DEFAULT 0,
                crawl_time  INTEGER NOT NULL,
                PRIMARY KEY (rpid, oid, type)
            );

            CREATE TABLE IF NOT EXISTS crawl_progress (
                oid             INTEGER NOT NULL,
                type            INTEGER NOT NULL DEFAULT 1,
                root_pages_done INTEGER NOT NULL DEFAULT 0,
                sub_progress    TEXT NOT NULL DEFAULT '{}',
                last_crawl      INTEGER,
                status          TEXT NOT NULL DEFAULT 'pending',
                total_root      INTEGER DEFAULT 0,
                total_subs      INTEGER DEFAULT 0,
                PRIMARY KEY (oid, type)
            );
        """)

    # ── 评论写入 ──

    def insert_comment(self, c: CommentRecord) -> None:
        """插入或忽略一条评论 (PRIMARY KEY 冲突则跳过)。"""
        self.conn.execute(
            """INSERT OR IGNORE INTO comments
               (rpid, oid, type, mid, parent, root, ctime, message,
                like_count, sub_count, crawl_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (c.rpid, c.oid, c.type, c.mid, c.parent, c.root,
             c.ctime, c.message, c.like_count, c.sub_count, c.crawl_time),
        )

    def insert_comments_batch(self, records: list[CommentRecord]) -> int:
        """批量插入评论,返回实际插入条数。"""
        count = 0
        with self.conn:  # 事务
            for c in records:
                self.conn.execute(
                    """INSERT OR IGNORE INTO comments
                       (rpid, oid, type, mid, parent, root, ctime, message,
                        like_count, sub_count, crawl_time)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (c.rpid, c.oid, c.type, c.mid, c.parent, c.root,
                     c.ctime, c.message, c.like_count, c.sub_count, c.crawl_time),
                )
                if self.conn.total_changes > count:
                    count += 1
            return count

    # ── 进度管理 ──

    def get_progress(self, oid: int, ctype: int = 1) -> dict:
        """获取某个评论区的爬取进度。"""
        row = self.conn.execute(
            "SELECT * FROM crawl_progress WHERE oid=? AND type=?",
            (oid, ctype),
        ).fetchone()
        if row is None:
            return {"root_pages_done": 0, "sub_progress": "{}", "status": "pending",
                    "total_root": 0, "total_subs": 0}
        return {
            "root_pages_done": row[2],
            "sub_progress": row[3],
            "last_crawl": row[4],
            "status": row[5],
            "total_root": row[6] or 0,
            "total_subs": row[7] or 0,
        }

    def upsert_progress(self, oid: int, ctype: int, **kwargs) -> None:
        """更新或插入爬取进度。"""
        existing = self.conn.execute(
            "SELECT 1 FROM crawl_progress WHERE oid=? AND type=?",
            (oid, ctype),
        ).fetchone()

        now = int(time.time())
        if existing:
            sets = []
            vals = []
            for key in ("root_pages_done", "sub_progress", "status",
                         "total_root", "total_subs"):
                if key in kwargs:
                    sets.append(f"{key}=?")
                    vals.append(kwargs[key])
            sets.append("last_crawl=?")
            vals.append(now)
            vals.extend([oid, ctype])
            self.conn.execute(
                f"UPDATE crawl_progress SET {', '.join(sets)} WHERE oid=? AND type=?",
                vals,
            )
        else:
            self.conn.execute(
                """INSERT INTO crawl_progress
                   (oid, type, root_pages_done, sub_progress, last_crawl, status, total_root, total_subs)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (oid, ctype,
                 kwargs.get("root_pages_done", 0),
                 kwargs.get("sub_progress", "{}"),
                 now,
                 kwargs.get("status", "pending"),
                 kwargs.get("total_root", 0),
                 kwargs.get("total_subs", 0)),
            )

    def get_stats(self) -> dict:
        """获取数据库统计信息。"""
        total = self.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        root = self.conn.execute("SELECT COUNT(*) FROM comments WHERE parent=0").fetchone()[0]
        sub = self.conn.execute("SELECT COUNT(*) FROM comments WHERE parent>0").fetchone()[0]
        vids = self.conn.execute("SELECT COUNT(*) FROM crawl_progress WHERE status='done'").fetchone()[0]
        return {"total": total, "root": root, "sub": sub, "videos_done": vids}


# ─── 评论爬取引擎 ──────────────────────────────────────────────

class CommentCrawler:
    """B站评论爬取引擎,带完整的频率控制和风控应对。"""

    def __init__(self, db_path: str = _DB_PATH) -> None:
        self.db = CommentDatabase(db_path)
        self._session = None  # 在 setup() 中创建
        self._cookie = ""
        self._img_key = ""
        self._sub_key = ""
        self._wbi_ts = 0.0
        self._cancelled = False
        # 速率控制器
        self._rate_ctrl = RateController()
        # 时间过滤 (Unix 时间戳,0 表示不过滤)
        self._since_ts: int = 0   # 只爬此时间之后的评论
        self._until_ts: int = 0   # 只爬此时间之前的评论
        self._max_videos: int = 0 # 最多爬取视频数 (0=不限)
        # 代理轮换
        self._proxy_index: int = 0
        self._proxies: list[str] = []
        # TLS 伪装
        self._tls_engine: str = ""  # "curl_cffi" 或 "requests"
        # 进度回调
        self._progress_cb = None

    # ── 初始化 ──

    def configure(
        self,
        since_ts: int = 0,
        until_ts: int = 0,
        max_videos: int = 0,
        proxies: list[str] | None = None,
        progress_callback=None,
        rate_base: float = 2.0,
        rate_jitter: float = 2.0,
        snooze_minutes: int = 10,
        auto_tune: bool = True,
        auto_snooze: bool = True,
    ) -> None:
        """
        配置爬取参数 (需在 setup() 之前调用)。

        参数:
            since_ts: 只爬取此 Unix 时间戳之后的评论 (0=不限)
            until_ts: 只爬取此 Unix 时间戳之前的评论 (0=不限)
            max_videos: 最多爬取视频数 (0=不限)
            proxies: 代理地址列表,如 ["http://127.0.0.1:7890"] (空=直连)
            progress_callback: 进度回调 fn(current, total, label)
        """
        self._since_ts = since_ts
        self._until_ts = until_ts
        self._max_videos = max_videos
        self._proxies = proxies or []
        self._progress_cb = progress_callback
        self._cfg_rate_base = rate_base
        self._cfg_rate_jitter = rate_jitter
        self._cfg_snooze_min = snooze_minutes
        self._cfg_auto_tune = auto_tune
        self._cfg_auto_snooze = auto_snooze

    def _is_comment_in_range(self, ctime: int) -> bool:
        """检查评论时间是否在设定的范围内。"""
        if self._since_ts and ctime < self._since_ts:
            return False
        if self._until_ts and ctime > self._until_ts:
            return False
        return True

    def setup(self) -> bool:
        """初始化: 创建 TLS 伪装会话 + 加载 Cookie + 获取 WBI 密钥。"""
        self._cookie = get_cookie_string()
        if not self._cookie:
            print("[X] 未找到 Cookie,请先运行 python login.py 扫码登录")
            return False

        # ── 创建会话: 优先 curl_cffi (Chrome 120 TLS 指纹), 回退 plain requests ──
        if _CURL_CFFI_AVAILABLE:
            self._session = _curl_requests.Session(impersonate=_IMPERSONATE_TARGET)
            self._tls_engine = "curl_cffi"
            print(f"[*] TLS 伪装已启用: curl_cffi impersonate={_IMPERSONATE_TARGET}")
        else:
            self._session = _plain_requests.Session()
            self._tls_engine = "requests"
            print("[!] curl_cffi 未安装,使用普通 requests (TLS 指纹可能被识别)")

        # ── 代理池: 优先 ProxyPool, 其次手动配置, 最后 flclash 自动检测 ──
        from .proxy_pool import get_pool
        self._proxy_pool = get_pool()

        # 自动检测 flclash (如果池中还没有代理)
        if self._proxy_pool.count() == 0 and not self._proxies:
            self._proxy_pool.auto_detect_flclash()

        # 把手动配置的代理也加入池
        if self._proxies:
            self._proxy_pool.add_manuals(self._proxies)

        pool_count = self._proxy_pool.count()
        if pool_count > 0:
            print(f"[*] 代理池就绪: {pool_count} 个代理")
            self._rotate_proxy()
        else:
            print("[*] 无可用代理,直连")

        print("[*] 获取 WBI 签名密钥...")
        try:
            self._img_key, self._sub_key = get_wbi_keys()
        except Exception as e:
            print(f"[X] 获取 WBI 密钥失败: {e}")
            return False

        self._session.headers.update({
            "User-Agent": random.choice(_UA_POOL),
            "Cookie": self._cookie,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": "https://www.bilibili.com",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        })
        dmin, dmax = self._rate_ctrl.get_delay_range()
        # 应用用户配置的速率参数
        self._rate_ctrl._base_delay = self._cfg_rate_base
        self._rate_ctrl._jitter = self._cfg_rate_jitter
        self._rate_ctrl._snooze_duration = self._cfg_snooze_min * 60
        self._rate_ctrl._auto_tune_enabled = self._cfg_auto_tune
        dmin, dmax = self._rate_ctrl.get_delay_range()
        print(f"[*] 速率控制: {self._rate_ctrl.get_state()} 模式, 延迟 {dmin:.1f}s~{dmax:.1f}s, 沉睡 {self._cfg_snooze_min}min, 自动提速={'ON' if self._cfg_auto_tune else 'OFF'}")
        return True

    def _rotate_proxy(self) -> None:
        """轮换到下一个代理 (优先从 ProxyPool 获取)。"""
        proxy = None
        if hasattr(self, '_proxy_pool') and self._proxy_pool.count() > 0:
            proxy = self._proxy_pool.get_proxy()
        elif self._proxies:
            proxy = self._proxies[self._proxy_index % len(self._proxies)]
            self._proxy_index += 1
        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}

    def _rotate_ua(self) -> None:
        """随机更换 User-Agent。"""
        self._session.headers["User-Agent"] = random.choice(_UA_POOL)

    def cancel(self) -> None:
        """取消爬取。"""
        self._cancelled = True

    # ── 请求控制 ──

    def _maybe_refresh_wbi(self) -> None:
        """
        WBI 密钥刷新策略:
          - 正常状态: 每 6 小时自动刷新 (时间缓存)
          - 异常状态: -352 时由 _signed_get 调用 _force_refresh_wbi()
        """
        now = time.time()
        if not self._wbi_ts:
            self._wbi_ts = now
            return
        if (now - self._wbi_ts) > _WBI_REFRESH_TTL:
            self._force_refresh_wbi()

    def _force_refresh_wbi(self) -> None:
        """强制刷新 WBI 密钥并更新时间戳。"""
        try:
            self._img_key, self._sub_key = get_wbi_keys()
            self._wbi_ts = time.time()
            print("[*] WBI 密钥已刷新")
        except Exception as e:
            print(f"[!] WBI 密钥刷新失败: {e}")

    def _wake_up(self) -> None:
        """沉睡后唤醒: 刷新WBI密钥、验证Cookie、重设代理。"""
        print("  [*] 唤醒检查: 刷新WBI密钥...")
        self._force_refresh_wbi()
        print("  [*] 唤醒检查: 刷新Cookie...")
        from .login import get_cookie_string
        new_cookie = get_cookie_string()
        if new_cookie and new_cookie != self._cookie:
            self._cookie = new_cookie
            self._session.headers["Cookie"] = new_cookie
            print("  [*] Cookie已更新")
        else:
            print("  [*] Cookie无变化")
        print("  [*] 唤醒检查: 轮换代理...")
        self._rotate_ua()
        if self._proxies or (hasattr(self, '_proxy_pool') and self._proxy_pool.count() > 0):
            self._rotate_proxy()

    def _delay(self, extra: float = 0.0) -> None:
        """自适应延迟,根据风控状态动态调整。"""
        base = self._rate_ctrl.on_request()
        time.sleep(base + extra)

    def _signed_get(self, url: str, params: dict, referer: str = "https://www.bilibili.com/") -> Optional[dict]:
        """
        发起带 WBI 签名的 GET 请求,内置重试和风控处理。

        返回:
            成功返回 JSON dict,失败返回 None
        """
        for attempt in range(_MAX_RETRIES):
            if self._cancelled:
                return None

            self._maybe_refresh_wbi()
            signed = enc_wbi(params, self._img_key, self._sub_key)
            self._session.headers["Referer"] = referer
            # 每次请求随机轮换 UA & 代理,增加伪装度
            self._rotate_ua()
            if self._proxies:
                self._rotate_proxy()

            try:
                resp = self._session.get(url, params=signed, timeout=15)
                # HTTP 412 = 风控拦截 → 交给速率控制器治理
                if resp.status_code == 412:
                    api_type = "reply" if "/reply" in url else "search" if "search" in url else "other"
                    self._rate_ctrl.on_412(url, api_type)
                    state = self._rate_ctrl.get_state()
                    # 冷却模式 → 进入自适应沉睡,自动恢复
                    if state == RateController.STATE_COOLING:
                        self._rate_ctrl._enter_snooze()
                        snooze_s = self._rate_ctrl._snooze_duration
                        print(f"  [!] 连续412 — 进入沉睡 {snooze_s/60:.0f} 分钟,自动恢复...")
                        time.sleep(snooze_s)
                        self._rate_ctrl._exit_snooze()
                        self._wake_up()
                        print(f"  [*] 沉睡结束,恢复爬取")
                        return None
                    delay = self._rate_ctrl.on_request()
                    time.sleep(delay)
                    continue

                resp.raise_for_status()
                data = resp.json()
                code = data.get("code", 0)

                if code == 0:
                    self._rate_ctrl.on_success()
                    return data
                elif code in (-352,):
                    # -352: 签名失效 → 强制刷新WBI密钥 + 短暂冷却
                    self._rate_ctrl._success_streak = 0
                    print(f"  [!] API -352 签名失效,强制刷新WBI密钥后冷却 {_WBI_SIGN_FAIL_COOLING}s...")
                    self._force_refresh_wbi()
                    time.sleep(_WBI_SIGN_FAIL_COOLING)
                elif code in (-799,):
                    # -799: 请求过于频繁
                    wait = _PAUSE_ANTI_FREQ * (attempt + 1)
                    print(f"  [!] API -799 请求频繁,暂停 {wait}s...")
                    time.sleep(wait)
                elif code == -404:
                    # 评论区不存在
                    return None
                else:
                    print(f"  [!] API 错误 code={code}: {data.get('message', '')}")
                    time.sleep(_RETRY_BASE_DELAY * (attempt + 1))

            except Exception as e:
                # curl_cffi 和 requests 的异常类型不同,统一捕获
                err_msg = str(e).lower()
                if "timeout" in err_msg:
                    print(f"  [!] 请求超时,第 {attempt + 1} 次重试")
                else:
                    print(f"  [!] 网络异常: {e},第 {attempt + 1} 次重试")
                time.sleep(_RETRY_BASE_DELAY * (attempt + 1))

        print(f"  [X] 请求失败,已达最大重试次数 ({_MAX_RETRIES})")
        return None

    # ── 获取 UP 主视频列表 ──

    def get_user_videos(self, uid: str) -> list[dict]:
        """
        获取 UP 主全部视频的 aid 列表。

        返回:
            [{"aid": ..., "bvid": ..., "title": ...}, ...]
        """
        videos: list[dict] = []
        page = 1

        while page <= 50:  # 最多获取 50 页 (50x30=1500个视频)
            if self._cancelled:
                break

            params = {
                "mid": uid, "ps": 30, "tid": 0, "pn": page,
                "keyword": "", "order": "pubdate", "platform": "web",
                "web_location": 1550101, "order_avoided": "true",
            }
            referer = f"https://space.bilibili.com/{uid}/video"

            result = self._signed_get(
                "https://api.bilibili.com/x/space/wbi/arc/search",
                params, referer=referer,
            )

            if result is None:
                break

            vlist = result["data"]["list"]["vlist"]
            if not vlist:
                break

            for v in vlist:
                videos.append({
                    "aid": v["aid"], "bvid": v["bvid"], "title": v["title"],
                })

            total = result["data"]["page"]["count"]
            print(f"  第{page}页: 获取 {len(vlist)} 个视频 (累计 {len(videos)}/{total})")
            page += 1
            self._delay()

        return videos

    # ── 爬取一级评论 ──

    def crawl_root_comments(self, oid: int, ctype: int = 1) -> int:
        """
        爬取某个评论区的一级评论 (逐页)。

        参数:
            oid: 评论区 ID (视频 = aid)
            ctype: 评论区类型 (1 = 视频)

        返回:
            实际爬取的一级评论数
        """
        progress = self.db.get_progress(oid, ctype)
        if progress["status"] == "done":
            print(f"    aid={oid}: 已完成,跳过")
            return progress.get("total_root", 0)

        start_page = progress["root_pages_done"] + 1
        crawled = 0
        page_num = start_page

        while True:
            if self._cancelled:
                break

            params = {
                "type": ctype, "oid": oid, "pn": page_num,
                "ps": _PAGE_SIZE, "sort": 2,
            }
            referer = f"https://www.bilibili.com/video/av{oid}/"

            result = self._signed_get(
                "https://api.bilibili.com/x/v2/reply",
                params, referer=referer,
            )

            if result is None:
                self.db.upsert_progress(oid, ctype,
                    root_pages_done=page_num - 1,
                    status="error",
                    total_root=crawled,
                )
                break

            replies = result["data"].get("replies", [])
            if not replies:
                # 没有更多评论了
                self.db.upsert_progress(oid, ctype,
                    root_pages_done=page_num,
                    status="done",
                    total_root=crawled,
                )
                break

            # 入库当前页评论 (带时间过滤)
            now = int(time.time())
            records = []
            oldest_ctime = None
            for r in replies:
                ctime = r["ctime"]
                oldest_ctime = ctime  # sort=2 按时间降序,最后一条最老
                # 时间过滤: 跳过不在范围内的评论
                if not self._is_comment_in_range(ctime):
                    continue
                records.append(CommentRecord(
                    rpid=r["rpid"], oid=oid, type=ctype,
                    mid=r["mid"], parent=0, root=0,
                    ctime=ctime,
                    message=r.get("content", {}).get("message", ""),
                    like_count=r.get("like", 0),
                    sub_count=r.get("rcount", 0),
                    crawl_time=now,
                ))

            # 如果整页评论都早于 since_ts,且 since_ts 已设置,
            # 则后续页必定更早,可以提前终止 (节省请求)
            if (self._since_ts and oldest_ctime is not None
                    and oldest_ctime < self._since_ts):
                print(f"    aid={oid}: 本页评论已早于截止时间,跳过后续页面")
                self.db.upsert_progress(oid, ctype,
                    root_pages_done=page_num,
                    status="done",
                    total_root=crawled,
                )
                break

            inserted = self.db.insert_comments_batch(records)
            crawled += len(records)

            total = result["data"]["page"].get("acount", result["data"]["page"]["count"])
            print(f"    aid={oid} 评论 p{page_num}: "
                  f"获取 {len(records)} 条 (累计 {crawled}/{total})")

            self.db.upsert_progress(oid, ctype,
                root_pages_done=page_num,
                total_root=crawled,
                status="crawling",
            )

            self._delay()
            page_num += 1

        # 正常结束 (API返回空页 or 时间截断)
        self.db.upsert_progress(oid, ctype,
            root_pages_done=page_num,
            status="done",
            total_root=crawled,
        )

        return crawled

    # ── 爬取子评论 ──

    def crawl_sub_comments(self, oid: int, ctype: int = 1) -> int:
        """
        爬取某评论区中所有有子评论的一级评论的子评论。

        流程:
          1. 从数据库中找出该 oid 下所有 sub_count > 0 的一级评论
          2. 逐个获取其子评论 (逐页)
          3. 已完成的根评论跳过

        返回:
            实际爬取的子评论数
        """
        # 获取待爬子评论的一级评论
        rows = self.db.conn.execute(
            """SELECT rpid, sub_count FROM comments
               WHERE oid=? AND type=? AND parent=0 AND sub_count > 0""",
            (oid, ctype),
        ).fetchall()

        if not rows:
            return 0

        # 读取子评论爬取进度
        progress = self.db.get_progress(oid, ctype)
        try:
            sub_progress: dict = json.loads(progress["sub_progress"])
        except (json.JSONDecodeError, TypeError):
            sub_progress = {}

        # 统计已完成的根评论数
        already_done = sum(
            1 for rpid, sc in rows
            if str(rpid) in sub_progress and sub_progress[str(rpid)] >= sc
        )
        pending = len(rows) - already_done

        if pending == 0:
            print(f"    aid={oid} 子评论: {len(rows)} 条根评论均已爬完,跳过")
            return 0

        print(f"    aid={oid} 子评论: 共{len(rows)}条,已爬{already_done}条,待爬{pending}条")

        root_processed = 0
        total_crawled = 0
        for root_rpid, sub_count in rows:
            root_rpid_str = str(root_rpid)
            if root_rpid_str in sub_progress and sub_progress[root_rpid_str] >= sub_count:
                continue  # 已经爬完

            root_processed += 1
            if root_processed % 5 == 0 or root_processed == 1:
                print(f"    aid={oid} 子评论: 处理第 {root_processed}/{pending} 条根评论...")

            start_page = (sub_progress.get(root_rpid_str, 0) // _PAGE_SIZE) + 1
            page_num = start_page

            while True:
                if self._cancelled:
                    break

                params = {
                    "type": ctype, "oid": oid, "pn": page_num,
                    "ps": _PAGE_SIZE, "root": root_rpid,
                }
                referer = f"https://www.bilibili.com/video/av{oid}/"

                result = self._signed_get(
                    "https://api.bilibili.com/x/v2/reply/reply",
                    params, referer=referer,
                )

                if result is None:
                    self._delay()
                    break

                sub_replies = result["data"].get("replies", [])
                if not sub_replies:
                    break

                now = int(time.time())
                records = []
                oldest_ctime = None
                for r in sub_replies:
                    ctime = r["ctime"]
                    oldest_ctime = ctime
                    # 时间过滤: 跳过不在范围内的子评论
                    if not self._is_comment_in_range(ctime):
                        continue
                    records.append(CommentRecord(
                        rpid=r["rpid"], oid=oid, type=ctype,
                        mid=r["mid"],
                        parent=r.get("parent", root_rpid),
                        root=root_rpid,
                        ctime=ctime,
                        message=r.get("content", {}).get("message", ""),
                        like_count=r.get("like", 0),
                        sub_count=0,  # 二级评论不再有子评论
                        crawl_time=now,
                    ))

                # 如果整页都早于截止时间,提前终止
                if (self._since_ts and oldest_ctime is not None
                        and oldest_ctime < self._since_ts and not records):
                    break

                self.db.insert_comments_batch(records)
                total_crawled += len(records)

                sub_progress[root_rpid_str] = page_num * _PAGE_SIZE
                self.db.upsert_progress(oid, ctype, sub_progress=json.dumps(sub_progress))

                if len(sub_replies) < _PAGE_SIZE:
                    break  # 最后一页

                self._delay(extra=1.0)  # 子评论页间延迟
                page_num += 1

            # 标记该根评论子评论完成
            sub_progress[root_rpid_str] = sub_count
            self.db.upsert_progress(oid, ctype, sub_progress=json.dumps(sub_progress))
            # 根评论之间加延迟,避免子评论请求过于密集触发风控
            self._delay()

        # 更新总子评论数
        total_subs = self.db.conn.execute(
            "SELECT COUNT(*) FROM comments WHERE oid=? AND type=? AND parent>0",
            (oid, ctype),
        ).fetchone()[0]
        self.db.upsert_progress(oid, ctype, total_subs=total_subs)

        if total_crawled:
            print(f"    aid={oid} 子评论: 完成,新增 {total_crawled} 条子评论")
        return total_crawled

    # ── 主流程: 按 UID 爬取全部评论 ──

    def crawl_by_uid(self, uid: str) -> dict:
        """
        对指定 UP 主执行完整的评论爬取流程。

        流程:
          1. 获取 UP 主全部视频
          2. 对每个视频爬取一级评论
          3. 对每个视频爬取子评论

        返回:
            统计信息 dict
        """
        db = self.db
        db.open()

        try:
            print(f"\n{'='*50}")
            print(f"  开始爬取 UP 主 UID={uid} 的评论")
            print(f"{'='*50}")

            print("\n[1/3] 获取视频列表...")
            videos = self.get_user_videos(uid)
            print(f"  共获取 {len(videos)} 个视频")

            total_root = 0
            total_subs = 0

            for idx, v in enumerate(videos, 1):
                if self._cancelled:
                    print("  [!] 爬取已取消")
                    break
                if self._max_videos > 0 and idx > self._max_videos:
                    print(f"  [!] 已达到最大视频数限制 ({self._max_videos}),停止")
                    break

                # 进度回调
                if self._progress_cb:
                    total = min(len(videos), self._max_videos) if self._max_videos else len(videos)
                    self._progress_cb(idx, total, v['title'][:30])

                aid = v["aid"]
                print(f"\n  视频 {idx}/{len(videos)}: {v['title'][:40]} (aid={aid})")

                # 爬一级评论
                root_crawled = self.crawl_root_comments(aid)
                total_root += root_crawled

                # 爬子评论
                sub_crawled = self.crawl_sub_comments(aid)
                total_subs += sub_crawled

                if sub_crawled:
                    print(f"    aid={aid} 子评论: {sub_crawled} 条")

            # 统计
            stats = db.get_stats()

            # 412 复盘报告
            print(self._rate_ctrl.dump_report())

            print(f"\n[3/3] 爬取完成!")
            print(f"  一级评论: {total_root}")
            print(f"  子评论  : {total_subs}")
            print(f"  数据库总计: {stats['total']} 条")
            print(f"  已完成视频: {stats['videos_done']}")

            return {
                "total_root": total_root,
                "total_subs": total_subs,
                "db_total": stats["total"],
                "videos_done": stats["videos_done"],
            }
        finally:
            db.close()


# ─── 便捷入口 ──────────────────────────────────────────────────

def crawl_uid(uid: str) -> dict:
    """一键爬取指定 UID 的全部评论。"""
    crawler = CommentCrawler()
    if not crawler.setup():
        return {"error": "初始化失败"}
    return crawler.crawl_by_uid(uid)
