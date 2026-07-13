"""Import JSONL comment datasets into data/comments.db with SQLite de-duplication."""

from __future__ import annotations

import argparse
import json
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
    missing = [key for key in COMMENT_COLUMNS if key not in record]
    if missing:
        raise ValueError(f"{source}:{line_no} missing fields: {', '.join(missing)}")
    return tuple(record[key] for key in COMMENT_COLUMNS)


def import_file(conn: sqlite3.Connection, path: Path) -> tuple[int, int]:
    read_count = 0
    before = conn.total_changes

    with path.open("r", encoding="utf-8") as fh:
        with conn:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                conn.execute(INSERT_SQL, normalize_record(record, path, line_no))
                read_count += 1

    inserted = conn.total_changes - before
    return read_count, inserted


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    ensure_data_dir()

    CommentDatabase(str(db_path)).close()

    total_read = 0
    total_inserted = 0
    with sqlite3.connect(db_path) as conn:
        for raw_file in args.files:
            path = Path(raw_file)
            if not path.exists():
                raise SystemExit(f"Dataset not found: {path}")
            read_count, inserted = import_file(conn, path)
            total_read += read_count
            total_inserted += inserted
            print(f"{path}: read {read_count}, inserted {inserted}, skipped {read_count - inserted}")

    print(f"Done. Read {total_read}, inserted {total_inserted}, skipped {total_read - total_inserted}.")


if __name__ == "__main__":
    main()
