"""
B站爬取基准测试 — 评估反风控策略效果。

三种模式:
    python benchmark.py quick       # 30分钟基线
    python benchmark.py medium      # 2小时中测
    python benchmark.py overnight   # 8小时通宵

基准测试会自动爬取 B站站长 bishi (UID=2) 最近30天的评论，
记录请求速率、412率、成功率等指标，结束时输出报告。
"""

import sys
import time
import threading
from datetime import datetime, timedelta

from bilispider.comment_crawler import CommentCrawler

# 预设模式
PRESETS = {
    "quick":     {"duration_min": 30,  "label": "30分钟基线"},
    "medium":    {"duration_min": 120, "label": "2小时中测"},
    "overnight": {"duration_min": 480, "label": "8小时通宵"},
}


class BenchmarkRunner:
    """基准测试运行器。"""

    def __init__(self, duration_min: int, uid: str = "2") -> None:
        self.duration_sec = duration_min * 60
        self.uid = uid
        self._crawler: CommentCrawler | None = None
        self._start_time = 0.0
        # 快照指标 (每秒更新)
        self._metrics: dict = {}
        self._running = False

    # ── 公共接口 ──

    def run(self, progress_callback=None) -> dict:
        """运行基准测试,返回结果字典。"""
        crawler = CommentCrawler()
        self._crawler = crawler

        since = int((datetime.now() - timedelta(days=30)).timestamp())
        crawler.configure(since_ts=since, max_videos=0)

        if not crawler.setup():
            return {"error": "初始化失败"}

        self._start_time = time.time()
        self._running = True

        # 定时停止线程
        def _stop_timer():
            time.sleep(self.duration_sec)
            crawler.cancel()
            self._running = False

        timer = threading.Thread(target=_stop_timer, daemon=True)
        timer.start()

        try:
            result = crawler.crawl_by_uid(self.uid)
        except KeyboardInterrupt:
            crawler.cancel()

        elapsed = time.time() - self._start_time
        report = self._build_report(elapsed, result)

        # 回调通知完成
        if progress_callback:
            progress_callback("done", report)

        return report

    def get_live_metrics(self) -> dict:
        """获取实时指标 (供GUI轮询)。"""
        if not self._crawler or not self._start_time:
            return {}

        rc = self._crawler._rate_ctrl
        elapsed = time.time() - self._start_time
        remaining = max(0, self.duration_sec - elapsed)

        return {
            "elapsed_min": round(elapsed / 60, 1),
            "remaining_min": round(remaining / 60, 1),
            "total_requests": rc._total_requests,
            "total_success": rc._total_success,
            "req_per_min": round(rc._total_requests / max(elapsed, 1) * 60, 1),
            "412_count": rc.get_412_count(),
            "state": rc.get_state(),
            "delay_range": rc.get_delay_range(),
            "running": self._running,
        }

    # ── 报告生成 ──

    def _build_report(self, elapsed: float, crawl_result: dict) -> dict:
        rc = self._crawler._rate_ctrl if self._crawler else None
        total_req = rc._total_requests if rc else 0
        total_ok = rc._total_success if rc else 0
        req_rate = round(total_req / max(elapsed, 1) * 60, 1)
        fail_rate = round((total_req - total_ok) / max(total_req, 1) * 100, 1)

        return {
            "duration_min": round(elapsed / 60, 1),
            "planned_min": round(self.duration_sec / 60, 1),
            "total_requests": total_req,
            "total_success": total_ok,
            "req_per_min": req_rate,
            "fail_rate": fail_rate,
            "412_count": rc.get_412_count() if rc else 0,
            "comments_root": crawl_result.get("total_root", 0),
            "comments_sub": crawl_result.get("total_subs", 0),
            "db_total": crawl_result.get("db_total", 0),
        }


def print_report(report: dict) -> None:
    """打印格式化的基准测试报告。"""
    if "error" in report:
        print(f"[X] {report['error']}")
        return

    print()
    print("=" * 60)
    print("  基准测试报告")
    print("=" * 60)
    print(f"  计划时长: {report['planned_min']}min")
    print(f"  实际运行: {report['duration_min']}min")
    print(f"  总请求数: {report['total_requests']}")
    print(f"  成功请求: {report['total_success']}")
    print(f"  请求速率: {report['req_per_min']:.1f} req/min")
    print(f"  失败率:   {report['fail_rate']:.1f}%")
    print(f"  412次数:  {report['412_count']}")
    print(f"  一级评论: {report['comments_root']}")
    print(f"  子评论:   {report['comments_sub']}")
    print(f"  数据库:   {report['db_total']} 条")
    print("=" * 60)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in PRESETS:
        print("用法: python benchmark.py quick|medium|overnight")
        sys.exit(1)

    mode = sys.argv[1]
    cfg = PRESETS[mode]
    print(f"基准测试: {cfg['label']}")
    print(f"目标UID: 2 (bishi)")
    print(f"时间范围: 最近30天")
    print()

    runner = BenchmarkRunner(duration_min=cfg["duration_min"])
    report = runner.run()
    print_report(report)


if __name__ == "__main__":
    main()
