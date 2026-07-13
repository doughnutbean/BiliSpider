# 数据贡献指南

感谢你贡献评论数据。v2 只协作 JSONL 数据集，不协作 SQLite 数据库或 Cookie。

## 可以提交什么

推荐两种方式：

| 方式 | 路径示例 | 适合场景 |
| --- | --- | --- |
| 单文件快照 | `datasets/comments_all_2026-07-13.jsonl` | 一次性提交本地完整导出 |
| 拆分目录 | `datasets/by_uid/comments_uid_2.jsonl` | 数据量较大，需要按 UID/OID 分批维护 |

也可以提交单个 UID/OID 文件，例如 `datasets/comments_uid_2.jsonl`，但大型数据更建议放入 `datasets/by_uid/` 或 `datasets/by_oid/`。

## 不要提交什么

| 不提交 | 原因 |
| --- | --- |
| `data/comments.db` | 本地 SQLite 数据库，体积大且不适合多人合并 |
| `data/cookies.json` | 登录凭据，包含敏感信息 |
| `data/*.db-wal` / `data/*.db-shm` | SQLite 临时文件 |
| `data/config.json` / `data/crawl_queue.json` | 个人运行状态 |
| 临时导出、测试文件 | 会污染协作历史 |

## 推荐流程

1. 登录：

```bash
python login.py
```

2. 爬取一小批数据：

```bash
python crawl_comments.py 2 --days 30 --max-videos 5
```

3. 导出 JSONL：

```bash
python tools/export_comments.py --out datasets/comments_all_2026-07-13.jsonl --pretty-summary
```

或拆分导出：

```bash
python tools/export_comments.py --split-by uid --out-dir datasets/by_uid --pretty-summary
python tools/export_comments.py --split-by oid --out-dir datasets/by_oid --pretty-summary
```

4. 校验并更新 manifest：

```bash
python tools/prepare_dataset.py datasets/**/*.jsonl --update-manifest --check-manifest
```

5. 提交：

```bash
git add datasets/ docs/CONTRIBUTING_DATA.md
git commit -m "data: add comments dataset"
```

## 校验规则

`tools/prepare_dataset.py` 会检查：

- 每行是否是合法 JSON 对象。
- 必需字段是否完整。
- 整数字段类型是否正确。
- `(rpid, oid, type)` 是否重复。
- 文件名是否符合推荐规范。
- 文件是否过大。
- `datasets/manifest.json` 是否与磁盘文件一致。

只校验不更新 manifest：

```bash
python tools/prepare_dataset.py datasets/*.jsonl --check-manifest
```

新增、删除或重命名 JSONL 后，请重新生成 manifest：

```bash
python tools/prepare_dataset.py datasets/**/*.jsonl --update-manifest --check-manifest
```

## 导入数据

拉取别人贡献的数据后，可以导入本地数据库：

```bash
python tools/import_comments.py datasets/*.jsonl
```

导入会按 `(rpid, oid, type)` 去重，重复导入不会产生重复评论。
