"""Inspect data/comments.db and verify comment de-duplication."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilispider.paths import COMMENTS_DB_PATH


def main() -> None:
    db = COMMENTS_DB_PATH
    if not db.exists():
        raise SystemExit(f"Database not found: {db}")

    conn = sqlite3.connect(db)
    try:
        for table in ("comments", "crawl_progress"):
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            print(f"=== {table} ===")
            for col in cols:
                pk = " [PK]" if col[5] else ""
                print(f"  {col[1]:20s} {col[2]:10s}{pk}")

        count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        root = conn.execute("SELECT COUNT(*) FROM comments WHERE parent=0").fetchone()[0]
        sub = conn.execute("SELECT COUNT(*) FROM comments WHERE parent>0").fetchone()[0]
        print(f"\nTotal comments: {count}, root: {root}, sub: {sub}")

        print("\n=== De-duplication check ===")
        duplicate_count = conn.execute(
            """SELECT COUNT(*) FROM (
                   SELECT rpid, oid, type, COUNT(*) AS count
                   FROM comments
                   GROUP BY rpid, oid, type
                   HAVING count > 1
               )"""
        ).fetchone()[0]
        pk_cols = [
            row[1]
            for row in conn.execute("PRAGMA table_info(comments)").fetchall()
            if row[5]
        ]
        print(f"Primary key columns: {', '.join(pk_cols)}")
        print(f"Duplicate primary keys found: {duplicate_count}")

        print(f"\nDatabase: {db}")
        print(f"Size: {db.stat().st_size:,} bytes")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
