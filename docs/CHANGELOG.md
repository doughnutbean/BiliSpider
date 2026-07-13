# Changelog

## v2 - 稳定协作版

- 整理 Tkinter GUI 数据协作页，移除热修后残留的不可达旧逻辑。
- 数据协作页支持导出、导入、校验、数据库统计、拆分导出取消和批量删除确认。
- 批量删除限制为当前目录一层 `.jsonl` 文件，并在删除前再次校验路径边界。
- 本地检索融合本地 SQLite 与在线 API，并明确展示在线 API 可用、无数据或不可用状态。
- `prepare_dataset.py` 成为提交前统一检查入口，覆盖 JSONL 校验、重复主键、大文件提醒、命名规范和 manifest 一致性。
- `prepare_dataset.py --update-manifest` 可在新增、删除或重命名数据集后重建 `datasets/manifest.json`。
- manifest 扫描支持 `datasets/by_uid/`、`datasets/by_oid/` 等拆分目录。
- 临时 manifest 初始化脚本移入 `tools/dev/rebuild_manifest.py`。
- README 和数据贡献文档更新为 v2 推荐工作流，明确 SQLite 数据库和 Cookie 不提交。

## v1

- 初始 GUI、登录、WBI 签名、用户信息查询、评论爬取和 SQLite 持久化能力。
