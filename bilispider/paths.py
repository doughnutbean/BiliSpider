"""Shared filesystem paths for BiliSpider."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

COOKIES_PATH = DATA_DIR / "cookies.json"
CONFIG_PATH = DATA_DIR / "config.json"
CRAWL_QUEUE_PATH = DATA_DIR / "crawl_queue.json"
COMMENTS_DB_PATH = DATA_DIR / "comments.db"


def ensure_data_dir() -> None:
    """Create the runtime data directory if it does not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
