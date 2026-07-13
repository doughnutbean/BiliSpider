"""
词云生成工具模块。

功能:
  - 从评论列表中提取 message 文本
  - 中文分词 (jieba) + 停用词过滤
  - URL/BV号/纯数字/标点/过短词清洗
  - 使用 wordcloud 库生成 PNG 词云图片

依赖:
  pip install jieba wordcloud

用法:
    from bilispider.wordcloud_utils import generate_wordcloud
    img_bytes = generate_wordcloud(rows)       # 返回 PNG 的 bytes
    generate_wordcloud(rows, save_path)         # 保存到文件
"""
from __future__ import annotations

import os
import re
import sys
from io import BytesIO
from typing import Optional

# ─── 可选依赖检查 ─────────────────────────────────────────────

def _check_deps() -> tuple[bool, str]:
    """检查 wordcloud 和 jieba 是否可用。返回 (ok, error_message)。"""
    missing = []
    try:
        import jieba  # noqa: F401
    except ImportError:
        missing.append("jieba")
    try:
        import wordcloud  # noqa: F401
    except ImportError:
        missing.append("wordcloud")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    if missing:
        return False, f"缺少依赖: {', '.join(missing)}。请执行 pip install jieba wordcloud Pillow"
    return True, ""


# ─── 字体查找 ──────────────────────────────────────────────────

