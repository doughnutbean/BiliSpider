"""Pre-commit checks for BiliSpider JSONL datasets.

This is the single entry point before committing data. It validates JSONL
records, checks duplicate primary keys, warns about large files and naming
drift, and can verify or regenerate datasets/manifest.json.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path
import subprocess
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilispider.manifest import (
    DATASETS_DIR,
    aggregate_stats,
    load_manifest,
    save_manifest,
    scan_jsonl_stats,
    update_file_entry,
)

COMMENT_COLUMNS = (
    "rpid", "oid", "type", "mid", "parent", "root",
    "ctime", "message", "picture_count", "like_count", "sub_count", "crawl_time",
)

INTEGER_COLUMNS = {
    "rpid", "oid", "type", "mid", "parent", "root",
    "ctime", "picture_count", "like_count", "sub_count", "crawl_time",
}

NAME_PATTERNS = (
    re.compile(r"^comments_all_\d{4}-\d{2}-\d{2}\.jsonl$"),
    re.compile(r"^comments_uid_\d+\.jsonl$"),
    re.compile(r"^comments_oid_\d+\.jsonl$"),
    re.compile(r"^comments_all\.jsonl$"),
)

NAME_PATTERN_DESC = (
    "comments_all_<YYYY-MM-DD>.jsonl",
    "comments_uid_<uid>.jsonl",
    "comments_oid_<oid>.jsonl",
    "comments_all.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate JSONL datasets, check manifest consistency, and optionally "
            "regenerate datasets/manifest.json."
        )
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="JSONL files or glob patterns. Defaults to datasets/**/*.jsonl.",
    )
    parser.add_argument(
        "--max-mb",
        type=int,
        default=50,
        help="Warn when a JSONL file is larger than this size in MB. Default: 50.",
    )
    parser.add_argument(
        "--no-name-check",
        action="store_true",
        help="Skip recommended file naming checks.",
    )
    parser.add_argument(
        "--check-manifest",
        action="store_true",
        help="Verify datasets/manifest.json against the selected files.",
    )
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="Regenerate datasets/manifest.json from the selected files after validation.",
    )
    parser.add_argument(
        "--contributor",
        default="",
        help="Contributor name used when --update-manifest writes entries.",
    )
    return parser.parse_args()


def _glob(pattern: str) -> list[Path]:
    return sorted(Path(match) for match in glob.glob(pattern, recursive=True))


def is_git_ignored(path: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return completed.returncode == 0


def expand_files(patterns: list[str]) -> list[Path]:
    explicit_patterns = bool(patterns)
    if not explicit_patterns:
        patterns = ["datasets/**/*.jsonl"]
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = _glob(pattern)
        if not matches:
            path = Path(pattern)
            if path.exists():
                matches = [path]
            else:
                print(f"[SKIP] Dataset not found: {pattern}")
                continue
        for path in matches:
            if path.name == "manifest.json" or not path.is_file():
                continue
            if not explicit_patterns and is_git_ignored(path):
                continue
            resolved = path.resolve()
            if resolved not in seen:
                files.append(path)
                seen.add(resolved)
    return files


def dataset_key(path: Path) -> str:
    try:
        return path.resolve().relative_to(DATASETS_DIR.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def check_name(path: Path) -> str | None:
    if any(pattern.match(path.name) for pattern in NAME_PATTERNS):
        return None
    return (
        f"{path.name}: name does not match recommended formats: "
        f"{', '.join(NAME_PATTERN_DESC)}"
    )


def validate_record(record: object, path: Path, line_no: int) -> list[str]:
    prefix = f"{path}:{line_no}"
    if not isinstance(record, dict):
        return [f"{prefix} JSON value must be an object"]

    errors: list[str] = []
    missing = [
        field for field in COMMENT_COLUMNS
        if field not in record and field != "picture_count"
    ]
    if missing:
        errors.append(f"{prefix} missing fields: {', '.join(missing)}")

    for field in INTEGER_COLUMNS:
        if field in record and record[field] is not None and not isinstance(record[field], int):
            errors.append(f"{prefix} field {field} must be an integer")

    if "message" in record and record["message"] is not None and not isinstance(record["message"], str):
        errors.append(f"{prefix} field message must be a string or null")

    return errors


def check_manifest_consistency(files: list[Path]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest = load_manifest()
    manifest_files = set(manifest.get("files", {}).keys())
    disk_files = {dataset_key(path) for path in files}

    for name in sorted(disk_files - manifest_files):
        errors.append(f"manifest.json is missing entry: {name}")

    for name in sorted(manifest_files - disk_files):
        errors.append(f"manifest.json has stale entry: {name}")

    for name in sorted(manifest_files & disk_files):
        entry = manifest["files"][name]
        filepath = DATASETS_DIR / name
        if not filepath.exists():
            continue
        actual_size = filepath.stat().st_size
        recorded_size = entry.get("size_bytes", 0)
        if recorded_size and recorded_size != actual_size:
            warnings.append(
                f"{name}: manifest size {recorded_size} differs from actual size {actual_size}; "
                "run --update-manifest."
            )

    return errors, warnings


def validate_files(
    files: list[Path],
    *,
    max_mb: int,
    check_names: bool,
) -> tuple[list[str], list[str], dict[str, dict], int, dict[tuple[int, int, int], str]]:
    errors: list[str] = []
    warnings: list[str] = []
    file_stats: dict[str, dict] = {}
    seen_keys: dict[tuple[int, int, int], str] = {}
    total_rows = 0

    for path in files:
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > max_mb:
            warnings.append(
                f"{dataset_key(path)}: {size_mb:.1f} MB exceeds {max_mb} MB; "
                "prefer comments_all_<date>.jsonl for a single release snapshot or split by UID/OID directory."
            )

        if check_names:
            name_warning = check_name(path)
            if name_warning:
                warnings.append(f"{dataset_key(path)}: {name_warning}")

        stats = scan_jsonl_stats(path)
        file_stats[dataset_key(path)] = stats
        errors.extend(stats["errors"])

        with path.open("r", encoding="utf-8-sig") as fh:
            for line_no, raw_line in enumerate(fh, 1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                record_errors = validate_record(record, path, line_no)
                errors.extend(record_errors)
                if record_errors:
                    continue

                total_rows += 1
                key = (int(record["rpid"]), int(record["oid"]), int(record["type"]))
                location = f"{dataset_key(path)}:{line_no}"
                if key in seen_keys:
                    errors.append(f"{location} duplicate primary key {key}; first seen at {seen_keys[key]}")
                else:
                    seen_keys[key] = location

    return errors, warnings, file_stats, total_rows, seen_keys


def update_manifest(files: list[Path], file_stats: dict[str, dict], contributor: str) -> None:
    manifest = {
        "version": load_manifest().get("version", "1"),
        "last_updated": "",
        "files": {},
    }
    for path in files:
        key = dataset_key(path)
        stats = file_stats[key]
        update_file_entry(
            manifest,
            key,
            comments=stats["comments"],
            unique_uids=stats["unique_uids"],
            unique_oids=stats["unique_oids"],
            contributor=contributor,
            filepath=path,
        )
    save_manifest(manifest)


def main() -> None:
    args = parse_args()
    files = expand_files(args.files)

    if not files:
        print("No JSONL dataset files found.")
        print("Put files under datasets/ or pass explicit JSONL paths.")
        return

    errors, warnings, file_stats, total_rows, seen_keys = validate_files(
        files,
        max_mb=args.max_mb,
        check_names=not args.no_name_check,
    )

    if errors:
        for warning in warnings:
            print(f"[WARN] {warning}")
        print(f"\nFound {len(errors)} error(s):\n")
        for error in errors[:50]:
            print(f"  [ERROR] {error}")
        if len(errors) > 50:
            print(f"  ... {len(errors) - 50} more")
        raise SystemExit(1)

    if args.update_manifest:
        update_manifest(files, file_stats, args.contributor)
        print("Updated datasets/manifest.json")

    if args.check_manifest:
        manifest_errors, manifest_warnings = check_manifest_consistency(files)
        errors.extend(f"[MANIFEST] {error}" for error in manifest_errors)
        warnings.extend(f"[MANIFEST] {warning}" for warning in manifest_warnings)

    for warning in warnings:
        print(f"[WARN] {warning}")

    if errors:
        print(f"\nFound {len(errors)} error(s):\n")
        for error in errors[:50]:
            print(f"  [ERROR] {error}")
        if len(errors) > 50:
            print(f"  ... {len(errors) - 50} more")
        raise SystemExit(1)

    agg = aggregate_stats(file_stats)
    print("=" * 50)
    print("Dataset check passed")
    print("=" * 50)
    print(f"Files          : {len(files)}")
    print(f"Valid rows     : {total_rows}")
    print(f"Unique keys    : {len(seen_keys)}")
    print(f"Unique UIDs    : {agg['unique_uids']}")
    print(f"Unique OIDs    : {agg['unique_oids']}")


if __name__ == "__main__":
    main()
