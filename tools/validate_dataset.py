"""Validate JSONL comment datasets before committing them."""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import re
import sys

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

INTEGER_COLUMNS = {
    "rpid",
    "oid",
    "type",
    "mid",
    "parent",
    "root",
    "ctime",
    "like_count",
    "sub_count",
    "crawl_time",
}

NAME_PATTERNS = (
    re.compile(r"^comments_uid_\d+\.jsonl$"),
    re.compile(r"^comments_oid_\d+\.jsonl$"),
    re.compile(r"^comments_all_\d{4}-\d{2}-\d{2}\.jsonl$"),
    re.compile(r"^comments_all\.jsonl$"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate JSONL comment datasets.")
    parser.add_argument("files", nargs="+", help="JSONL files or glob patterns.")
    parser.add_argument("--max-mb", type=int, default=50, help="Warn when a file is larger than this size.")
    return parser.parse_args()


def expand_input_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = sorted(Path(match) for match in glob.glob(pattern))
        if not matches:
            path = Path(pattern)
            if path.exists():
                matches = [path]
            else:
                raise SystemExit(f"Dataset not found: {pattern}")
        for path in matches:
            resolved = path.resolve()
            if resolved not in seen:
                files.append(path)
                seen.add(resolved)
    return files


def name_matches(path: Path) -> bool:
    return any(pattern.match(path.name) for pattern in NAME_PATTERNS)


def validate_record(record: object, path: Path, line_no: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return [f"{path}:{line_no} JSON value must be an object"]

    missing = [key for key in COMMENT_COLUMNS if key not in record]
    if missing:
        errors.append(f"{path}:{line_no} missing fields: {', '.join(missing)}")

    for key in INTEGER_COLUMNS:
        if key in record and not isinstance(record[key], int):
            errors.append(f"{path}:{line_no} field {key} must be an integer")

    if "message" in record and record["message"] is not None and not isinstance(record["message"], str):
        errors.append(f"{path}:{line_no} field message must be a string or null")

    return errors


def main() -> None:
    args = parse_args()
    files = expand_input_files(args.files)
    errors: list[str] = []
    warnings: list[str] = []
    seen_keys: dict[tuple[int, int, int], str] = {}
    total_rows = 0
    uids: set[int] = set()
    oids: set[int] = set()

    for path in files:
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > args.max_mb:
            warnings.append(f"{path}: file is {size_mb:.1f} MB; consider --split-by uid or --split-by oid")
        if not name_matches(path):
            warnings.append(f"{path}: name does not follow comments_uid_<uid>.jsonl, comments_oid_<oid>.jsonl, or comments_all_<date>.jsonl")

        with path.open("r", encoding="utf-8-sig") as fh:
            for line_no, raw_line in enumerate(fh, 1):
                line = raw_line.strip()
                if not line:
                    errors.append(f"{path}:{line_no} empty line")
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{path}:{line_no} invalid JSON: {exc.msg}")
                    continue

                record_errors = validate_record(record, path, line_no)
                errors.extend(record_errors)
                if record_errors:
                    continue

                key = (int(record["rpid"]), int(record["oid"]), int(record["type"]))
                location = f"{path}:{line_no}"
                if key in seen_keys:
                    errors.append(f"{location} duplicate key {key}; first seen at {seen_keys[key]}")
                else:
                    seen_keys[key] = location
                uids.add(int(record["mid"]))
                oids.add(int(record["oid"]))
                total_rows += 1

    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        for error in errors[:50]:
            print(f"[ERROR] {error}")
        if len(errors) > 50:
            print(f"[ERROR] ... {len(errors) - 50} more")
        raise SystemExit(1)

    print(f"Validated files : {len(files)}")
    print(f"Valid rows      : {total_rows}")
    print(f"Unique keys     : {len(seen_keys)}")
    print(f"Unique UIDs     : {len(uids)}")
    print(f"Unique OIDs     : {len(oids)}")


if __name__ == "__main__":
    main()