def _find_chinese_font() -> Optional[str]:
    """
    在 Windows 上查找可用的中文字体。
    优先级: Microsoft YaHei (微软雅黑) → SimHei (黑体) → SimSun (宋体)。
    macOS / Linux 回退到常见系统字体。
    """
    if sys.platform == "win32":
        # Windows 字体目录
        candidates = [
            ("Microsoft YaHei", "C:/Windows/Fonts/msyh.ttc"),
            ("Microsoft YaHei", "C:/Windows/Fonts/msyh.ttf"),
            ("SimHei", "C:/Windows/Fonts/simhei.ttf"),
            ("SimSun", "C:/Windows/Fonts/simsun.ttc"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            ("PingFang", "/System/Library/Fonts/PingFang.ttc"),
            ("Heiti SC", "/System/Library/Fonts/STHeiti Light.ttc"),
        ]
    else:
        candidates = [
            ("Noto Sans CJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            ("WenQuanYi", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        ]

    for _name, path in candidates:
        if os.path.exists(path):
            return path
    return None


# ─── 文本清洗 ──────────────────────────────────────────────────

# URL 匹配模式
_URL_PATTERN = re.compile(
    r'https?://[^\s]+|www\.[^\s]+',
    re.IGNORECASE,
)
# BV/AV 号匹配模式
_BVAV_PATTERN = re.compile(
    r'\b(BV[0-9A-Za-z]{10}|av\d+)\b',
    re.IGNORECASE,
)
# 纯数字（至少4位）→ 通常不是有意义的词
_PURE_NUMBER_PATTERN = re.compile(r'^\d{4,}$')
# 首尾标点清理
_PUNCT_STRIP_PATTERN = re.compile(r'^[\W_]+|[\W_]+$')


# 默认中文停用词集合 (常见高频无意义词)
_DEFAULT_STOP_WORDS: set[str] = {
    # B站常用
    "回复", "评论", "弹幕", "视频", "up主", "up", "b站", "bilibili",
    "哔哩哔哩", "投币", "点赞", "收藏", "转发", "三连",
    # 通用中文停用词
    "的", "了", "在", "是", "我", "有", "和", "就",
    "不", "人", "都", "一", "一个", "上", "也", "很",
    "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "他", "她", "它", "们",
    "那", "什么", "怎么", "哪个", "为什么",
    "可以", "这个", "那个", "还是", "已经", "因为",
    "所以", "但是", "如果", "虽然", "然后", "而且",
    "不过", "只是", "真的", "觉得", "感觉", "应该",
    "可能", "一定", "比较", "非常", "特别",
    # 语气词/助词
    "啊", "吧", "呢", "吗", "哈", "嘛", "呀", "哦",
    "嗯", "呃", "哎", "唉", "哇", "嘿", "哼",
    "哈哈", "呵呵", "嘿嘿", "嘻嘻",
    # 量词/代词
    "个", "种", "些", "点", "下", "次", "遍",
    "每", "各", "某", "另", "其他", "其它",
    "多少", "几", "怎么", "怎样", "这么", "那么",
    # 时间词
    "现在", "今天", "昨天", "明天", "今年", "去年",
    "以前", "以后", "之前", "之后", "时候",
    "小时", "分钟", "天", "年", "月", "日",
    # 常见网络用语
    "弹幕", "前方", "高能", "空降", "指挥部",
    "第一", "第二", "第三", "打卡", "来了",
    "哈哈哈哈", "hhhh",
}


def _clean_text(text: str) -> Optional[str]:
    """清洗单条评论文本,返回清洗后的字符串或 None (无有效内容)。"""
    if not text or not isinstance(text, str):
        return None

    # 去除 URL
    text = _URL_PATTERN.sub(" ", text)
    # 去除 BV/AV 号
    text = _BVAV_PATTERN.sub(" ", text)
    # 去除方括号表情 (如 [doge], [妙啊])
    text = re.sub(r'\[.*?\]', " ", text)
    # 去除 "回复 @用户名 :"
    text = re.sub(r'回复\s*@\S+?\s*[:：]?\s*', " ", text)
    # 合并空白
    text = re.sub(r'\s+', " ", text).strip()
    if not text or len(text) < 2:
        return None
    return text


def _tokenize(text: str, stop_words: set[str] | None = None) -> list[str]:
    """
    对清洗后的文本做中文分词,返回有效词列表。
    - 过短词 (len < 2) 过滤
    - 纯数字 (4位及以上) 过滤
    - 停用词过滤
    """
    import jieba
    if stop_words is None:
        stop_words = _DEFAULT_STOP_WORDS

    words: list[str] = []
    # 使用精确模式分词
    for word in jieba.cut(text, cut_all=False):
        word = word.strip()
        # 过滤条件
        if len(word) < 2:
            continue
        if _PURE_NUMBER_PATTERN.match(word):
            continue
        if word.isspace():
            continue
        # 停用词过滤
        if word in stop_words:
            continue
        # 首尾标点清理后仍有内容才保留
        word = _PUNCT_STRIP_PATTERN.sub("", word)
        if len(word) >= 2:
            words.append(word)
    return words


# ─── 词云生成 ──────────────────────────────────────────────────

def generate_wordcloud(
    rows: list[dict],
    save_path: str | None = None,
    width: int = 1000,
    height: int = 700,
    max_words: int = 200,
    background_color: str = "white",
    stop_words: set[str] | None = None,
) -> tuple[Optional[bytes], str]:
    """
    从评论列表生成词云 PNG。

    参数:
        rows: 评论字典列表,每条必须含 "message" 字段
        save_path: 可选保存路径 (跳过则只返回 bytes)
        width, height: 图片尺寸
        max_words: 最大词汇数
        background_color: 背景色
        stop_words: 自定义停用词集合 (None=默认)

    返回:
        (PNG bytes 或 None, 状态消息)
    """
    # 依赖检查
    ok, err = _check_deps()
    if not ok:
        return None, err

    # 字体检查
    font_path = _find_chinese_font()
    if font_path is None:
        return None, "未找到中文字体文件 (需要 Microsoft YaHei / SimHei 等)"

    # 提取并清洗文本
    all_words: list[str] = []
    for r in rows:
        msg = r.get("message", "")
        cleaned = _clean_text(msg)
        if cleaned is None:
            continue
        words = _tokenize(cleaned, stop_words)
        all_words.extend(words)

    if not all_words:
        return None, "当前结果没有可生成词云的有效词汇\n(评论可能都是纯数字、URL或表情)"

    # 词频统计
    freq: dict[str, int] = {}
    for w in all_words:
        freq[w] = freq.get(w, 0) + 1

    if len(freq) < 3:
        return None, f"有效词汇过少 (仅 {len(freq)} 个不同词),不适合生成词云"

    # 生成词云
    try:
        from wordcloud import WordCloud

        wc = WordCloud(
            font_path=font_path,
            width=width,
            height=height,
            max_words=max_words,
            background_color=background_color,
            collocations=False,       # 不合并搭配词
            scale=2,                  # 2x 渲染精度,放大后清晰
            margin=10,
        )
        wc.generate_from_frequencies(freq)

        # 转为 PNG bytes
        img = wc.to_image()
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        if save_path:
            img.save(save_path, format="PNG")

        return png_bytes, f"词云生成成功 ({len(freq)} 个词)"

    except Exception as e:
        return None, f"词云生成失败: {e}"
