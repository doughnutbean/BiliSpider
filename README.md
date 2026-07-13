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
- 支持 curl_cffi 浏览器 TLS 指纹模拟，缺失时自动回退到 requests
- 支持手动代理、FlClash 本地代理和 haipproxy Redis 代理池

## 项目结构

```text
bilispider/
├── bilispider/                 # 核心包
│   ├── __init__.py
│   ├── comment_crawler.py      # 评论爬取、速率控制、SQLite 存储
│   ├── gui.py                  # Tkinter GUI 主界面
│   ├── login.py                # 扫码登录与 Cookie 管理
│   ├── paths.py                # 项目路径与 data 目录管理
│   ├── proxy_pool.py           # 代理池
│   └── wbi.py                  # WBI 签名
├── data/                       # 本地运行数据，不建议提交
│   ├── config.json             # GUI 配置
│   ├── cookies.json            # 登录 Cookie
│   ├── crawl_queue.json        # 待爬 UID 队列
│   └── comments.db             # 评论数据库
├── datasets/                   # 可提交的 JSONL 评论数据集
├── docs/
│   └── reference/              # 参考资料与外部实现笔记
├── examples/                   # 示例查询脚本
│   ├── get_my_info.py
│   ├── get_user_info.py
│   └── get_user_videos.py
├── tools/                      # 调试与检查脚本
│   ├── check_db.py
│   ├── export_comments.py
│   ├── import_comments.py
│   └── test_comment_api.py
├── benchmark.py                # 爬取稳定性基准测试
├── crawl_comments.py           # 命令行评论爬取入口
├── gui.py                      # GUI 启动入口
├── login.py                    # 命令行扫码登录入口
├── requirements.txt
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 登录

```bash
python login.py
```

终端会显示二维码，用 B 站 App 扫码确认后，Cookie 会保存到 `data/cookies.json`。

### 3. 启动 GUI

```bash
python gui.py
```

GUI 会自动读取 `data/cookies.json`、`data/config.json` 和 `data/crawl_queue.json`。

### 4. 使用示例脚本

```bash
python examples/get_my_info.py
python examples/get_user_info.py
python examples/get_user_videos.py
```

`get_user_info.py` 和 `get_user_videos.py` 默认查询 UID `2`，可在脚本顶部修改 `TARGET_UID` 和 `PAGE_NUM`。

### 5. 命令行爬取评论

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

`cookies.json`、数据库和队列文件已加入 `.gitignore`。`config.json` 目前保留在仓库中，便于保存默认 GUI 配置。

## 数据协作

不要直接提交 `data/comments.db`。SQLite 数据库是二进制文件，多人修改后很难用 Git 合并；本项目改用 `datasets/*.jsonl` 作为可提交的数据交换格式。

导出本地评论：

```bash
python tools/export_comments.py --uid 2 --out datasets/comments_uid_2.jsonl
```

也可以按视频或时间范围导出：

```bash
python tools/export_comments.py --oid 123456 --out datasets/comments_oid_123456.jsonl
python tools/export_comments.py --since 1750000000 --out datasets/comments_recent.jsonl
```

导入别人提交的数据：

```bash
python tools/import_comments.py datasets/comments_uid_2.jsonl
```

批量导入：

```bash
python tools/import_comments.py datasets/*.jsonl
```

JSONL 每行是一条评论，导入时按 `(rpid, oid, type)` 自动去重，因此重复导入不会产生重复数据。

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
