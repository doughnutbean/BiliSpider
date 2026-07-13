"""生成 Markdown 格式的数据集报告。

报告内容:
  - 总评论数、覆盖视频数、覆盖用户数
  - 最近更新时间
  - 每个数据文件的贡献量
  - Top 评论用户 / Top 视频

用法:
  python tools/report_dataset.py                    # 输出到终端
  python tools/report_dataset.py --out REPORT.md   # 输出到文件
  python tools/report_dataset.py --top 20          # 调整 Top N 数量
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

# 修复 Windows 控制台 GBK 编码问题，确保 emoji 正常输出
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilispider.manifest import (
    load_manifest,
    scan_datasets_dir,
    scan_jsonl_stats,
    aggregate_stats,
)


# ── 参数解析 ──────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成 Markdown 格式的数据集报告。"
    )
    parser.add_argument("--out", help="输出文件路径（默认输出到 stdout）。")
    parser.add_argument("--top", type=int, default=10, help="Top N 数量（默认 10）。")
    return parser.parse_args()


# ── 数据收集 ──────────────────────────────────────────

def _format_size(size_bytes: int) -> str:
    """将字节数格式化为人类可读的大小。"""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def collect_file_stats() -> tuple[dict[str, dict], list[str]]:
    """扫描 datasets/ 目录，收集每个文件的统计信息。

    优先使用 manifest 中的缓存数据，缺失的文件实时扫描。
    返回 (file_stats, missing_from_manifest_list)。
    """
    manifest = load_manifest()
    jsonl_files = scan_datasets_dir()
    result: dict[str, dict] = {}
    missing: list[str] = []

    for filepath in jsonl_files:
        filename = filepath.name
        if filename in manifest.get("files", {}):
            entry = manifest["files"][filename]
            size = filepath.stat().st_size if filepath.exists() else entry.get("size_bytes", 0)
            result[filename] = {
                "comments": entry.get("comments", 0),
                "unique_uids": entry.get("unique_uids", 0),
                "unique_oids": entry.get("unique_oids", 0),
                "size_bytes": size,
                "contributor": entry.get("contributor", ""),
                "export_time": entry.get("export_time", ""),
            }
        else:
            missing.append(filename)
            stats = scan_jsonl_stats(filepath)
            size = filepath.stat().st_size if filepath.exists() else 0
            result[filename] = {
                "comments": stats["comments"],
                "unique_uids": stats["unique_uids"],
                "unique_oids": stats["unique_oids"],
                "size_bytes": size,
                "contributor": "",
                "export_time": "",
                # 传递原始 uid/oid 集合，供 aggregate_stats 精确去重
                "uids": stats.get("uids", set()),
                "oids": stats.get("oids", set()),
            }

    return result, missing


# ── 报告生成 ──────────────────────────────────────────

def generate_report(file_stats: dict[str, dict], top_n: int, missing: list[str]) -> str:
    """根据文件统计信息生成 Markdown 报告。"""
    agg = aggregate_stats(file_stats)
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []
    lines.append(f"# 📊 BiliSpider 数据集报告")
    lines.append(f"")
    lines.append(f"> 生成时间: {now}")
    lines.append(f"")
    lines.append(f"## 总览")
    lines.append(f"")
    lines.append(f"- **总评论数**: {agg['total_comments']:,}")
    approx_note = " *(近似值)*" if agg.get("approximate") else ""
    lines.append(f"- **覆盖视频数 (OID)**: {agg['unique_oids']}{approx_note}")
    lines.append(f"- **覆盖用户数 (UID)**: {agg['unique_uids']}{approx_note}")
    lines.append(f"- **数据文件数**: {agg['total_files']}")
    lines.append(f"")

    # ── 文件明细 ──
    lines.append(f"## 数据文件明细")
    lines.append(f"")
    # 按评论数降序排列
    sorted_files = sorted(
        file_stats.items(),
        key=lambda kv: kv[1].get("comments", 0),
        reverse=True,
    )
    for filename, stats in sorted_files:
        contrib = stats.get("contributor", "")
        contrib_str = f" — *{contrib}*" if contrib else ""
        export_time = stats.get("export_time", "")
        time_str = f" ({export_time})" if export_time else ""
        size_str = _format_size(stats.get("size_bytes", 0))
        lines.append(
            f"- **{filename}**{contrib_str}{time_str}"
        )
        lines.append(
            f"  - {stats['comments']:,} 条评论 | "
            f"{stats['unique_uids']} UID | "
            f"{stats['unique_oids']} OID | "
            f"{size_str}"
        )
    lines.append(f"")

    # ── Top 贡献者 ──
    contrib_counts: dict[str, tuple[int, int]] = {}
    for stats in file_stats.values():
        name = stats.get("contributor", "").strip()
        if not name:
            name = "(未署名)"
        prev_comments, prev_files = contrib_counts.get(name, (0, 0))
        contrib_counts[name] = (
            prev_comments + stats.get("comments", 0),
            prev_files + 1,
        )

    if contrib_counts:
        lines.append(f"## 贡献者排行（按评论数）")
        lines.append(f"")
        sorted_contrib = sorted(
            contrib_counts.items(),
            key=lambda kv: kv[1][0],
            reverse=True,
        )
        for name, (comments, files) in sorted_contrib[:top_n]:
            lines.append(f"- **{name}**: {comments:,} 条评论 ({files} 个文件)")
        lines.append(f"")

    # ── 提示 ──
    if missing:
        lines.append(f"## ⚠ 注意")
        lines.append(f"")
        lines.append(f"以下文件未在 `manifest.json` 中登记，统计信息来自实时扫描：")
        for fname in missing:
            lines.append(f"- `{fname}`")
        lines.append(f"")
        lines.append(f"如需登记，请运行 `python tools/contribute_dataset.py` 或手动更新 manifest。")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"")
    lines.append(f"*本报告由 `tools/report_dataset.py` 自动生成。*")
    lines.append(f"")

    return "\n".join(lines)


# ── 主逻辑 ────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    file_stats, missing = collect_file_stats()

    if not file_stats:
        print("datasets/ 目录中没有 JSONL 文件。")
        print("运行 python tools/contribute_dataset.py --all 来创建第一份数据集。")
        return

    report = generate_report(file_stats, args.top, missing)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"报告已生成: {out_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
