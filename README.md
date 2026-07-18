# BiliSpider

BiliSpider 是一个面向学习、个人研究和小团队协作的 B 站数据查询、评论采集与本地分析工具。它提供轻量 Tkinter GUI、扫码登录、评论断点续爬、SQLite 本地存储、JSONL 数据协作、本地检索和词云分析能力。

请控制请求频率和采集范围，不要将本项目用于高频批量请求、绕过平台限制或违反平台规则的用途。

## 功能亮点

- 扫码登录并把 Cookie 保存到本机运行时数据目录。
- 按 UID 查询账号信息、视频列表，并采集视频一级/二级评论。
- 支持断点续爬、本地去重、队列、限速、冷却和 412 风控保护。
- 本地检索融合 SQLite 数据库与在线 API 结果，并标记数据来源。
- 本地检索结果可生成词云，支持保存 PNG、查看 Top 高频词、一键屏蔽无意义词。
- 停用词支持内置词库和用户自定义词库，用户词库保存在本机，不提交到 Git。
- 安装包默认不携带数据库，可在 GUI 中开启远端 JSONL 增量数据同步。
- 数据协作使用 JSONL + manifest，便于校验、导入、导出和团队共享。
- Windows 默认发布为单个安装程序 EXE，安装后数据仍写入用户目录。

## 快速开始

### 使用源码运行

```bash
pip install -r requirements.txt
python login.py
python gui.py
```

命令行采集示例：

```bash
python crawl_comments.py 2 --days 30 --max-videos 5
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--days N` | 只采集最近 N 天，`0` 表示不限 |
| `--since YYYY-MM-DD` | 只采集指定日期之后 |
| `--until YYYY-MM-DD` | 只采集指定日期之前 |
| `--max-videos N` | 最多处理 N 个视频，`0` 表示不限 |
| `--proxy URL` | 指定代理，可重复传入多个代理 |

### 使用 Windows 安装包

从 GitHub Releases 下载 `BiliSpiderSetup-x.y.z.exe` 后直接安装。默认安装到当前用户目录，不需要管理员权限。

安装版的运行时数据位于：

```text
%APPDATA%\BiliSpider\data
```

源码开发环境默认使用项目内的 `data\` 目录。需要调试或便携部署时，可以用环境变量覆盖：

```powershell
$env:BILISPIDER_DATA_DIR = "D:\BiliSpiderData"
```

## GUI 功能

启动 GUI：

```bash
python gui.py
```

主要标签页：

| 标签页 | 用途 |
| --- | --- |
| 用户查询 | 查看登录状态、当前账号、指定 UID 的主页信息和视频列表 |
| 评论爬取 | 输入 UID 后开始/停止采集，管理队列、速率、日志和进度 |
| 数据协作 | 导出、导入、校验 JSONL，查看数据库统计，执行拆分导出和批量删除 |
| 本地检索 | 按 UID 检索评论，合并本地数据库和在线 API 结果，支持导出与词云 |

爬取日志区会在你停留底部时自动跟随最新输出；如果你手动向上查看历史日志，新日志不会再强制把滚动条拉回底部。

## 词云与停用词

在“本地检索”页完成检索后，点击“词云”可以基于当前筛选结果生成词云预览。

词云窗口支持：

- 保存 PNG 图片。
- 放大、缩小、适应窗口。
- 查看 Top 50 高频词及词频。
- 选中高频词后一键“屏蔽”，并自动重新生成词云。
- 打开“停用词”编辑器，维护长期停用词。

用户停用词文件为一行一个词，源码环境保存在：

```text
data\wordcloud_stopwords.txt
```

安装版保存在：

```text
%APPDATA%\BiliSpider\data\wordcloud_stopwords.txt
```

该文件属于本地偏好，不应提交到 Git。内置停用词会始终生效，用户停用词只是在本机额外叠加。

## 本地数据与安全

运行时数据不要提交到仓库：

| 文件 | 说明 |
| --- | --- |
| `data/cookies.json` | 登录 Cookie，包含敏感凭据 |
| `data/config.json` | GUI 本地配置 |
| `data/crawl_queue.json` | GUI 待采集队列 |
| `data/comments.db` | SQLite 评论数据库 |
| `data/wordcloud_stopwords.txt` | 用户自定义词云停用词 |

协作时只提交可共享的 JSONL 数据集和 `datasets/manifest.json`。不要提交 SQLite 数据库、Cookie、WAL/SHM 文件、本地配置、抓包文件或构建产物。

## 远端数据同步

安装包不会内置 `comments.db` 或默认 JSONL 数据集。首次启动 GUI 时，程序会询问是否开启“启动时自动同步远端数据集”：

- 选择开启后，每次启动只先检查远端数据清单。
- 只有发现新的 `jsonl.gz` 增量包或文件哈希变化时，才会下载并合并到本地 SQLite。
- 合并仍按 `(rpid, oid, type)` 去重，不覆盖或删除用户本地已有数据。
- 同步状态记录在本机运行时数据目录中，避免同一数据包重复导入。

你也可以在“数据协作”页手动点击“立即同步”，或随时关闭“启动时自动同步”。

## 数据协作

推荐两种共享格式：

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

导入他人贡献的数据：

```bash
python tools/import_comments.py datasets/*.jsonl
```

PowerShell 不展开通配符时，导入脚本会自行展开 `datasets/*.jsonl`。

更多协作规则见 `docs/CONTRIBUTING_DATA.md`。

## 开发检查

提交前推荐运行：

```bash
python -m py_compile bilispider/*.py tools/*.py tools/dev/*.py gui.py login.py crawl_comments.py
python tools/prepare_dataset.py --check
```

本地存在数据库时，可以额外运行：

```bash
python tools/check_db.py
```

常用数据质量工具：

```bash
python tools/validate_dataset.py datasets/*.jsonl
python tools/db_stats.py
python tools/report_dataset.py
```

项目目录约定见 `docs/PROJECT_STRUCTURE.md`。临时探针和调试脚本应放入 `tools/dev/`，不要放在仓库根目录。

## Windows 安装包

推荐的 Windows 分发方式是：先用 PyInstaller 构建稳定的 `onedir` GUI 程序，再用 Inno Setup 打成单个安装程序 EXE。

```powershell
.\packaging\build_windows.ps1 -Version 0.4.0
```

输出文件：

```text
release\BiliSpiderSetup-0.4.0.exe
```

如确实需要额外生成安装后本体也是单文件的便携 EXE：

```powershell
.\packaging\build_windows.ps1 -Version 0.4.0 -PortableOneFile
```

默认发布只上传安装器 EXE，不上传本地数据库、Cookie、配置、`dist\`、`build\` 或 `release\` 目录。

安装包构建时会显式排除 `data\`、`datasets\*.jsonl`、Cookie、配置和 SQLite 数据库。词云依赖仍会增加安装包体积；若只想进一步压缩体积，需要继续精简词云依赖链。

## 参考资料

- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)
- [Sparklewink/BiliBili-view](https://github.com/Sparklewink/BiliBili-view)
- [SpiderClub/haipproxy](https://github.com/SpiderClub/haipproxy)
- [PyInstaller](https://pyinstaller.org/)
- [Inno Setup](https://jrsoftware.org/isinfo.php)
