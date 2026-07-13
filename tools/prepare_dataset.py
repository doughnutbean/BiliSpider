"""提交前自动检查 JSONL 数据集。

检查项:
  1. JSONL 格式校验（合法 JSON、必需字段、字段类型）
  2. 主键 (rpid, oid, type) 重复检查
  3. 文件命名规范检查
  4. 大文件提醒（默认 >50MB）
  5. 数据统计摘要

用法:
  python tools/prepare_dataset.py datasets/*.jsonl
  python tools/prepare_dataset.py datasets/comments_all.jsonl --max-mb 30
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path
import sys

# 修复 Windows 控制台 GBK 编码问题，确保 emoji 正常输出
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilispider.manifest import scan_jsonl_stats

# ── 常量 ──────────────────────────────────────────────

COMMENT_COLUMNS = (
    "rpid", "oid", "type", "mid", "parent", "root",
    "ctime", "message", "like_count", "sub_count", "crawl_time",
)

INTEGER_COLUMNS = {
    "rpid", "oid", "type", "mid", "parent", "root",
    "ctime", "like_count", "sub_count", "crawl_time",
}

# 推荐的文件命名模式
_NAME_PATTERNS = (
    re.compile(r"^comments_uid_\d+\.jsonl$"),
    re.compile(r"^comments_oid_\d+\.jsonl$"),
    re.compile(r"^comments_all_\d{4}-\d{2}-\d{2}\.jsonl$"),
    re.compile(r"^comments_all\.jsonl$"),
)

_NAME_PATTERN_DESC = (
    "comments_uid_<uid>.jsonl",
    "comments_oid_<oid>.jsonl",
    "comments_all_<YYYY-MM-DD>.jsonl",
    "comments_all.jsonl",
)


# ── 参数解析 ──────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="提交前检查 JSONL 数据集：格式校验、去重检查、命名规范、统计摘要。"
    )
    parser.add_argument(
        "files", nargs="*",
        help="JSONL 文件或 glob 模式（默认 datasets/*.jsonl）。",
    )
    parser.add_argument(
        "--max-mb", type=int, default=50,
        help="超过此大小（MB）的文件会触发警告（默认 50）。",
    )
    parser.add_argument(
        "--no-name-check", action="store_true",
        help="跳过文件命名规范检查。",
    )
    return parser.parse_args()


# ── 文件展开 ──────────────────────────────────────────

def expand_files(patterns: list[str]) -> list[Path]:
    """展开 glob 模式，去重，返回排序后的 Path 列表。"""
    if not patterns:
        patterns = ["datasets/*.jsonl"]
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = sorted(Path(m) for m in glob.glob(pattern))
        if not matches:
            path = Path(pattern)
            if path.exists():
                matches = [path]
            else:
                print(f"[SKIP] 未找到匹配文件: {pattern}")
                continue
        for path in matches:
            resolved = path.resolve()
            if resolved not in seen and path.name != "manifest.json":
                files.append(path)
                seen.add(resolved)
    return files


# ── 命名检查 ──────────────────────────────────────────

def check_name(path: Path) -> str | None:
    """检查文件名是否符合推荐规范；返回警告消息或 None。"""
    if any(pat.match(path.name) for pat in _NAME_PATTERNS):
        return None
    return (
        f"文件名不符合推荐规范: {path.name}\n"
        f"  推荐格式: {', '.join(_NAME_PATTERN_DESC)}"
    )


# ── 记录校验 ──────────────────────────────────────────

def validate_record(record: object, path: Path, line_no: int) -> list[str]:
    """校验单条 JSON 记录；返回错误消息列表。"""
    errors: list[str] = []
    prefix = f"{path}:{line_no}"

    if not isinstance(record, dict):
        return [f"{prefix} JSON 值必须是对象，实际类型: {type(record).__name__}"]

    missing = [col for col in COMMENT_COLUMNS if col not in record]
    if missing:
        errors.append(f"{prefix} 缺少字段: {', '.join(missing)}")

    for col in INTEGER_COLUMNS:
        if col in record and record[col] is not None and not isinstance(record[col], int):
            errors.append(f"{prefix} 字段 {col} 必须是整数，实际类型: {type(record[col]).__name__}")

    if "message" in record and record["message"] is not None and not isinstance(record["message"], str):
        errors.append(f"{prefix} 字段 message 必须是字符串或 null")

    return errors


# ── 主逻辑 ────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    files = expand_files(args.files)

    if not files:
        print("没有找到需要检查的 JSONL 文件。")
        print("提示: 将 .jsonl 文件放在 datasets/ 目录下，或通过命令行参数指定路径。")
        return

    errors: list[str] = []
    warnings: list[str] = []
    seen_keys: dict[tuple[int, int, int], str] = {}
    total_rows = 0
    file_stats: dict[str, dict] = {}

    for path in files:
        # ── 大文件提醒 ──
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > args.max_mb:
            warnings.append(
                f"{path.name}: 文件 {size_mb:.1f} MB，超过 {args.max_mb} MB。"
                f" 建议用 --split-by uid 或 --split-by oid 拆分成小文件。"
            )

        # ── 命名检查 ──
        if not args.no_name_check:
            name_warn = check_name(path)
            if name_warn:
                warnings.append(f"{path.name}: {name_warn}")

        # ── 逐行校验 ──
        stats = scan_jsonl_stats(path)
        file_stats[path.name] = stats
        if stats["errors"]:
            errors.extend(stats["errors"])

        # ── 主键去重检查 ──
        with path.open("r", encoding="utf-8-sig") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    # 空行已在 scan_jsonl_stats 中跳过，这里仅作防御
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 已在 stats["errors"] 中记录
                if not isinstance(record, dict):
                    continue

                total_rows += 1
                key = (int(record["rpid"]), int(record["oid"]), int(record["type"]))
                location = f"{path.name}:{line_no}"
                if key in seen_keys:
                    errors.append(f"{location} 主键重复 {key}；首次出现在 {seen_keys[key]}")
                else:
                    seen_keys[key] = location

    # ── 输出警告 ──
    for w in warnings:
        print(f"⚠  [WARN]  {w}")

    # ── 输出错误 ──
    if errors:
        print(f"\n❌ 发现 {len(errors)} 个错误:\n")
        for err in errors[:30]:
            print(f"  [ERROR] {err}")
        if len(errors) > 30:
            print(f"  ... 还有 {len(errors) - 30} 个错误")
        print()

    # ── 统计摘要 ──
    from bilispider.manifest import aggregate_stats
    agg = aggregate_stats(file_stats)
    print(f"{'='*50}")
    print(f"  检查完成")
    print(f"{'='*50}")
    print(f"  文件数        : {len(files)}")
    print(f"  有效记录数    : {total_rows}")
    print(f"  唯一主键      : {len(seen_keys)}")
    print(f"  覆盖 UID 数   : {agg['unique_uids']}")
    print(f"  覆盖 OID 数   : {agg['unique_oids']}")
    if errors:
        print(f"  错误数        : {len(errors)} ❌")
    else:
        print(f"  错误数        : 0 ✅")

    # ── 退出码 ──
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
