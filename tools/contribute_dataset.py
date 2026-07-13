"""一键贡献数据集：导出 → 校验 → 统计 → 更新 manifest → 提示 git 命令。

用法:
  # 按 UID 导出并贡献
  python tools/contribute_dataset.py --uid 2 --contributor "小明"

  # 导出全部评论
  python tools/contribute_dataset.py --all --contributor "团队"

流程:
  1. 从 data/comments.db 导出 JSONL
  2. 校验导出文件格式
  3. 扫描统计信息
  4. 更新 datasets/manifest.json
  5. 输出建议的 git add/commit 命令
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3
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
    save_manifest,
    update_file_entry,
    scan_jsonl_stats,
)
from bilispider.paths import COMMENTS_DB_PATH

# ── 常量 ──────────────────────────────────────────────

COMMENT_COLUMNS = (
    "rpid", "oid", "type", "mid", "parent", "root",
    "ctime", "message", "like_count", "sub_count", "crawl_time",
)

# 默认导出目录
_DEFAULT_OUT_DIR = ROOT / "datasets"


# ── 参数解析 ──────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="一键贡献数据集：导出、校验、更新 manifest、提示 git 命令。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--uid", type=int, help="按 UP 主 UID 导出评论。")
    group.add_argument("--all", action="store_true", help="导出数据库中全部评论。")

    parser.add_argument("--contributor", default="", help="贡献者姓名或昵称（会写入 manifest）。")
    parser.add_argument("--db", default=str(COMMENTS_DB_PATH), help="SQLite 数据库路径。")
    parser.add_argument(
        "--out-dir", default=str(_DEFAULT_OUT_DIR),
        help=f"导出目录（默认 {_DEFAULT_OUT_DIR}）。",
    )
    parser.add_argument(
        "--since", type=int,
        help="只导出此 Unix 时间戳之后的评论。",
    )
    parser.add_argument(
        "--until", type=int,
        help="只导出此 Unix 时间戳之前的评论。",
    )
    return parser.parse_args()


# ── 导出 ──────────────────────────────────────────────

def _build_export_query(
    uid: int | None,
    since: int | None,
    until: int | None,
) -> tuple[str, list]:
    """构建导出 SQL 查询。"""
    where: list[str] = []
    params: list = []

    if uid is not None:
        where.append("mid = ?")
        params.append(uid)
    if since is not None:
        where.append("ctime >= ?")
        params.append(since)
    if until is not None:
        where.append("ctime <= ?")
        params.append(until)

    sql = f"SELECT {', '.join(COMMENT_COLUMNS)} FROM comments"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY oid, type, rpid"
    return sql, params


def _generate_filename(uid: int | None) -> str:
    """根据导出模式生成文件名。"""
    if uid is not None:
        return f"comments_uid_{uid}.jsonl"
    date_str = time.strftime("%Y-%m-%d")
    return f"comments_all_{date_str}.jsonl"


def export_comments(
    db_path: Path,
    out_path: Path,
    uid: int | None,
    since: int | None,
    until: int | None,
) -> int:
    """从数据库导出评论到 JSONL 文件；返回导出条数。"""
    sql, params = _build_export_query(uid, since, until)

    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params)
        with out_path.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                item = {key: row[key] for key in COMMENT_COLUMNS}
                fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1

    return count


# ── 校验 ──────────────────────────────────────────────

def validate_export(filepath: Path) -> list[str]:
    """快速校验导出文件的格式；返回错误列表。"""
    errors: list[str] = []
    with filepath.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                errors.append(f"{filepath.name}:{line_no} 空行")
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{filepath.name}:{line_no} 非法 JSON: {exc.msg}")
                continue
            if not isinstance(record, dict):
                errors.append(f"{filepath.name}:{line_no} 不是 JSON 对象")
                continue
            missing = [col for col in COMMENT_COLUMNS if col not in record]
            if missing:
                errors.append(f"{filepath.name}:{line_no} 缺少字段: {', '.join(missing)}")
    return errors


# ── 主逻辑 ────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    out_dir = Path(args.out_dir)
    uid: int | None = args.uid if args.uid else None

    filename = _generate_filename(uid)
    out_path = out_dir / filename

    # ── 1. 导出 ──
    print(f"📤 正在导出到 {out_path} ...")
    count = export_comments(db_path, out_path, uid, args.since, args.until)
    print(f"   导出完成: {count} 条评论")
    if count == 0:
        print("⚠  没有导出任何数据，请检查数据库或筛选条件。")
        return

    # ── 2. 校验 ──
    print(f"🔍 正在校验 {out_path.name} ...")
    errors = validate_export(out_path)
    if errors:
        print(f"❌ 校验发现 {len(errors)} 个错误:")
        for err in errors[:10]:
            print(f"   {err}")
        if len(errors) > 10:
            print(f"   ... 还有 {len(errors) - 10} 个")
        raise SystemExit(1)
    print("   ✅ 格式校验通过")

    # ── 3. 统计 ──
    print("📊 正在统计...")
    stats = scan_jsonl_stats(out_path)
    print(f"   评论数: {stats['comments']}, 覆盖 UID: {stats['unique_uids']}, 覆盖 OID: {stats['unique_oids']}")

    # ── 4. 更新 manifest ──
    print("📋 正在更新 manifest.json ...")
    manifest = load_manifest()
    update_file_entry(
        manifest,
        filename,
        comments=stats["comments"],
        unique_uids=stats["unique_uids"],
        unique_oids=stats["unique_oids"],
        contributor=args.contributor,
        filepath=out_path,
    )
    save_manifest(manifest)
    print(f"   ✅ manifest.json 已更新 (version={manifest['version']})")

    # ── 5. 提示 git 命令 ──
    print()
    print("=" * 56)
    print("  数据已就绪！建议执行以下命令提交:")
    print("=" * 56)
    print(f"  git add {out_path.as_posix()} datasets/manifest.json")
    print(f'  git commit -m "data: 添加数据集 {filename}"')
    print()
    print(f"  贡献者: {args.contributor or '(未填写)'}")
    print(f"  文件:   {out_path}")
    print(f"  大小:   {out_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
