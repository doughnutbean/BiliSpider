"""Export local comments from SQLite to merge-friendly JSONL files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilispider.paths import COMMENTS_DB_PATH

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export comments from data/comments.db to a JSONL dataset."
    )
    parser.add_argument("--db", default=str(COMMENTS_DB_PATH), help="SQLite database path.")
    parser.add_argument("--out", required=True, help="Output JSONL path.")
    parser.add_argument("--uid", type=int, help="Only export comments from this user mid.")
    parser.add_argument("--oid", type=int, help="Only export comments under this video aid/oid.")
    parser.add_argument("--since", type=int, help="Only export comments with ctime >= this Unix timestamp.")
    parser.add_argument("--until", type=int, help="Only export comments with ctime <= this Unix timestamp.")
    return parser.parse_args()


def build_query(args: argparse.Namespace) -> tuple[str, list[int]]:
    where: list[str] = []
    params: list[int] = []

    if args.uid is not None:
        where.append("mid = ?")
        params.append(args.uid)
    if args.oid is not None:
        where.append("oid = ?")
        params.append(args.oid)
    if args.since is not None:
        where.append("ctime >= ?")
        params.append(args.since)
    if args.until is not None:
        where.append("ctime <= ?")
        params.append(args.until)

    sql = f"SELECT {', '.join(COMMENT_COLUMNS)} FROM comments"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY oid, type, rpid"
    return sql, params


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    out_path = Path(args.out)

    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sql, params = build_query(args)

    exported = 0
    with sqlite3.connect(db_path) as conn, out_path.open("w", encoding="utf-8", newline="\n") as fh:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(sql, params):
            item = {key: row[key] for key in COMMENT_COLUMNS}
            fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            exported += 1

    print(f"Exported {exported} comments to {out_path}")
    print(f"Finished at {time.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
