"""一键贡献数据集：导出 → 校验 → 统计 → 更新 manifest → 提示 git 命令。

用法:
  # 按 UID 导出并贡献
  python tools/contribute_dataset.py --uid 2 --contributor "小明"

  # 导出全部评论
  python tools/contribute_dataset.py --all --contributor "团队"

  # 增量追加（只导出数据库中新增的评论，追加到已有文件）
  python tools/contribute_dataset.py --uid 2 --append --contributor "小明"

流程:
  1. 从 data/comments.db 导出 JSONL
  2. 校验导出文件格式
  3. 扫描统计信息
  4. 更新 datasets/manifest.json
  5. 输出建议的 git add/commit 命令
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import Set, Tuple

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
    parser.add_argument(
        "--append", action="store_true",
        help="增量模式：只导出数据库中新增的评论，追加到已有文件末尾。"
             " 文件不存在时自动退化为全量导出。",
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


def _generate_filename(uid: int | None, append_mode: bool = False) -> str:
    """根据导出模式生成文件名。

    增量模式用固定文件名（方便反复追加），全量模式加日期后缀。
    """
    if uid is not None:
        return f"comments_uid_{uid}.jsonl"
    if append_mode:
        # 增量全量导出用固定文件名，便于反复追加
        return "comments_all.jsonl"
    date_str = time.strftime("%Y-%m-%d")
    return f"comments_all_{date_str}.jsonl"


def export_comments(
    db_path: Path,
    out_path: Path,
    uid: int | None,
    since: int | None,
    until: int | None,
) -> int:
    """从数据库导出评论到 JSONL 文件（覆盖写入）；返回导出条数。"""
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


# ── 增量模式辅助函数 ──────────────────────────────────

def _read_existing_keys(filepath: Path) -> Set[Tuple[int, int, int]]:
    """读取 JSONL 文件中已有的 (rpid, oid, type) 主键集合。

    大文件友好：逐行流式读取，不一次性加载全部内容到内存。
    """
    keys: Set[Tuple[int, int, int]] = set()
    if not filepath.exists():
        return keys
    with filepath.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                keys.add((int(record["rpid"]), int(record["oid"]), int(record["type"])))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return keys


def export_comments_append(
    db_path: Path,
    out_path: Path,
    uid: int | None,
    since: int | None,
    until: int | None,
    existing_keys: Set[Tuple[int, int, int]],
) -> int:
    """增量导出：查询所有匹配评论，过滤掉已有主键，追加写入文件。

    返回新增条数。
    """
    sql, params = _build_export_query(uid, since, until)

    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params)
        # 追加模式：以 "a" 打开文件
        with out_path.open("a", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                item = {key: row[key] for key in COMMENT_COLUMNS}
                key = (int(item["rpid"]), int(item["oid"]), int(item["type"]))
                if key in existing_keys:
                    continue
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
    append_mode: bool = args.append

    filename = _generate_filename(uid, append_mode)
    out_path = out_dir / filename

    # ── 增量模式：读取已有主键 ──
    existing_keys: Set[Tuple[int, int, int]] = set()
    initial_existing_count = 0
    if append_mode and out_path.exists():
        print(f"📖 正在读取已有数据 {out_path.name} ...")
        existing_keys = _read_existing_keys(out_path)
        initial_existing_count = len(existing_keys)
        print(f"   已有 {initial_existing_count} 条记录，将跳过重复并追加新数据")

    # ── 1. 导出 ──
    if append_mode:
        if out_path.exists():
            action = "增量追加"
            count = export_comments_append(db_path, out_path, uid, args.since, args.until, existing_keys)
        else:
            action = "全量导出（文件不存在）"
            count = export_comments(db_path, out_path, uid, args.since, args.until)
        print(f"📤 正在{action}到 {out_path} ...")
        print(f"   新增: {count} 条 | 已有: {initial_existing_count} 条 | 合计: {count + initial_existing_count} 条")
    else:
        print(f"📤 正在导出到 {out_path} ...")
        if out_path.exists():
            print(f"⚠  文件已存在，将被覆盖: {out_path.name}")
            print(f"   如需增量追加，请使用 --append 参数")
        count = export_comments(db_path, out_path, uid, args.since, args.until)
        print(f"   导出完成: {count} 条评论")

    if count == 0:
        if append_mode and initial_existing_count > 0:
            print("✅ 没有新增数据，数据库与文件已同步。")
            return
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
    total = stats["comments"]  # 增量追加后，stats 是追加前的，需要重新扫描
    # 增量模式下 scan_jsonl_stats 扫描的是追加后的完整文件（因为文件已关闭）
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
    if append_mode:
        print(f'  git commit -m "data: 更新数据集 {filename}（+{count} 条）"')
    else:
        print(f'  git commit -m "data: 添加数据集 {filename}"')
    print()
    print(f"  贡献者: {args.contributor or '(未填写)'}")
    print(f"  文件:   {out_path}")
    print(f"  大小:   {out_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
