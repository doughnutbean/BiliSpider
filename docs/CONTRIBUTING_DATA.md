# 🙌 贡献数据指南

> 不会写代码？没关系。只要你运行过 BiliSpider、本地有一些评论数据，就能参与贡献。

## 我能贡献什么？

你本地 `data/comments.db` 里的每一条评论数据都可以导出成 **JSONL 文件**，提交到这个仓库的 `datasets/` 目录。

具体来说，你可以贡献：

- **某个 UP 主的全部评论**（比如你完整爬了 UID=2 的评论区）
- **你本地全部评论**（导出整个数据库）
- **某个特定日期范围的评论**

## 三步贡献法

整个流程只需要三步：

### 第一步：爬一小份数据

如果你还没有数据，先爬一些：

```bash
# 爬 UID=2 最近 7 天的评论（只爬前 3 个视频，快速出数据）
python crawl_comments.py 2 --days 7 --max-videos 3
```

> **怕风控？** 默认每请求间隔 2~4 秒，只要不疯狂刷就不会出问题。爬 3 个视频也就几十秒的事。

### 第二步：一键导出 + 提交

用一条命令完成导出、校验、登记：

```bash
# 按 UID 导出（推荐）
python tools/contribute_dataset.py --uid 2 --contributor "你的名字"

# 导出全部本地数据
python tools/contribute_dataset.py --all --contributor "你的名字"
```

这条命令会自动：
- 📤 从数据库导出 JSONL 文件到 `datasets/`
- 🔍 校验文件格式是否合法
- 📊 统计评论数、覆盖视频数
- 📋 更新 `datasets/manifest.json`（数据目录）

完成后，终端会提示你接下来要执行的 git 命令，照做就行：

```bash
git add datasets/comments_uid_2.jsonl datasets/manifest.json
git commit -m "data: 添加 UID=2 的评论数据集"
```

### 第三步：提交前检查（可选但推荐）

提交前跑一下自动检查，确保数据没问题：

```bash
python tools/prepare_dataset.py datasets/*.jsonl
```

检查通过会显示 ✅，有错误会告诉你具体哪里需要修。

## 哪些数据 **不要** 提交？

| ❌ 不要提交 | 原因 |
|---|---|
| `data/comments.db` | 这是你本地的数据库，很大，而且含个人信息 |
| `data/cookies.json` | 包含你的登录凭证，绝对不能公开 |
| `data/*.db-shm` / `*.db-wal` | 数据库临时文件 |
| 敏感评论内容 | 注意评论里是否包含他人隐私 |

## 命名规范

文件名请按以下格式（工具会自动帮你命名）：

| 格式 | 说明 |
|---|---|
| `comments_uid_<uid>.jsonl` | 单个 UP 主的数据 |
| `comments_all_<日期>.jsonl` | 全量导出（标上日期） |

## 查看数据全景

想看看仓库里现在有哪些数据？

```bash
# 生成 Markdown 报告
python tools/report_dataset.py

# 保存到文件（适合贴吧发帖）
python tools/report_dataset.py --out DATASET_REPORT.md
```

报告会告诉你：
- 现在总共有多少条评论
- 覆盖了多少个视频、多少个用户
- 每位贡献者贡献了多少
- 每个数据文件的详细信息

## 常见问题

**Q: 我不小心重复导出了，会重复提交吗？**
不会。导入时会按 `(rpid, oid, type)` 自动去重。但建议导出前先看看 `manifest.json`，确认是否已经有人导过同样的 UID。

**Q: 我导出了 100MB 的数据，怎么提交？**
超过 50MB 的文件建议拆分成小文件：
```bash
python tools/export_comments.py --split-by uid --out-dir datasets/by_uid
```
然后分批提交。

**Q: 爬数据会不会被封号？**
本项目内置了自适应风控机制——遇到风控会自动降速甚至沉睡 10 分钟。只要不是超高频率批量爬取，基本不会出问题。

---

> 有疑问？在 Issue 区提问，或者直接提 PR。数据协作这件事，人多力量大 💪
