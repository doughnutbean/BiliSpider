"""
B站 API 稳定性压测工具。

用固定任务集周期循环,测量爬虫稳定性基线。

用法:
    python benchmark.py quick        # 30分钟
    python benchmark.py medium       # 2小时
    python benchmark.py overnight    # 8小时 (通宵)

输出:
    - 总请求数 / 成功率 / 412率
    - 平均冷却时间 / 吞吐量 (请求/分钟)
    - 按接口维度的细分指标
    - 结果保存到 benchmark_result.json

以后每次改 headers、调度、Cookie 策略后跑一次,
对比结果就知道是否真的变稳了。
"""

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

from bilispider.comment_crawler import RateController
from bilispider.login import get_cookie_string
from bilispider.wbi import enc_wbi, get_wbi_keys

# ─── 预设档位 ─────────────────────────────────────────────────

_PRESETS = {
    "quick":     30 * 60,    # 30分钟
    "medium":    2 * 3600,   # 2小时
    "overnight": 8 * 3600,   # 8小时
}

# ─── 固定任务集: 低风险的API探测端点 ──────────────────────────

# 任务集: (名称, API URL, 参数模板)
# 用已知安全的"小号"UID,避免频繁访问同一个UP主
_SAFE_UIDS = ["2", "234978716", "8047632", "488979578", "1830548880"]

_TASK_SET = [
    ("用户信息",  "https://api.bilibili.com/x/space/wbi/acc/info",
     lambda uid: {"mid": uid}),
    ("评论-第1页", "https://api.bilibili.com/x/v2/reply",
     lambda uid: {"type": 1, "oid": 170001, "pn": 1, "ps": 5, "sort": 2}),
    ("评论-末页",  "https://api.bilibili.com/x/v2/reply",
     lambda uid: {"type": 1, "oid": 170001, "pn": 99, "ps": 5, "sort": 2}),
]


# ─── 指标收集器 ────────────────────────────────────────────────

class MetricsCollector:
    """收集压测过程中的各项指标。"""

    def __init__(self) -> None:
        self.start_time = time.time()
        self.total_requests = 0
        self.success_count = 0
        self.http_412_count = 0
        self.api_352_count = 0
        self.api_799_count = 0
        self.other_error_count = 0
        self.total_delay = 0.0         # 累计等待时间
        self.cooling_count = 0          # 进入冷却模式次数
        self.cooling_total_time = 0.0   # 冷却模式累计时长
        # 按接口细分
        self.per_api: dict[str, dict] = defaultdict(lambda: {
            "requests": 0, "success": 0, "412": 0, "latency_ms": [],
        })
        # 时间序列: (时间戳, 事件类型)
        self.timeline: list[dict] = []
        self._rate_ctrl: RateController | None = None

    def bind_rate_controller(self, ctrl: RateController) -> None:
        self._rate_ctrl = ctrl

    def record_request(self, task_name: str) -> None:
        self.total_requests += 1
        self.per_api[task_name]["requests"] += 1

    def record_success(self, task_name: str, latency_ms: float) -> None:
        self.success_count += 1
        self.per_api[task_name]["success"] += 1
        self.per_api[task_name]["latency_ms"].append(latency_ms)
        self._snapshot("success", task_name)

    def record_412(self, task_name: str) -> None:
        self.http_412_count += 1
        self.per_api[task_name]["412"] += 1
        self._snapshot("412", task_name)

    def record_352(self, task_name: str) -> None:
        self.api_352_count += 1
        self._snapshot("352", task_name)

    def record_799(self, task_name: str) -> None:
        self.api_799_count += 1
        self._snapshot("799", task_name)

    def record_error(self, task_name: str) -> None:
        self.other_error_count += 1
        self._snapshot("error", task_name)

    def record_delay(self, seconds: float) -> None:
        self.total_delay += seconds
        if self._rate_ctrl and self._rate_ctrl.get_state() == RateController.STATIC_COOLING:
            self.cooling_count += 1
            self.cooling_total_time += seconds

    def _snapshot(self, event: str, task: str) -> None:
        self.timeline.append({
            "elapsed_s": round(time.time() - self.start_time, 1),
            "event": event, "task": task,
        })

    def report(self, duration_s: float) -> str:
        elapsed = time.time() - self.start_time
        actual_min = elapsed / 60
        throughput = self.total_requests / max(elapsed, 1) * 60
        success_rate = self.success_count / max(self.total_requests, 1) * 100
        http_412_rate = self.http_412_count / max(self.total_requests, 1) * 100
        avg_delay = self.total_delay / max(self.total_requests, 1)

        lines = [
            "",
            "=" * 60,
            "  压测报告",
            "=" * 60,
            f"  预设时长: {duration_s/60:.0f}分钟  |  实际运行: {actual_min:.0f}分钟",
            f"  总请求: {self.total_requests}  |  吞吐: {throughput:.1f} req/min",
            f"  成功率: {success_rate:.1f}%",
            f"  412率:   {http_412_rate:.1f}%  |  -352: {self.api_352_count}  |  -799: {self.api_799_count}  |  其他: {self.other_error_count}",
            f"  平均延迟: {avg_delay:.1f}s  |  冷却次数: {self.cooling_count}  |  冷却累计: {self.cooling_total_time:.0f}s",
            "",
            "  ── 按接口细分 ──",
        ]
        for name, m in sorted(self.per_api.items()):
            n = m["requests"]
            sr = m["success"] / max(n, 1) * 100
            ar = m["412"] / max(n, 1) * 100
            lats = m["latency_ms"]
            avg_lat = sum(lats) / max(len(lats), 1)
            lines.append(
                f"    {name:16s} {n:4d}次 | "
                f"成功率:{sr:5.1f}% | 412率:{ar:5.1f}% | "
                f"均延时:{avg_lat:.0f}ms"
            )

        if self._rate_ctrl:
            lines.append("")
            lines.append(self._rate_ctrl.dump_report())

        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self, duration_s: float) -> dict:
        elapsed = time.time() - self.start_time
        return {
            "timestamp": datetime.now().isoformat(),
            "preset_duration_s": duration_s,
            "actual_duration_s": round(elapsed, 1),
            "total_requests": self.total_requests,
            "throughput_rpm": round(self.total_requests / max(elapsed, 1) * 60, 1),
            "success_rate_pct": round(self.success_count / max(self.total_requests, 1) * 100, 1),
            "http412_rate_pct": round(self.http_412_count / max(self.total_requests, 1) * 100, 1),
            "api352_count": self.api_352_count,
            "api799_count": self.api_799_count,
            "avg_delay_s": round(self.total_delay / max(self.total_requests, 1), 1),
            "cooling_count": self.cooling_count,
            "cooling_total_s": round(self.cooling_total_time, 1),
        }


