# bilispider — B站数据爬取工具

基于 Python + WBI 签名鉴权的 B站数据爬取实验项目。

复现自 [snozzz.cc - bilibili-spider](https://snozzz.cc/article/bilibili-spider)。

## 项目结构

```
bilispider/
├── bilispider/
│   ├── __init__.py      # 包初始化
│   └── wbi.py           # WBI 签名鉴权核心模块
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

### 2. 获取 Cookie

1. 浏览器登录 [B站](https://www.bilibili.com/)
2. 按 `F12` → Application → Cookies → `bilibili.com`
3. 复制完整的 Cookie 字符串（至少需要 `SESSDATA` 字段）

### 3. 运行脚本

**获取个人信息**（无需 WBI 签名）:

```bash
python get_my_info.py
```

将脚本中的 `MY_COOKIE` 替换为你的真实 Cookie 后运行。

**获取指定用户主页信息**（需要 WBI 签名）:

```bash
python get_user_info.py
```

修改脚本中的 `MY_COOKIE` 和 `TARGET_UID` 后运行。

**获取指定用户视频列表**（需要 WBI 签名）:

```bash
python get_user_videos.py
```

修改脚本中的 `MY_COOKIE`、`TARGET_UID` 和 `PAGE_NUM` 后运行。

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
