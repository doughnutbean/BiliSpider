"""Lightweight application update checks for BiliSpider."""

from __future__ import annotations

import re
from typing import Any

import requests

from . import __version__

GITHUB_LATEST_RELEASE_API = (
    "https://api.github.com/repos/doughnutbean/BiliSpider/releases/latest"
)
GITHUB_RELEASES_URL = "https://github.com/doughnutbean/BiliSpider/releases/latest"
UPDATE_CHECK_INTERVAL = 24 * 3600


def _parse_version(value: str) -> tuple[int, ...]:
    text = value.strip().lower()
    if text.startswith("v"):
        text = text[1:]
    match = re.match(r"(\d+(?:\.\d+)*)", text)
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(remote: str, local: str = __version__) -> bool:
    remote_parts = list(_parse_version(remote))
    local_parts = list(_parse_version(local))
    width = max(len(remote_parts), len(local_parts))
    remote_parts.extend([0] * (width - len(remote_parts)))
    local_parts.extend([0] * (width - len(local_parts)))
    return tuple(remote_parts) > tuple(local_parts)


def check_latest_release(
    *,
    current_version: str = __version__,
    timeout: int = 10,
) -> dict[str, Any]:
    resp = requests.get(
        GITHUB_LATEST_RELEASE_API,
        timeout=timeout,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"BiliSpider/{current_version}",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("GitHub release response must be a JSON object")

    latest_version = str(data.get("tag_name") or data.get("name") or "").strip()
    if not latest_version:
        raise ValueError("GitHub latest release has no tag_name")
    release_url = str(data.get("html_url") or GITHUB_RELEASES_URL)

    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "release_url": release_url,
        "name": str(data.get("name") or latest_version),
        "published_at": str(data.get("published_at") or ""),
        "update_available": is_newer_version(latest_version, current_version),
    }
