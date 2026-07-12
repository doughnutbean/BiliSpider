"""
B站评论批量爬取工具。

通过 UP主 UID 爬取其过往视频评论区的所有评论（一级 + 二级），
持久化存储到 SQLite 数据库 (comments.db)。

⚠️ 风险警告:
  批量爬取属于高风险操作。B站有严格的风控机制，请务必:
    - 控制爬取范围 (建议先用小UP主测试)
    - 保持默认的 2~4 秒请求间隔
    - 仅用于学习研究

用法:
    python crawl_comments.py <UID> [选项]

选项:
    --days N         只爬最近 N 天的评论 (默认: 不限)
    --since DATE     只爬此日期之后的评论,格式 YYYY-MM-DD
    --until DATE     只爬此日期之前的评论,格式 YYYY-MM-DD
    --max-videos N   最多爬取 N 个视频 (默认: 不限)
    --proxy URL      使用代理,如 --proxy http://127.0.0.1:7890
                     (可多次指定以轮换)

示例:
    python crawl_comments.py 2 --days 30 --max-videos 5
    python crawl_comments.py 2 --since 2025-01-01 --until 2025-06-30
    python crawl_comments.py 2 --proxy http://127.0.0.1:7890
"""

import sys
import time
from datetime import datetime, timedelta

from bilispider.comment_crawler import CommentCrawler


def parse_date(date_str: str) -> int:
    """将 YYYY-MM-DD 格式转换为 Unix 时间戳。"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return int(dt.timestamp())
    except ValueError:
        print(f"[X] 日期格式错误: {date_str},应为 YYYY-MM-DD")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    uid = sys.argv[1]
    if not uid.isdigit():
        print(f"[X] UID 必须是纯数字,收到: {uid}")
        sys.exit(1)

    # 解析参数
    since_ts = 0
    until_ts = 0
    max_videos = 0
    proxies: list[str] = []
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            since_ts = int((datetime.now() - timedelta(days=days)).timestamp())
            print(f"  时间过滤: 最近 {days} 天 (since {datetime.fromtimestamp(since_ts)})")
            i += 2
        elif args[i] == "--since" and i + 1 < len(args):
            since_ts = parse_date(args[i + 1])
            print(f"  时间过滤: since {args[i+1]}")
            i += 2
        elif args[i] == "--until" and i + 1 < len(args):
            until_ts = parse_date(args[i + 1])
            print(f"  时间过滤: until {args[i+1]}")
            i += 2
        elif args[i] == "--max-videos" and i + 1 < len(args):
            max_videos = int(args[i + 1])
            print(f"  视频限制: 最多 {max_videos} 个")
            i += 2
        elif args[i] == "--proxy" and i + 1 < len(args):
            proxies.append(args[i + 1])
            print(f"  代理: {args[i+1]}")
            i += 2
        else:
            print(f"[X] 未知参数: {args[i]}")
            sys.exit(1)

    # 确认风险
    print("=" * 60)
    print("  ⚠️  批量评论爬取 - 风险确认")
    print("=" * 60)
    print()
    print("  此操作将对目标 UP 主的所有视频评论区进行逐页爬取。")
    if since_ts:
        print(f"  时间范围: {datetime.fromtimestamp(since_ts)} 之后")
    if until_ts:
        print(f"            {datetime.fromtimestamp(until_ts)} 之前")
    if max_videos:
        print(f"  视频数量: 最多 {max_videos} 个")
    if proxies:
        print(f"  代理数量: {len(proxies)} 个")
    print()
    answer = input("  确认继续? (输入 yes 继续): ").strip().lower()
    if answer != "yes":
        print("  已取消。")
        sys.exit(0)

    crawler = CommentCrawler()
    crawler.configure(
        since_ts=since_ts,
        until_ts=until_ts,
        max_videos=max_videos,
        proxies=proxies,
    )
    if not crawler.setup():
        print("[X] 初始化失败,请确保已运行 python login.py 扫码登录")
        sys.exit(1)

    try:
        result = crawler.crawl_by_uid(uid)
        print(f"\n爬取结果: {result}")
    except KeyboardInterrupt:
        print("\n[!] 用户中断,正在保存进度...")
        crawler.cancel()
    except Exception as e:
        print(f"\n[X] 爬取出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
