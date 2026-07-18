"""Import JSONL comment datasets into data/comments.db with SQLite de-duplication."""

from __future__ import annotations

import argparse
import glob
import json
from json import JSONDecodeError
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilispider.comment_crawler import CommentDatabase
from bilispider.paths import COMMENTS_DB_PATH, ensure_data_dir

COMMENT_COLUMNS = (
    "rpid",
    "oid",
    "type",
    "mid",
    "parent",
    "root",
    "ctime",
    "message",
    "picture_count",
    "like_count",
    "sub_count",
    "crawl_time",
)

INSERT_SQL = f"""
    INSERT OR IGNORE INTO comments
    ({', '.join(COMMENT_COLUMNS)})
    VALUES ({', '.join(['?'] * len(COMMENT_COLUMNS))})
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import JSONL comment datasets into data/comments.db."
    )
    parser.add_argument("files", nargs="+", help="JSONL dataset files to import.")
    parser.add_argument("--db", default=str(COMMENTS_DB_PATH), help="SQLite database path.")
    return parser.parse_args()


def normalize_record(record: dict, source: Path, line_no: int) -> tuple:
    if not isinstance(record, dict):
        raise ValueError(f"{source}:{line_no} JSON value must be an object")
    if "picture_count" not in record:
        record["picture_count"] = 0
    missing = [key for key in COMMENT_COLUMNS if key not in record]
    if missing:
        raise ValueError(f"{source}:{line_no} missing fields: {', '.join(missing)}")
    return tuple(record[key] for key in COMMENT_COLUMNS)


def expand_input_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for pattern in patterns:
        matches = sorted(Path(match) for match in glob.glob(pattern))
        if not matches:
            path = Path(pattern)
            if path.exists():
                matches = [path]
            else:
                raise SystemExit(f"Dataset not found: {pattern}")

        for path in matches:
            resolved = path.resolve()
            if resolved not in seen:
                files.append(path)
                seen.add(resolved)

    return files


def import_file(conn: sqlite3.Connection, path: Path) -> dict:
    read_count = 0
    empty_count = 0
    uids: set[int] = set()
    oids: set[int] = set()
    before = conn.total_changes

    with path.open("r", encoding="utf-8-sig") as fh:
        with conn:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    empty_count += 1
                    continue
                try:
                    record = json.loads(line)
                    values = normalize_record(record, path, line_no)
                except JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no} invalid JSON: {exc.msg}") from exc
                uids.add(int(record["mid"]))
                oids.add(int(record["oid"]))
                conn.execute(INSERT_SQL, values)
                read_count += 1

    inserted = conn.total_changes - before
    return {
        "read": read_count,
        "inserted": inserted,
        "skipped": read_count - inserted,
        "empty": empty_count,
        "uids": uids,
        "oids": oids,
    }


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    ensure_data_dir()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with CommentDatabase(str(db_path)):
        pass

    total_read = 0
    total_inserted = 0
    total_empty = 0
    all_uids: set[int] = set()
    all_oids: set[int] = set()
    files = expand_input_files(args.files)
    with sqlite3.connect(db_path) as conn:
        for path in files:
            try:
                stats = import_file(conn, path)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            total_read += stats["read"]
            total_inserted += stats["inserted"]
            total_empty += stats["empty"]
            all_uids.update(stats["uids"])
            all_oids.update(stats["oids"])
            print(
                f"{path}: read {stats['read']}, inserted {stats['inserted']}, "
                f"skipped {stats['skipped']}, uids {len(stats['uids'])}, oids {len(stats['oids'])}"
            )

    print("Done.")
    print(f"  Files       : {len(files)}")
    print(f"  Read        : {total_read}")
    print(f"  Inserted    : {total_inserted}")
    print(f"  Skipped     : {total_read - total_inserted}")
    print(f"  Empty lines : {total_empty}")
    print(f"  Unique UIDs : {len(all_uids)}")
    print(f"  Unique OIDs : {len(all_oids)}")


if __name__ == "__main__":
    main()