# ─── 压测执行器 ────────────────────────────────────────────────

def run_benchmark(duration_s: int) -> None:
    import requests
    from curl_cffi import requests as cr

    cookie = get_cookie_string()
    if not cookie:
        print("[X] 未找到 Cookie,请先 python login.py")
        sys.exit(1)

    # 设置
    session = cr.Session(impersonate="chrome120")
    session.headers.update({
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    })

    # 自动检测代理
    try:
        requests.get("http://127.0.0.1:7890", timeout=0.3)
        session.proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
        print("[*] 使用代理: 127.0.0.1:7890")
    except Exception:
        print("[*] 直连模式")

    # WBI 密钥
    try:
        img_key, sub_key = get_wbi_keys()
    except Exception as e:
        print(f"[X] 获取WBI密钥失败: {e}")
        sys.exit(1)

    rate_ctrl = RateController()
    metrics = MetricsCollector()
    metrics.bind_rate_controller(rate_ctrl)

    end_time = time.time() + duration_s
    uid_idx = 0
    task_idx = 0

    print(f"\n压测开始 — 预设 {duration_s//60} 分钟, 预计结束于 {datetime.fromtimestamp(end_time).strftime('%H:%M:%S')}")
    print(f"任务集: {len(_TASK_SET)} 个接口 × {len(_SAFE_UIDS)} 个UID 轮转")
    print("-" * 40)

    iteration = 0
    while time.time() < end_time:
        uid = _SAFE_UIDS[uid_idx % len(_SAFE_UIDS)]
        uid_idx += 1

        task_name, url, param_fn = _TASK_SET[task_idx % len(_TASK_SET)]
        task_idx += 1
        iteration += 1

        # 进度报告
        elapsed = time.time() - metrics.start_time
        if iteration % 20 == 0:
            remaining = max(0, end_time - time.time())
            print(f"  [{elapsed/60:.0f}min] 已执行 {metrics.total_requests} 请求, "
                  f"成功:{metrics.success_count} 412:{metrics.http_412_count}, "
                  f"剩余 {remaining/60:.0f}min")

        # 延迟
        delay = rate_ctrl.on_request()
        metrics.record_delay(delay)
        time.sleep(delay)

        # 签名并请求
        params = param_fn(uid)
        signed = enc_wbi(params, img_key, sub_key)
        metrics.record_request(task_name)

        t0 = time.time()
        try:
            resp = session.get(url, params=signed, timeout=12)
            latency = (time.time() - t0) * 1000

            if resp.status_code == 412:
                metrics.record_412(task_name)
                rate_ctrl.on_412(url, "benchmark")
                continue

            resp.raise_for_status()
            data = resp.json()
            code = data.get("code", 0)

            if code == 0:
                metrics.record_success(task_name, latency)
                rate_ctrl.on_success()
            elif code == -352:
                metrics.record_352(task_name)
                img_key, sub_key = get_wbi_keys()
                time.sleep(15)
            elif code == -799:
                metrics.record_799(task_name)
                time.sleep(30)
            else:
                metrics.record_error(task_name)
        except Exception:
            metrics.record_error(task_name)

    # 报告
    print(metrics.report(duration_s))
    result = metrics.to_dict(duration_s)
    result["iterations"] = iteration
    with open("benchmark_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 benchmark_result.json")


# ─── CLI ──────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _PRESETS:
        print("用法: python benchmark.py <preset>")
        print(f"可选: {', '.join(_PRESETS.keys())}")
        sys.exit(1)

    preset = sys.argv[1]
    duration = _PRESETS[preset]
    label = {"quick": "30分钟", "medium": "2小时", "overnight": "通宵(8小时)"}[preset]

    print(f"压测档位: {label}")
    print(f"预计持续: {duration//60} 分钟")
    print()

    run_benchmark(duration)


if __name__ == "__main__":
    main()
