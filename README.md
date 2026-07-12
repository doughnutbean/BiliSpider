# bilispider — B站数据爬取工具

基于 Python + WBI 签名鉴权的 B站数据爬取实验项目。

复现自 [snozzz.cc - bilibili-spider](https://snozzz.cc/article/bilibili-spider)。

## 项目结构

```
bilispider/
├── bilispider/
│   ├── __init__.py      # 包初始化
│   ├── login.py         # 扫码登录 + Cookie 持久化模块
│   ├── wbi.py           # WBI 签名鉴权核心模块
│   └── gui.py           # Tkinter 图形化界面
├── gui.py               # GUI 启动入口
├── login.py             # 扫码登录入口脚本
├── get_my_info.py       # 获取当前登录用户个人信息（无需签名）
├── get_user_info.py     # 获取指定用户主页信息（需 WBI 签名）
├── get_user_videos.py   # 获取指定用户视频列表（需 WBI 签名）
├── requirements.txt     # 依赖
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 扫码登录

```bash
python login.py
```

运行后终端会显示一个 ASCII 二维码（需安装 `qrcode[pil]`），使用 **哔哩哔哩手机 App** 扫码并确认登录。

登录成功后，Cookie 自动保存到项目根目录的 `cookies.json`。

> 💡 如果终端无法显示二维码图案，可以复制脚本输出的「二维码链接」在浏览器中打开。

**手动填入 Cookie（备选方案）：**

1. 浏览器登录 [B站](https://www.bilibili.com/)
2. 按 `F12` → Application → Cookies → `bilibili.com`
3. 复制完整的 Cookie 字符串到项目根目录手动创建 `cookies.json`

### 3. 运行脚本

所有脚本会自动从 `cookies.json` 加载 Cookie，无需手动填入。

**获取个人信息**（无需 WBI 签名）:

```bash
python get_my_info.py
```

**获取指定用户主页信息**（需要 WBI 签名）:

```bash
python get_user_info.py
```

修改脚本中的 `TARGET_UID` 为目标用户 UID 后运行。

**获取指定用户视频列表**（需要 WBI 签名）:

```bash
python get_user_videos.py
```

修改脚本中的 `TARGET_UID`（目标用户 UID）和 `PAGE_NUM`（页码）后运行。

### 4. 图形化界面（推荐）

```bash
python gui.py
```

提供直观的图形化操作界面，支持：

- **扫码登录** — 点击按钮弹出二维码窗口，App 扫码后自动登录
- **UID 查询** — 输入任意用户 UID，一键查询主页信息和视频列表
- **双标签展示** — 用户信息 / 视频列表分页展示，清晰直观
- **评论爬取** — 配置 UID+天数+视频数+代理，实时日志输出，支持随时停止

## WBI 签名机制说明

B站对部分 API 启用了 WBI 签名风控。未签名或签名错误会返回 `-352`（风控校验失败）、`-799`（请求频繁）等错误。

签名流程：

1. 从 `/x/web-interface/nav` 获取最新的 `img_key` 和 `sub_key`
2. 将两 key 拼接后通过 `mixinKeyEncTab` 打乱，取前 32 位作为 `mixin_key`
3. 对请求参数排序、过滤特殊字符，加上时间戳 `wts`
4. 参数字符串 + `mixin_key` 做 MD5 得到 `w_rid`
5. 将 `wts` 和 `w_rid` 附加到请求中发送

核心逻辑封装在 `bilispider/wbi.py`，无需关心内部细节即可调用。

## 参考来源

- [snozzz.cc - bilibili-spider](https://snozzz.cc/article/bilibili-spider)
- [bilibili-API-collect #885](https://github.com/SocialSisterYi/bilibili-API-collect/issues/885)
