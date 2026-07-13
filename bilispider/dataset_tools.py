"""共享数据操作模块。

提供导出、导入、校验、统计等可复用函数，供 CLI 工具和 GUI 共同调用。
所有函数返回结构化 dict，不直接 print；由调用方决定如何展示结果。
"""

from __future__ import annotations

import glob
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Callable

from .paths import COMMENTS_DB_PATH, ensure_data_dir

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


# ── 导出 ──────────────────────────────────────────────

def export_comments(
    db_path: str | Path = "",
    out_path: str | Path = "",
    uid: int | None = None,
    oid: int | None = None,
    since: int | None = None,
    until: int | None = None,
    limit: int | None = None,
    split_by: str = "",
    out_dir: str | Path = "datasets",
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """从 SQLite 导出评论到 JSONL 文件。

    参数:
        db_path: SQLite 数据库路径，默认 data/comments.db
        out_path: 输出 JSONL 路径（split_by 为空时必需）
        uid: 按 UP 主 mid 筛选
        oid: 按视频 oid 筛选
        since: Unix 时间戳，只导出 >= 此时间的评论
        until: Unix 时间戳，只导出 <= 此时间的评论
        limit: 最多导出条数
        split_by: "uid" 或 "oid"，按维度拆分输出
        out_dir: split_by 模式下的输出目录
        progress_callback: 进度回调 (current, total)

    返回:
        {"success": bool, "exported": int, "uids": set, "oids": set,
         "outputs": [Path, ...], "error": str | None}
    """
    result: dict[str, Any] = {
        "success": False, "exported": 0, "uids": set(), "oids": set(),
        "outputs": [], "error": None,
    }

    db_path = Path(db_path) if db_path else COMMENTS_DB_PATH
    if not db_path.exists():
        result["error"] = f"数据库不存在: {db_path}"
        return result

    # 构建查询
    where: list[str] = []
    params: list = []
    if uid is not None:
        where.append("mid = ?"); params.append(uid)
    if oid is not None:
        where.append("oid = ?"); params.append(oid)
    if since is not None:
        where.append("ctime >= ?"); params.append(since)
    if until is not None:
        where.append("ctime <= ?"); params.append(until)

    sql = f"SELECT {', '.join(COMMENT_COLUMNS)} FROM comments"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order_prefix = "mid" if split_by == "uid" else "oid"
    sql += f" ORDER BY {order_prefix}, oid, type, rpid"
    if limit is not None:
        sql += " LIMIT ?"; params.append(limit)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params)

            if split_by:
                out_dir = Path(out_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                current_key: int | None = None
                fh = None
                exported = 0
                try:
                    for row in rows:
                        item = {key: row[key] for key in COMMENT_COLUMNS}
                        key = int(item["mid"] if split_by == "uid" else item["oid"])
                        if key != current_key:
                            if fh:
                                fh.close()
                            current_key = key
                            prefix = "comments_uid" if split_by == "uid" else "comments_oid"
                            path = out_dir / f"{prefix}_{key}.jsonl"
                            result["outputs"].append(path)
                            fh = path.open("w", encoding="utf-8", newline="\n")
                        fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
                        result["uids"].add(int(item["mid"]))
                        result["oids"].add(int(item["oid"]))
                        exported += 1
                finally:
                    if fh:
                        fh.close()
            else:
                out_path = Path(out_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                result["outputs"].append(out_path)
                exported = 0
                with out_path.open("w", encoding="utf-8", newline="\n") as fh:
                    for row in rows:
                        item = {key: row[key] for key in COMMENT_COLUMNS}
                        fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
                        result["uids"].add(int(item["mid"]))
                        result["oids"].add(int(item["oid"]))
                        exported += 1
                if progress_callback:
                    progress_callback(exported, exported)

        result["exported"] = exported
        result["success"] = True
    except Exception as exc:
        result["error"] = str(exc)

    return result


# ── 导入 ──────────────────────────────────────────────

INSERT_SQL = f"""
    INSERT OR IGNORE INTO comments
    ({', '.join(COMMENT_COLUMNS)})
    VALUES ({', '.join(['?'] * len(COMMENT_COLUMNS))})
"""


def import_jsonl(
    files: list[str | Path],
    db_path: str | Path = "",
    progress_callback: Callable[[str, int, int, int], None] | None = None,
) -> dict[str, Any]:
    """将 JSONL 文件导入 SQLite 数据库。

    参数:
        files: JSONL 文件路径列表（支持 glob 模式）
        db_path: 目标数据库路径
        progress_callback: (filename, read, inserted, skipped) 每文件回调

    返回:
        {"success": bool, "files": int, "read": int, "inserted": int, "skipped": int,
         "uids": set, "oids": set, "errors": [str, ...]}
    """
    result: dict[str, Any] = {
        "success": False, "files": 0, "read": 0, "inserted": 0, "skipped": 0,
        "uids": set(), "oids": set(), "errors": [],
    }

    db_path = Path(db_path) if db_path else COMMENTS_DB_PATH
    ensure_data_dir()

    # 展开 glob 并去重
    expanded: list[Path] = []
    seen: set[Path] = set()
    for pattern in files:
        pattern_str = str(pattern)
        matches = sorted(Path(m) for m in glob.glob(pattern_str))
        if not matches:
            p = Path(pattern_str)
            if p.exists():
                matches = [p]
        for path in matches:
            resolved = path.resolve()
            if resolved not in seen:
                expanded.append(path)
                seen.add(resolved)

    if not expanded:
        result["error"] = "未找到任何 JSONL 文件"
        return result

    try:
        from .comment_crawler import CommentDatabase
        with CommentDatabase(str(db_path)):
            pass
    except Exception:
        pass  # 表可能已存在

    try:
        with sqlite3.connect(db_path) as conn:
            for filepath in expanded:
                read_count = 0
                empty_count = 0
                file_uids: set[int] = set()
                file_oids: set[int] = set()
                before = conn.total_changes

                with filepath.open("r", encoding="utf-8-sig") as fh:
                    with conn:
                        for line_no, line in enumerate(fh, 1):
                            line = line.strip()
                            if not line:
                                empty_count += 1
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError as exc:
                                result["errors"].append(
                                    f"{filepath.name}:{line_no} 非法 JSON: {exc.msg}"
                                )
                                continue
                            if not isinstance(record, dict):
                                result["errors"].append(
                                    f"{filepath.name}:{line_no} 不是 JSON 对象"
                                )
                                continue
                            missing = [c for c in COMMENT_COLUMNS if c not in record]
                            if missing:
                                result["errors"].append(
                                    f"{filepath.name}:{line_no} 缺少字段: {', '.join(missing)}"
                                )
                                continue
                            values = tuple(record[c] for c in COMMENT_COLUMNS)
                            conn.execute(INSERT_SQL, values)
                            file_uids.add(int(record["mid"]))
                            file_oids.add(int(record["oid"]))
                            read_count += 1

                inserted = conn.total_changes - before
                skipped = read_count - inserted
                result["read"] += read_count
                result["inserted"] += inserted
                result["skipped"] += skipped
                result["uids"].update(file_uids)
                result["oids"].update(file_oids)
                result["files"] += 1

                if progress_callback:
                    progress_callback(filepath.name, read_count, inserted, skipped)

        result["success"] = True
    except Exception as exc:
        result["errors"].append(str(exc))
        result["error"] = str(exc)

    return result


# ── 校验 ──────────────────────────────────────────────

def validate_jsonl_files(
    files: list[str | Path],
    max_mb: int = 50,
    check_names: bool = True,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """校验 JSONL 数据集的格式和一致性。

    参数:
        files: 文件路径或 glob 模式列表
        max_mb: 超过此大小的文件触发警告
        check_names: 是否检查文件名规范
        progress_callback: (filename, current_row, total_in_file) 进度回调

    返回:
        {"success": bool, "files": int, "valid_rows": int, "unique_keys": int,
         "unique_uids": int, "unique_oids": int,
         "errors": [str, ...], "warnings": [str, ...]}
    """
    result: dict[str, Any] = {
        "success": False, "files": 0, "valid_rows": 0, "unique_keys": 0,
        "unique_uids": 0, "unique_oids": 0, "errors": [], "warnings": [],
    }

    # 展开 glob
    expanded: list[Path] = []
    seen: set[Path] = set()
    patterns = files if files else ["datasets/*.jsonl"]
    for pattern in patterns:
        pattern_str = str(pattern)
        matches = sorted(Path(m) for m in glob.glob(pattern_str))
        if not matches:
            p = Path(pattern_str)
            if p.exists():
                matches = [p]
        for path in matches:
            resolved = path.resolve()
            if resolved not in seen and path.name != "manifest.json":
                expanded.append(path)
                seen.add(resolved)

    if not expanded:
        result["errors"].append("未找到任何 JSONL 文件")
        return result

    seen_keys: dict[tuple[int, int, int], str] = {}
    all_uids: set[int] = set()
    all_oids: set[int] = set()
    total_rows = 0

    for path in expanded:
        # 大文件提醒
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > max_mb:
            result["warnings"].append(
                f"{path.name}: 文件 {size_mb:.1f} MB 超过 {max_mb} MB"
            )

        # 命名检查
        if check_names:
            if not any(p.match(path.name) for p in _NAME_PATTERNS):
                result["warnings"].append(
                    f"{path.name}: 文件名不符合规范，推荐: {', '.join(_NAME_PATTERN_DESC)}"
                )

        file_rows = 0
        with path.open("r", encoding="utf-8-sig") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    result["errors"].append(f"{path.name}:{line_no} 空行")
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    result["errors"].append(f"{path.name}:{line_no} 非法 JSON: {exc.msg}")
                    continue
                if not isinstance(record, dict):
                    result["errors"].append(f"{path.name}:{line_no} 不是 JSON 对象")
                    continue

                # 字段检查
                missing = [c for c in COMMENT_COLUMNS if c not in record]
                if missing:
                    result["errors"].append(f"{path.name}:{line_no} 缺少字段: {', '.join(missing)}")
                    continue

                # 类型检查
                for col in INTEGER_COLUMNS:
                    if col in record and record[col] is not None and not isinstance(record[col], int):
                        result["errors"].append(
                            f"{path.name}:{line_no} 字段 {col} 必须是整数"
                        )
                        break
                else:
                    file_rows += 1
                    total_rows += 1
                    all_uids.add(int(record["mid"]))
                    all_oids.add(int(record["oid"]))
                    key = (int(record["rpid"]), int(record["oid"]), int(record["type"]))
                    loc = f"{path.name}:{line_no}"
                    if key in seen_keys:
                        result["errors"].append(f"{loc} 主键重复 {key}，首次: {seen_keys[key]}")
                    else:
                        seen_keys[key] = loc

                if progress_callback and file_rows % 5000 == 0:
                    progress_callback(path.name, file_rows, 0)

    result["files"] = len(expanded)
    result["valid_rows"] = total_rows
    result["unique_keys"] = len(seen_keys)
    result["unique_uids"] = len(all_uids)
    result["unique_oids"] = len(all_oids)
    result["success"] = len(result["errors"]) == 0

    return result


# ── 数据库统计 ────────────────────────────────────────

def get_db_stats(
    db_path: str | Path = "",
    top_n: int = 10,
) -> dict[str, Any]:
    """获取本地评论数据库的统计信息。

    返回:
        {"success": bool, "total": int, "root": int, "sub": int,
         "unique_uids": int, "unique_oids": int, "first_ctime": int | None,
         "last_ctime": int | None, "last_crawl": int | None,
         "file_size": int, "top_uids": [(uid, count), ...],
         "top_oids": [(oid, count), ...], "error": str | None}
    """
    result: dict[str, Any] = {
        "success": False, "total": 0, "root": 0, "sub": 0,
        "unique_uids": 0, "unique_oids": 0,
        "first_ctime": None, "last_ctime": None, "last_crawl": None,
        "file_size": 0, "top_uids": [], "top_oids": [], "error": None,
    }

    db_path = Path(db_path) if db_path else COMMENTS_DB_PATH
    if not db_path.exists():
        result["error"] = f"数据库不存在: {db_path}"
        return result

    try:
        with sqlite3.connect(db_path) as conn:
            result["total"] = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
            result["root"] = conn.execute("SELECT COUNT(*) FROM comments WHERE parent=0").fetchone()[0]
            result["sub"] = conn.execute("SELECT COUNT(*) FROM comments WHERE parent>0").fetchone()[0]
            result["unique_uids"] = conn.execute("SELECT COUNT(DISTINCT mid) FROM comments").fetchone()[0]
            result["unique_oids"] = conn.execute("SELECT COUNT(DISTINCT oid) FROM comments").fetchone()[0]
            result["first_ctime"] = conn.execute("SELECT MIN(ctime) FROM comments").fetchone()[0]
            result["last_ctime"] = conn.execute("SELECT MAX(ctime) FROM comments").fetchone()[0]
            result["last_crawl"] = conn.execute("SELECT MAX(crawl_time) FROM comments").fetchone()[0]
            result["file_size"] = db_path.stat().st_size

            top_uids = conn.execute(
                "SELECT mid, COUNT(*) c FROM comments GROUP BY mid ORDER BY c DESC LIMIT ?",
                (top_n,),
            ).fetchall()
            result["top_uids"] = [(int(r[0]), r[1]) for r in top_uids]

            top_oids = conn.execute(
                "SELECT oid, COUNT(*) c FROM comments GROUP BY oid ORDER BY c DESC LIMIT ?",
                (top_n,),
            ).fetchall()
            result["top_oids"] = [(int(r[0]), r[1]) for r in top_oids]

        result["success"] = True
    except Exception as exc:
        result["error"] = str(exc)

    return result


# ── 快速校验（单文件，不检查跨文件重复） ──────────────

def quick_validate(filepath: Path) -> dict[str, Any]:
    """快速校验单个 JSONL 文件（不检查跨文件重复）。

    用于导出后的即时校验，轻量级。

    返回:
        {"success": bool, "errors": [str, ...], "rows": int}
    """
    result: dict[str, Any] = {"success": False, "errors": [], "rows": 0}

    if not filepath.exists():
        result["errors"].append(f"文件不存在: {filepath}")
        return result

    with filepath.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                result["errors"].append(f"{filepath.name}:{line_no} 空行")
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                result["errors"].append(f"{filepath.name}:{line_no} 非法 JSON: {exc.msg}")
                continue
            if not isinstance(record, dict):
                result["errors"].append(f"{filepath.name}:{line_no} 不是 JSON 对象")
                continue
            missing = [c for c in COMMENT_COLUMNS if c not in record]
            if missing:
                result["errors"].append(f"{filepath.name}:{line_no} 缺少字段: {', '.join(missing)}")
                continue
            result["rows"] += 1

    result["success"] = len(result["errors"]) == 0
    return result
