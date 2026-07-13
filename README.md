# BiliSpider

BiliSpider 是一个面向学习和个人研究的 B 站数据查询、评论爬取和数据协作工具。v2 的目标是稳定协作：Tkinter GUI 保持轻量，SQLite 只留在本地，团队通过 `datasets/*.jsonl` 共享可校验的数据集。

请控制请求频率和爬取范围，不要把本项目用于高频批量请求或违反平台规则的用途。

## 功能概览

- 扫码登录并保存本地 Cookie。
- 查询当前账号、指定 UID 的主页信息和视频列表。
- 按 UID 爬取 UP 主视频评论，支持一级/二级评论、断点续爬、本地去重和队列。
- GUI 提供查询、评论爬取、数据协作、本地检索四个标签页。
- 数据协作统一使用 JSONL，配合 manifest 做提交前检查。
- 本地检索会融合 `data/comments.db` 和在线 API：本地有数据、在线可用、在线不可用都会显示明确状态。

## 快速开始

```bash
pip install -r requirements.txt
python login.py
python gui.py
```

命令行爬取示例：

```bash
python crawl_comments.py 2 --days 30 --max-videos 5
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--days N` | 只爬最近 N 天，`0` 表示不限 |
| `--since YYYY-MM-DD` | 只爬指定日期之后 |
| `--until YYYY-MM-DD` | 只爬指定日期之前 |
| `--max-videos N` | 最多处理 N 个视频，`0` 表示不限 |
| `--proxy URL` | 指定代理，可重复传入多个代理 |

## GUI v2

GUI 入口：

```bash
python gui.py
```

四个标签页：

| 标签页 | 用途 |
| --- | --- |
| 账号/查询 | 登录状态、账号信息、UID 信息和视频列表查询 |
| 评论爬取 | 输入 UID 后开始/停止爬取，管理队列、速率、日志和进度 |
| 数据协作 | 导出全部、按 UID 导出、拆分导出、导入 JSONL、校验 JSONL、查看数据库统计、批量删除 |
| 本地与在线检索 | 按 UID 搜索评论，合并本地数据库与在线 API 结果并标记来源 |

数据协作页的批量删除只扫描当前目录一层的 `.jsonl` 文件，不递归，不会删除目录、数据库、`manifest.json` 或 `.gitkeep`。删除前必须手动选择并确认。

## 本地数据

运行态数据放在 `data/`，不要提交：

| 文件 | 说明 |
| --- | --- |
| `data/cookies.json` | 登录 Cookie，包含敏感凭据 |
| `data/config.json` | GUI 本地配置 |
| `data/crawl_queue.json` | GUI 待爬队列 |
| `data/comments.db` | SQLite 评论数据库 |

协作时只提交 JSONL 数据集和 `datasets/manifest.json`。不要提交 SQLite、Cookie、WAL/SHM 文件或本地配置。

## 数据协作格式

推荐两种贡献方式：

1. 单文件快照：`datasets/comments_all_YYYY-MM-DD.jsonl`
2. 拆分目录：`datasets/by_uid/comments_uid_<uid>.jsonl` 或 `datasets/by_oid/comments_oid_<oid>.jsonl`

JSONL 每行是一条评论记录，导入时按 `(rpid, oid, type)` 自动去重。

导出全部：

```bash
python tools/export_comments.py --out datasets/comments_all_2026-07-13.jsonl --pretty-summary
```

按 UID/OID 导出：

```bash
python tools/export_comments.py --uid 2 --out datasets/comments_uid_2.jsonl --pretty-summary
python tools/export_comments.py --oid 123456 --out datasets/comments_oid_123456.jsonl --pretty-summary
```

拆分导出：

```bash
python tools/export_comments.py --split-by uid --out-dir datasets/by_uid --pretty-summary
python tools/export_comments.py --split-by oid --out-dir datasets/by_oid --pretty-summary
```

导入别人贡献的数据：

```bash
python tools/import_comments.py datasets/*.jsonl
```

PowerShell 不展开通配符时，导入脚本会自行展开 `datasets/*.jsonl`。

## v2 推荐工作流

```bash
python login.py
python crawl_comments.py 2 --days 30 --max-videos 5
python tools/export_comments.py --out datasets/comments_all_2026-07-13.jsonl --pretty-summary
python tools/prepare_dataset.py datasets/*.jsonl --update-manifest --check-manifest
git add datasets/comments_all_2026-07-13.jsonl datasets/manifest.json
git commit -m "data: add comments snapshot 2026-07-13"
```

提交前统一检查入口：

```bash
python tools/prepare_dataset.py datasets/*.jsonl --check-manifest
```

当新增、删除或重命名数据集后，重新生成 manifest：

```bash
python tools/prepare_dataset.py datasets/**/*.jsonl --update-manifest --check-manifest
```

## 数据质量工具

```bash
python tools/validate_dataset.py datasets/*.jsonl
python tools/db_stats.py
python tools/check_db.py
python tools/report_dataset.py
```

`prepare_dataset.py` 覆盖 JSONL 校验、重复主键检查、manifest 一致性、大文件提醒和命名规范。`tools/dev/rebuild_manifest.py` 仅作为维护脚本保留，日常请优先使用 `prepare_dataset.py --update-manifest`。

## 静态检查

```bash
python -m py_compile bilispider/*.py tools/*.py gui.py login.py crawl_comments.py
```

## Windows 单 EXE 安装包

推荐的 Windows 分发方式是：先用 PyInstaller 构建稳定的 `onedir` GUI 程序，再用 Inno Setup 打成单个安装程序 EXE。

```powershell
.\packaging\build_windows.ps1 -Version 0.2.0
```

安装包输出到：

```text
release\BiliSpiderSetup-0.2.0.exe
```

运行时数据不会打进安装包。开发环境仍使用项目内 `data\` 目录；打包后的 EXE 会把 Cookie、配置、队列和 SQLite 数据库保存到：

```text
%APPDATA%\BiliSpider\data
```

如需调试或便携部署，可设置 `BILISPIDER_DATA_DIR` 覆盖数据目录。如确实需要额外生成一个安装后本体也是单文件的便携 EXE：

```powershell
.\packaging\build_windows.ps1 -Version 0.2.0 -PortableOneFile
```

## 参考来源

- [snozzz.cc - bilibili-spider](https://snozzz.cc/article/bilibili-spider)
- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)
- [Sparklewink/BiliBili-view](https://github.com/Sparklewink/BiliBili-view)
- [SpiderClub/haipproxy](https://github.com/SpiderClub/haipproxy)
