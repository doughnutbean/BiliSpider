"""临时脚本：扫描现有 datasets/ 文件并初始化 manifest.json"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bilispider.manifest import (
    load_manifest, save_manifest, update_file_entry,
    scan_jsonl_stats, scan_datasets_dir,
)

files = scan_datasets_dir()
print("找到 JSONL 文件:", [f.name for f in files])

manifest = load_manifest()

for fp in files:
    print(f"扫描 {fp.name} ...")
    stats = scan_jsonl_stats(fp)
    print(f"  评论: {stats['comments']}, UIDs: {stats['unique_uids']}, OIDs: {stats['unique_oids']}")
    update_file_entry(
        manifest, fp.name,
        comments=stats['comments'],
        unique_uids=stats['unique_uids'],
        unique_oids=stats['unique_oids'],
        contributor="团队",
        filepath=fp,
    )

save_manifest(manifest)
print(f"manifest.json 初始化完成 ({len(manifest['files'])} 个文件)")
