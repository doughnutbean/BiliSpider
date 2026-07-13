"""Repair crawl progress rows that were wrongly marked done after API truncation.

This script only updates ``crawl_progress``. It does not delete comments, cookies,
or datasets. Videos repaired by this script will be retried by the crawler.
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
    args = parser.parse_args()

    with CommentDatabase(args.db) as db:
        repaired = db.repair_suspect_done_progress(max_root=args.max_root)

    print(f"Repaired {repaired} suspect done progress rows in {args.db}")


if __name__ == "__main__":
    main()
