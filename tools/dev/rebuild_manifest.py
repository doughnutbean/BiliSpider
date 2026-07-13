"""Developer helper: rebuild datasets/manifest.json from JSONL files.

Normal contributors should use:
    python tools/prepare_dataset.py --update-manifest --check-manifest
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilispider.manifest import save_manifest, scan_datasets_dir, scan_jsonl_stats, update_file_entry


def main() -> None:
    files = scan_datasets_dir()
    manifest = {"version": "1", "last_updated": "", "files": {}}
    for path in files:
        key = path.relative_to(ROOT / "datasets").as_posix()
        stats = scan_jsonl_stats(path)
        update_file_entry(
            manifest,
            key,
            comments=stats["comments"],
            unique_uids=stats["unique_uids"],
            unique_oids=stats["unique_oids"],
            contributor="",
            filepath=path,
        )
        print(f"{key}: {stats['comments']} comments")
    save_manifest(manifest)
    print(f"Rebuilt datasets/manifest.json with {len(files)} file(s).")


if __name__ == "__main__":
    main()
