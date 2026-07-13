"""Print useful statistics for the local comments database."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilispider.paths import COMMENTS_DB_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show local comments database statistics.")
    parser.add_argument("--db", default=str(COMMENTS_DB_PATH), help="SQLite database path.")
    parser.add_argument("--top", type=int, default=10, help="Number of top UID/OID rows to show.")
    return parser.parse_args()


def scalar(conn: sqlite3.Connection, sql: str) -> int | None:
    return conn.execute(sql).fetchone()[0]


def format_time(ts: int | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def print_top(conn: sqlite3.Connection, label: str, column: str, limit: int) -> None:
    print(f"\nTop {limit} {label}:")
    rows = conn.execute(
        f"SELECT {column}, COUNT(*) AS count FROM comments GROUP BY {column} ORDER BY count DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        print("  -")
        return
    for value, count in rows:
        print(f"  {value}: {count}")


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        total = scalar(conn, "SELECT COUNT(*) FROM comments")
        root = scalar(conn, "SELECT COUNT(*) FROM comments WHERE parent=0")
        sub = scalar(conn, "SELECT COUNT(*) FROM comments WHERE parent>0")
        uid_count = scalar(conn, "SELECT COUNT(DISTINCT mid) FROM comments")
        oid_count = scalar(conn, "SELECT COUNT(DISTINCT oid) FROM comments")
        first_ctime = scalar(conn, "SELECT MIN(ctime) FROM comments")
        last_ctime = scalar(conn, "SELECT MAX(ctime) FROM comments")
        last_crawl = scalar(conn, "SELECT MAX(crawl_time) FROM comments")

        print(f"Database       : {db_path}")
        print(f"File size      : {db_path.stat().st_size:,} bytes")
        print(f"Comments       : {total}")
        print(f"Root comments  : {root}")
        print(f"Sub comments   : {sub}")
        print(f"Unique UIDs    : {uid_count}")
        print(f"Unique OIDs    : {oid_count}")
        print(f"First comment  : {format_time(first_ctime)}")
        print(f"Last comment   : {format_time(last_ctime)}")
        print(f"Last crawl     : {format_time(last_crawl)}")
        print_top(conn, "UIDs", "mid", args.top)
        print_top(conn, "OIDs", "oid", args.top)


if __name__ == "__main__":
    main()
