# BiliSpider

BiliSpider 是一个基于 Python 的 B 站数据查询与评论爬取实验项目，包含扫码登录、WBI 签名、用户信息查询、视频列表查询、评论爬取、SQLite 持久化和 Tkinter 图形界面。

> 请仅将本项目用于学习、课程实验或个人研究。批量请求 B 站接口可能触发风控，请控制频率和范围。

## 功能概览

- 扫码登录并保存 Cookie
- 查询当前登录账号信息
- 通过 UID 查询用户主页信息和视频列表
- 按 UID 批量爬取 UP 主视频评论
- 支持一级评论、二级评论、断点续爬和本地去重
- GUI 支持查询、爬取、队列、速率控制、本地评论检索和导出
- 使用 JSONL 数据集进行多人协作，避免直接合并 SQLite 数据库

## 项目结构

```text
bilispider/
├── bilispider/                 # 核心包
│   ├── comment_crawler.py      # 评论爬取、速率控制、SQLite 存储
│   ├── gui.py                  # Tkinter GUI 主界面
│   ├── login.py                # 扫码登录与 Cookie 管理
│   ├── paths.py                # 项目路径与 data 目录管理
│   ├── proxy_pool.py           # 代理池
│   └── wbi.py                  # WBI 签名
├── data/                       # 本地运行数据，不提交数据库和 Cookie
├── datasets/                   # 可提交的 JSONL 评论数据集
├── docs/reference/             # 参考资料
├── examples/                   # 示例查询脚本
├── tools/                      # 数据导入导出、校验和检查工具
├── benchmark.py                # 爬取稳定性基准测试
├── crawl_comments.py           # 命令行评论爬取入口
├── gui.py                      # GUI 启动入口
├── login.py                    # 命令行扫码登录入口
└── requirements.txt
```

## 快速开始

安装依赖：

```bash
pip install -r requirements.txt
```

扫码登录：

```bash
python login.py
```

启动 GUI：

```bash
python gui.py
```

运行示例查询：

```bash
python examples/get_my_info.py
python examples/get_user_info.py
python examples/get_user_videos.py
```

命令行爬取评论：

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
| `--proxy URL` | 指定代理，可重复传入多个代理轮换 |

## 本地数据

运行时数据统一放在 `data/`：

| 文件 | 说明 |
| --- | --- |
| `data/cookies.json` | 登录 Cookie，包含敏感信息 |
| `data/config.json` | GUI 最近一次配置 |
| `data/crawl_queue.json` | GUI 待爬 UID 队列 |
| `data/comments.db` | SQLite 评论数据库 |

不要提交 `data/comments.db`、`data/cookies.json`、WAL 文件或队列文件。多人协作统一提交 `datasets/*.jsonl`。

## 数据协作流程

推荐数据集命名：

- `datasets/comments_uid_<uid>.jsonl`
- `datasets/comments_oid_<oid>.jsonl`
- `datasets/comments_all_<YYYY-MM-DD>.jsonl`

导出本地全部评论：

```bash
python tools/export_comments.py --out datasets/comments_all_2026-07-13.jsonl --pretty-summary
```

按 UID 或 OID 导出：

```bash
python tools/export_comments.py --uid 2 --out datasets/comments_uid_2.jsonl --pretty-summary
python tools/export_comments.py --oid 123456 --out datasets/comments_oid_123456.jsonl --pretty-summary
```

拆分成多个小文件，适合提交较大的本地数据：

```bash
python tools/export_comments.py --split-by uid --out-dir datasets/by_uid --pretty-summary
python tools/export_comments.py --split-by oid --out-dir datasets/by_oid --pretty-summary
```

调试时只导出少量数据：

```bash
python tools/export_comments.py --limit 100 --out datasets/comments_sample.jsonl --pretty-summary
```

提交前校验数据集：

```bash
python tools/validate_dataset.py datasets/*.jsonl
```

导入别人提交的数据：

```bash
python tools/import_comments.py datasets/*.jsonl
```

在 PowerShell 中也可以直接使用 `datasets/*.jsonl`，导入脚本会自行展开通配符。导入时按 `(rpid, oid, type)` 自动去重，重复导入不会产生重复数据。

完整贡献流程：

```bash
python crawl_comments.py 2 --days 30 --max-videos 5
python tools/export_comments.py --uid 2 --out datasets/comments_uid_2.jsonl --pretty-summary
python tools/validate_dataset.py datasets/comments_uid_2.jsonl
git add datasets/comments_uid_2.jsonl
git commit -m "Add comments dataset for uid 2"
```

## 数据质量工具

查看本地数据库统计：

```bash
python tools/db_stats.py
```

查看表结构并验证去重：

```bash
python tools/check_db.py
```

JSONL 校验会检查：

- 必需字段是否完整
- JSON 是否合法
- 是否存在空行
- `(rpid, oid, type)` 是否重复
- 文件名是否符合推荐规范
- 文件是否过大，过大时建议使用 `--split-by`

## 数据库表

| 表 | 说明 |
| --- | --- |
| `comments` | 评论明细，包含 rpid、oid、mid、parent、root、ctime、message、like_count、crawl_time |
| `crawl_progress` | 断点续爬进度，记录视频维度的爬取状态 |

数据库使用 SQLite WAL 模式，并通过 `INSERT OR IGNORE` 对评论去重。

## 基准测试

```bash
python benchmark.py quick
python benchmark.py medium
python benchmark.py overnight
```

三种模式分别用于短测、中测和长时间稳定性测试。测试会记录请求量、成功率、风控次数和评论入库量。

## 参考来源

- [snozzz.cc - bilibili-spider](https://snozzz.cc/article/bilibili-spider)
- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)
- [Sparklewink/BiliBili-view](https://github.com/Sparklewink/BiliBili-view)
- [SpiderClub/haipproxy](https://github.com/SpiderClub/haipproxy)
