# bilispider — B站数据爬取工具

基于 Python + WBI 签名鉴权的 B站数据爬取实验项目。

复现自 [snozzz.cc - bilibili-spider](https://snozzz.cc/article/bilibili-spider)。

## 项目结构

```
bilispider/
├── bilispider/
│   ├── __init__.py           # 包初始化
│   ├── login.py              # 扫码登录 + Cookie 持久化
│   ├── wbi.py                # WBI 签名鉴权核心
│   ├── gui.py                # Tkinter 图形化界面（三标签页）
│   ├── comment_crawler.py    # 评论爬取引擎（数据库+速率控制+反风控）
│   └── proxy_pool.py         # 代理池（haiproxy/手动/flclash）
├── gui.py                    # GUI 启动入口
├── login.py                  # 扫码登录入口
├── crawl_comments.py         # 命令行评论爬取
├── benchmark.py              # API 稳定性基准测试
├── get_my_info.py            # 获取个人信息（无需签名）
├── get_user_info.py          # 获取用户主页（需 WBI 签名）
├── get_user_videos.py        # 获取用户视频列表（需 WBI 签名）
├── requirements.txt          # 依赖
├── config.json               # GUI 配置持久化
├── cookies.json              # 登录 Cookie
├── crawl_queue.json          # 待爬队列
├── comments.db               # SQLite 评论数据库
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 图形化界面（推荐）

```bash
python gui.py
```

三标签页功能：

| 标签页 | 功能 |
|---|---|
| 📋 用户信息 | 扫码登录 + UID 查询用户详情（粉丝/关注/获赞/播放量） |
| 🎬 视频列表 | 查询用户视频列表，BVID/播放量 |
| 💬 评论爬取 | UID/天数/视频数/代理配置 + 实时日志 + 进度条 + 速率控制面板 |

### 3. 命令行登录

```bash
python login.py
```

终端显示 ASCII 二维码，B站 App 扫码确认，Cookie 自动保存到 `cookies.json`。

### 4. 命令行脚本

所有脚本自动从 `cookies.json` 加载 Cookie。

```bash
python get_my_info.py                          # 个人信息
python get_user_info.py                        # 用户主页（修改 TARGET_UID）
python get_user_videos.py                      # 视频列表（修改 TARGET_UID + PAGE_NUM）
python crawl_comments.py 2 --days 30 --max-videos 5  # 评论爬取
python benchmark.py quick                      # 基准测试（quick/medium/overnight）
```

## GUI 功能详情

### 用户查询标签页
- **扫码登录** — 弹出二维码窗口，App 扫码自动登录
- **UID 查询** — 输入 UID，一键查询用户信息和视频列表
- **双标签展示** — 用户信息 / 视频列表分页展示
- **数据来源** — 合并三个 API 接口（acc/info + relation/stat + upstat）

### 评论爬取标签页
- **爬取配置** — UID / 最近天数(0=不限) / 最大视频数(0=不限) / 代理地址
- **速率控制面板** — 基础延迟(s) / 抖动(s) / 沉睡时长(min) / 自适应提速开关 / 自适应沉睡开关
- **实时状态** — 当前模式 / 延迟范围 / 请求速率(rpm) / 请求总数
- **待爬队列** — +队列按钮添加 UID / 清空 / 自动切换 / 目标为空时取队首
- **进度条** — 视频级别进度 + 标题显示
- **实时日志** — 黑色终端风格，完整输出爬取过程
- **评论检索** — 搜索框输入 UID，双源融合查询（本地 DB + 在线 API）
  - 弹出表格窗口：时间/来源/层级/视频/评论内容
  - 关键词过滤搜索框，实时筛选
  - 右键菜单：复制选中行 / 全选 / Ctrl+C
  - 导出 Excel（需 openpyxl）/ CSV 回退
  - 双击行跳转 B站视频页面
- **基准测试** — quick(30min) / medium(2h) / overnight(8h) 三档
  - 实时指标（进度 / rpm / 状态）
  - 完成后输出完整报告

### 配置持久化
- 关闭 GUI 时自动保存所有输入值到 `config.json`
- 下次启动自动恢复：UID / 天数 / 视频数 / 代理 / 速率参数

## 反风控体系

```
TLS层:   curl_cffi impersonate="chrome120" (回退 requests)
HTTP层:  Sec-Ch-Ua Client Hints + 5个UA轮换 + Accept/Origin等完整头
签名层:  WBI 动态签名 + 6小时时间缓存 + -352 异常强制刷新
频率层:  基础延迟1.5s~2.5s + 自适应调速 + 412 状态机
恢复层:  412x3 后自动沉睡(默认10min,自适应倍增) + 唤醒刷新Cookie/WBI/代理
代理层:  flclash 自动检测 + 手动配置 + haiproxy Redis 代理池
```
**状态机**：`正常 → 警戒(1~2次412) → 冷却(3+次412) → 沉睡 → 唤醒 → 正常`

## 数据库（comments.db）

| 表 | 说明 |
|---|---|
| `comments` | rpid / oid / type / mid / parent(0=一级) / root / ctime / message / like_count / crawl_time |
| `crawl_progress` | oid / root_pages_done / sub_progress / status(pending/crawling/done) |

特性：SQLite WAL 模式 / `INSERT OR IGNORE` 去重 / 断点续爬

## 命令行参数（crawl_comments.py）

| 参数 | 说明 |
|---|---|
| `--days N` | 最近 N 天（0=不限） |
| `--since YYYY-MM-DD` | 开始日期 |
| `--until YYYY-MM-DD` | 结束日期 |
| `--max-videos N` | 最多视频数（0=不限） |
| `--proxy URL` | 代理地址（可多次指定轮换） |

## WBI 签名机制

1. 从 `/x/web-interface/nav` 获取 `img_key` 和 `sub_key`
2. `mixinKeyEncTab` 打乱取前 32 位为 `mixin_key`
3. 参数排序过滤 + 时间戳 `wts`
4. MD5 签名得到 `w_rid`

## 参考来源

- [snozzz.cc - bilibili-spider](https://snozzz.cc/article/bilibili-spider)
- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)
- [Sparklewink/BiliBili-view](https://github.com/Sparklewink/BiliBili-view)
- [SpiderClub/haipproxy](https://github.com/SpiderClub/haipproxy)
