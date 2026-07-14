# Changelog

## v0.3.3

- Fixed the queue label initialization so existing `crawl_queue.json` entries are shown immediately on GUI startup.
- Hardened queue loading by accepting UTF-8 BOM files, normalizing UID values, filtering invalid entries, and removing duplicates.
- Moved remote dataset sync controls onto their own row so the auto-sync option no longer gets squeezed out of the data collaboration page.
- Fixed one-click export/publish error handling by decoding GitHub CLI output as UTF-8 and preserving exception text across Tkinter callbacks.
- Updated one-click export/publish to delete old `comments_*.jsonl.gz` and `comments_all_*.jsonl.gz` assets before uploading the latest remote dataset archive.
- Removed generated dataset snapshots and remote-sync state from Git tracking, and made the dataset checker skip ignored local JSONL assets unless they are passed explicitly.
- Prepared the Windows installer release as `BiliSpiderSetup-0.3.3.exe`.

## v0.3.2

- Added optional remote dataset synchronization for `jsonl.gz` GitHub Release assets, with first-run opt-in, manual sync, sha256 verification, and SQLite de-duplicated import.
- Made packaging boundaries explicit so runtime data, local config, cookies, SQLite databases, and JSONL datasets are not bundled into the installer.
- Reduced unused Jieba packaging inputs by removing unused analysis imports and excluding nonessential Jieba data folders from the PyInstaller bundle.
- Prepared the Windows installer release as `BiliSpiderSetup-0.3.2.exe`.

## v0.3.1

- Rewrote `README.md` as a user-first guide covering setup, GUI usage, local data safety, word cloud features, dataset collaboration, development checks, and Windows packaging.
- Added word cloud stopword management notes for Top word blocking, user-maintained stopwords, PNG export, and local-only preference storage.
- Improved the crawl log viewing experience so new output no longer forces the log view to the bottom while the user is reading earlier lines.
- Updated Windows packaging defaults and release instructions for `BiliSpiderSetup-0.3.1.exe`.
- Rechecked sensitive-file boundaries before release: runtime config, cookies, SQLite databases, build outputs, and user stopword preferences remain local-only.

## v0.3.0

- Prepared the Windows installer release as `BiliSpiderSetup-0.3.0.exe`.
- Cleaned the repository layout so developer probes live under `tools/dev/` instead of the repository root or user-facing tools directory.
- Removed local runtime configuration and machine-specific helper scripts from Git tracking.
- Rechecked packaging, runtime-data boundaries, and local validation commands before release.

## v2 - 稳定协作版

- 整理 Tkinter GUI 数据协作页，移除热修后残留的不可达旧逻辑。
- 数据协作页支持导出、导入、校验、数据库统计、拆分导出取消和批量删除确认。
- 批量删除限制为当前目录一层的 `.jsonl` 文件，并在删除前再次校验路径边界。
- 本地检索融合本地 SQLite 与在线 API，并明确展示在线 API 可用、无数据或不可用状态。
- `prepare_dataset.py` 成为提交前统一检查入口，覆盖 JSONL 校验、重复主键、大文件提醒、命名规范和 manifest 一致性。
- `prepare_dataset.py --update-manifest` 可在新增、删除或重命名数据集后重建 `datasets/manifest.json`。
- manifest 扫描支持 `datasets/by_uid/`、`datasets/by_oid/` 等拆分目录。
- 临时 manifest 初始化脚本移入 `tools/dev/rebuild_manifest.py`。
- README 和数据贡献文档更新为 v2 推荐工作流，明确 SQLite 数据库和 Cookie 不提交。

## v1

- 初始 GUI、登录、WBI 签名、用户信息查询、评论采集和 SQLite 持久化能力。
