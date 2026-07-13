"""Remote JSONL dataset synchronization for BiliSpider."""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

from .dataset_tools import import_jsonl
from .paths import DATA_DIR, ensure_data_dir

DEFAULT_REMOTE_MANIFEST_URL = (
    "https://github.com/doughnutbean/BiliSpider/releases/latest/download/"
    "bilispider-data-manifest.json"
)
DEFAULT_RELEASE_DOWNLOAD_BASE = (
    "https://github.com/doughnutbean/BiliSpider/releases/latest/download"
)
REMOTE_SYNC_STATE_PATH = DATA_DIR / "remote_sync_state.json"

ProgressCallback = Callable[[str], None]


def load_sync_state(path: Path | None = None) -> dict[str, Any]:
    state_path = path or REMOTE_SYNC_STATE_PATH
    if not state_path.exists():
        return {"version": 1, "files": {}}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "files": {}}
    if not isinstance(data, dict):
        return {"version": 1, "files": {}}
    data.setdefault("version", 1)
    data.setdefault("files", {})
    if not isinstance(data["files"], dict):
        data["files"] = {}
    return data


def save_sync_state(state: dict[str, Any], path: Path | None = None) -> None:
    state_path = path or REMOTE_SYNC_STATE_PATH
    ensure_data_dir()
    state.setdefault("version", 1)
    state.setdefault("files", {})
    state["last_checked_at"] = int(time.time())
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _download_json(url: str, timeout: int = 30) -> dict[str, Any]:
    resp = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "BiliSpider/remote-sync"},
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("Remote manifest must be a JSON object")
    return data


def _download_file(url: str, out_path: Path, timeout: int = 60) -> int:
    resp = requests.get(
        url,
        stream=True,
        timeout=timeout,
        headers={"User-Agent": "BiliSpider/remote-sync"},
    )
    resp.raise_for_status()
    total = 0
    with out_path.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=1024 * 512):
            if not chunk:
                continue
            fh.write(chunk)
            total += len(chunk)
    return total


def _iter_manifest_files(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw_files = manifest.get("files", [])
    if isinstance(raw_files, dict):
        items = []
        for name, entry in raw_files.items():
            if isinstance(entry, dict):
                item = dict(entry)
                item.setdefault("name", name)
                items.append(item)
        return items
    if isinstance(raw_files, list):
        return [item for item in raw_files if isinstance(item, dict)]
    return []


def _file_url(item: dict[str, Any]) -> str:
    url = (
        item.get("url")
        or item.get("download_url")
        or item.get("browser_download_url")
    )
    if url:
        return str(url)
    name = str(item.get("name", "")).strip()
    if not name:
        raise ValueError("Remote file entry is missing name/url")
    return f"{DEFAULT_RELEASE_DOWNLOAD_BASE}/{quote(name)}"


def sync_remote_datasets(
    manifest_url: str = DEFAULT_REMOTE_MANIFEST_URL,
    *,
    state_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Download remote JSONL gzip datasets and import new/changed files.

    The remote manifest supports either:
      {"files": [{"name": "...jsonl.gz", "url": "...", "sha256": "..."}]}
    or:
      {"files": {"...jsonl.gz": {"url": "...", "sha256": "..."}}}
    """
    def progress(message: str) -> None:
        if progress_callback:
            progress_callback(message)

    result: dict[str, Any] = {
        "success": False,
        "checked": 0,
        "downloaded": 0,
        "imported_files": 0,
        "read": 0,
        "inserted": 0,
        "skipped": 0,
        "errors": [],
        "up_to_date": False,
    }

    ensure_data_dir()
    state = load_sync_state(state_path)

    try:
        progress("正在检查远端数据清单...")
        manifest = _download_json(manifest_url)
        files = _iter_manifest_files(manifest)
        result["checked"] = len(files)
        if not files:
            result["up_to_date"] = True
            result["success"] = True
            save_sync_state(state, state_path)
            return result

        state_files = state.setdefault("files", {})
        with tempfile.TemporaryDirectory(prefix="bilispider-sync-") as tmp:
            tmp_dir = Path(tmp)
            for item in files:
                name = str(item.get("name", "")).strip()
                if not name.endswith(".jsonl.gz"):
                    continue
                expected_sha = str(item.get("sha256", "")).strip().lower()
                previous = state_files.get(name, {})
                if expected_sha and previous.get("sha256") == expected_sha:
                    continue

                url = _file_url(item)
                gz_path = tmp_dir / name
                jsonl_path = tmp_dir / name[:-3]
                progress(f"正在下载 {name}...")
                bytes_written = _download_file(url, gz_path)
                result["downloaded"] += 1

                actual_sha = _sha256_file(gz_path)
                if expected_sha and actual_sha.lower() != expected_sha:
                    raise ValueError(
                        f"{name} sha256 mismatch: expected {expected_sha}, got {actual_sha}"
                    )

                progress(f"正在解压 {name}...")
                with gzip.open(gz_path, "rb") as src, jsonl_path.open("wb") as dst:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        dst.write(chunk)

                progress(f"正在导入 {jsonl_path.name}...")
                imported = import_jsonl([jsonl_path])
                if not imported.get("success"):
                    errors = imported.get("errors") or [imported.get("error", "unknown import error")]
                    raise ValueError(f"{name} import failed: {'; '.join(map(str, errors[:3]))}")

                result["imported_files"] += 1
                result["read"] += int(imported.get("read", 0) or 0)
                result["inserted"] += int(imported.get("inserted", 0) or 0)
                result["skipped"] += int(imported.get("skipped", 0) or 0)
                state_files[name] = {
                    "sha256": expected_sha or actual_sha,
                    "size_bytes": int(item.get("size_bytes", bytes_written) or bytes_written),
                    "comments": int(item.get("comments", 0) or 0),
                    "imported_at": int(time.time()),
                    "read": int(imported.get("read", 0) or 0),
                    "inserted": int(imported.get("inserted", 0) or 0),
                    "skipped": int(imported.get("skipped", 0) or 0),
                }

        result["up_to_date"] = result["imported_files"] == 0
        result["success"] = True
        save_sync_state(state, state_path)
        return result
    except Exception as exc:
        result["errors"].append(str(exc))
        return result
