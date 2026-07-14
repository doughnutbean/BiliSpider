"""Shared filesystem paths for BiliSpider."""

from __future__ import annotations

import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_data_dir() -> Path:
    override = os.environ.get("BILISPIDER_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "BiliSpider" / "data"
        return Path.home() / "AppData" / "Roaming" / "BiliSpider" / "data"

    return PROJECT_ROOT / "data"


DATA_DIR = _default_data_dir()

COOKIES_PATH = DATA_DIR / "cookies.json"
CONFIG_PATH = DATA_DIR / "config.json"
CRAWL_QUEUE_PATH = DATA_DIR / "crawl_queue.json"
COMMENTS_DB_PATH = DATA_DIR / "comments.db"
ONLINE_CACHE_DIR = DATA_DIR / "online_cache"


def ensure_data_dir() -> None:
    """Create the runtime data directory if it does not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
