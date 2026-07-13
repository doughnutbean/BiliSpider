"""Export local comments from SQLite to merge-friendly JSONL files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import TextIO

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
    parser.add_argument("--out", help="Output JSONL path. Required unless --split-by is used.")
    parser.add_argument("--out-dir", default="datasets", help="Output directory for --split-by.")
    parser.add_argument("--split-by", choices=("uid", "oid"), help="Split output into one JSONL per UID or OID.")
    parser.add_argument("--uid", type=int, help="Only export comments from this user mid.")
    parser.add_argument("--oid", type=int, help="Only export comments under this video aid/oid.")
    parser.add_argument("--since", type=int, help="Only export comments with ctime >= this Unix timestamp.")
    parser.add_argument("--until", type=int, help="Only export comments with ctime <= this Unix timestamp.")
    parser.add_argument("--limit", type=int, help="Export at most this many comments.")
    parser.add_argument("--pretty-summary", action="store_true", help="Print UID/OID summary after export.")
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
    order_prefix = "mid" if args.split_by == "uid" else "oid"
    sql += f" ORDER BY {order_prefix}, oid, type, rpid"
    if args.limit is not None:
        sql += " LIMIT ?"
        params.append(args.limit)
    return sql, params


def row_to_item(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in COMMENT_COLUMNS}


def write_item(fh: TextIO, item: dict) -> None:
    fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")


def split_filename(split_by: str, key: int) -> str:
    prefix = "comments_uid" if split_by == "uid" else "comments_oid"
    return f"{prefix}_{key}.jsonl"


def print_summary(exported: int, uids: set[int], oids: set[int], outputs: list[Path]) -> None:
    print(f"Exported comments : {exported}")
    print(f"Unique UIDs       : {len(uids)}")
    print(f"Unique OIDs       : {len(oids)}")
    print(f"Output files      : {len(outputs)}")
    if outputs:
        preview = outputs[:5]
        for path in preview:
            print(f"  - {path}")
        if len(outputs) > len(preview):
            print(f"  ... {len(outputs) - len(preview)} more")


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)

    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be greater than 0")
    if not args.split_by and not args.out:
        raise SystemExit("--out is required unless --split-by is used")

    sql, params = build_query(args)

    exported = 0
    uids: set[int] = set()
    oids: set[int] = set()
    outputs: list[Path] = []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params)

        if args.split_by:
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            current_key: int | None = None
            current_fh: TextIO | None = None
            try:
                for row in rows:
                    item = row_to_item(row)
                    key = int(item["mid"] if args.split_by == "uid" else item["oid"])
                    if key != current_key:
                        if current_fh is not None:
                            current_fh.close()
                        current_key = key
                        path = out_dir / split_filename(args.split_by, key)
                        outputs.append(path)
                        current_fh = path.open("w", encoding="utf-8", newline="\n")
                    write_item(current_fh, item)
                    uids.add(int(item["mid"]))
                    oids.add(int(item["oid"]))
                    exported += 1
            finally:
                if current_fh is not None:
                    current_fh.close()
        else:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            outputs.append(out_path)
            with out_path.open("w", encoding="utf-8", newline="\n") as fh:
                for row in rows:
                    item = row_to_item(row)
                    write_item(fh, item)
                    uids.add(int(item["mid"]))
                    oids.add(int(item["oid"]))
                    exported += 1

    if args.pretty_summary:
        print_summary(exported, uids, oids, outputs)
    else:
        target = Path(args.out) if args.out and not args.split_by else Path(args.out_dir)
        print(f"Exported {exported} comments to {target}")
    print(f"Finished at {time.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
