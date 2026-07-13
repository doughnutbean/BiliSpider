"""Repair crawl progress rows affected by old root-comment truncation logic.

This script only updates ``crawl_progress``. It does not delete comments, cookies,
or datasets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bilispider.comment_crawler import CommentDatabase, _SUSPECT_DONE_MAX_ROOT
from bilispider.paths import COMMENTS_DB_PATH


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mark suspect done videos as limited so they can be crawled again.",
    )
    parser.add_argument(
        "--db",
        default=str(COMMENTS_DB_PATH),
        help="SQLite comments database path. Defaults to the active BiliSpider data dir.",
    )
    parser.add_argument(
        "--max-root",
        type=int,
        default=_SUSPECT_DONE_MAX_ROOT,
        help="Rows with this many or fewer root comments are treated as suspect.",
    )
    parser.add_argument(
        "--skip-false-limited",
        action="store_true",
        help="Do not restore limited rows that already have enough root comments.",
    )
    args = parser.parse_args()

    with CommentDatabase(args.db) as db:
        suspect_done = db.repair_suspect_done_progress(max_root=args.max_root)
        false_limited = 0
        if not args.skip_false_limited:
            false_limited = db.repair_false_limited_progress(
                min_root=args.max_root + 1,
            )

    print(f"Repaired {suspect_done} suspect done progress rows in {args.db}")
    print(f"Restored {false_limited} false limited progress rows in {args.db}")


if __name__ == "__main__":
    main()
