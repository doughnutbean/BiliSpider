"""数据集 manifest 管理模块。

维护 datasets/manifest.json，记录每个数据文件的元信息：
文件名、评论条数、UID/OID 覆盖数、导出时间、SHA256 哈希、贡献者。

供 tools/ 下的脚本和 bilispider 内部模块共用。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any

# ── 路径常量 ──────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = _PROJECT_ROOT / "datasets" / "manifest.json"
DATASETS_DIR = _PROJECT_ROOT / "datasets"

SCHEMA_VERSION = "1"

# 推荐的文件命名模式（与 validate_dataset 保持一致）
_NAME_PATTERN_DESCRIPTIONS = (
    "comments_uid_<uid>.jsonl",
    "comments_oid_<oid>.jsonl",
    "comments_all_<YYYY-MM-DD>.jsonl",
    "comments_all.jsonl",
)


# ── 核心读写 ──────────────────────────────────────────

def _default_manifest() -> dict[str, Any]:
    """返回空 manifest 模板。"""
    return {
        "version": SCHEMA_VERSION,
        "last_updated": "",
        "files": {},
    }


def load_manifest() -> dict[str, Any]:
    """读取 manifest.json；文件不存在时返回空模板。"""
    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return _default_manifest()


def save_manifest(manifest: dict[str, Any]) -> None:
    """写入 manifest.json，自动更新时间戳。"""
    manifest["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    manifest.setdefault("version", SCHEMA_VERSION)
    manifest.setdefault("files", {})
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ── 哈希 ──────────────────────────────────────────────

def compute_sha256(filepath: Path) -> str:
    """计算文件的 SHA256 哈希（分块读取，大文件友好）。"""
    sha = hashlib.sha256()
    with filepath.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


# ── 文件条目管理 ──────────────────────────────────────

def update_file_entry(
    manifest: dict[str, Any],
    filename: str,
    *,
    comments: int,
    unique_uids: int,
    unique_oids: int,
    contributor: str = "",
    filepath: Path | None = None,
) -> dict[str, Any]:
    """更新或创建 manifest 中某个数据文件的条目。

    返回更新后的条目 dict（已写入 manifest["files"]）。
    """
    entry: dict[str, Any] = {
        "comments": comments,
        "unique_uids": unique_uids,
        "unique_oids": unique_oids,
        "export_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "contributor": contributor or "",
    }
    # 如果提供了实际文件路径，补上哈希和文件大小
    if filepath is None:
        filepath = DATASETS_DIR / filename
    if filepath.exists():
        entry["sha256"] = compute_sha256(filepath)
        entry["size_bytes"] = filepath.stat().st_size
    manifest["files"][filename] = entry
    return entry


def remove_file_entry(manifest: dict[str, Any], filename: str) -> bool:
    """从 manifest 中移除指定文件条目；返回是否确实存在并删除了。"""
    if filename in manifest["files"]:
        del manifest["files"][filename]
        return True
    return False


# ── 目录扫描 ──────────────────────────────────────────

def scan_datasets_dir() -> list[Path]:
    """扫描 datasets/ 目录，返回所有 .jsonl 文件的排序列表（排除 manifest.json）。"""
    if not DATASETS_DIR.exists():
        return []
    return sorted(
        p for p in DATASETS_DIR.iterdir()
        if p.suffix == ".jsonl" and p.name != "manifest.json"
    )


# ── 数据统计（从 JSONL 文件） ─────────────────────────

def scan_jsonl_stats(filepath: Path) -> dict[str, Any]:
    """扫描单个 JSONL 文件，返回统计信息。

    返回 dict: comments, unique_uids, unique_oids, errors (list[str]).
    """
    comments = 0
    uids: set[int] = set()
    oids: set[int] = set()
    errors: list[str] = []

    with filepath.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{filepath}:{line_no} invalid JSON: {exc.msg}")
                continue
            if not isinstance(record, dict):
                errors.append(f"{filepath}:{line_no} not a JSON object")
                continue
            comments += 1
            if "mid" in record:
                uids.add(int(record["mid"]))
            if "oid" in record:
                oids.add(int(record["oid"]))

    return {
        "comments": comments,
        "unique_uids": len(uids),
        "unique_oids": len(oids),
        "uids": uids,
        "oids": oids,
        "errors": errors,
    }


# ── 聚合统计 ──────────────────────────────────────────

def aggregate_stats(file_stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """将多个文件的统计信息聚合为全局摘要。

    file_stats: {filename: {comments, unique_uids, unique_oids, uids?, oids?, ...}}

    优先使用原始 uid/oid 集合做精确去重（来自实时扫描）；
    集合不可用时回退到 unique_uids/unique_oids 计数累加（近似值）。
    """
    total_comments = 0
    all_uids: set[int] = set()
    all_oids: set[int] = set()
    has_raw_sets = False  # 是否有至少一个文件提供了原始集合

    for stats in file_stats.values():
        total_comments += stats.get("comments", 0)
        if "uids" in stats:
            all_uids.update(stats["uids"])
            has_raw_sets = True
        if "oids" in stats:
            all_oids.update(stats["oids"])
            has_raw_sets = True

    # 如果没有任何文件提供原始集合，回退到 unique 计数求和
    # （注意：跨文件可能有重叠 UID/OID，此值为近似上限）
    if not has_raw_sets:
        uid_sum = sum(s.get("unique_uids", 0) for s in file_stats.values())
        oid_sum = sum(s.get("unique_oids", 0) for s in file_stats.values())
        return {
            "total_comments": total_comments,
            "total_files": len(file_stats),
            "unique_uids": uid_sum,
            "unique_oids": oid_sum,
            "approximate": True,
        }

    return {
        "total_comments": total_comments,
        "total_files": len(file_stats),
        "unique_uids": len(all_uids),
        "unique_oids": len(all_oids),
    }
