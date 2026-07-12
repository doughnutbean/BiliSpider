"""
B站 WBI 签名鉴权模块。

B站对部分 API（如用户空间接口）启用了 WBI 签名风控。
前端在发起请求前需要对参数做加密签名，服务器端验签，不匹配则拒绝服务。

核心流程：
  1. 从导航接口 /x/web-interface/nav 获取最新的 img_key 和 sub_key
  2. 将两个 key 拼接后用 mixinKeyEncTab 打乱取前 32 位得到 mixin_key
  3. 对请求参数排序、过滤特殊字符后拼接，加上当前时间戳 wts
  4. 将拼接后的参数字符串 + mixin_key 做 MD5 得到 w_rid
  5. 将 wts 和 w_rid 附加到请求参数中发送

参考来源: https://github.com/SocialSisterYi/bilibili-API-collect/issues/885
"""

from functools import reduce
from hashlib import md5
import time
import urllib.parse

import requests

# B站 WBI 签名中用于对 imgKey + subKey 进行字符顺序打乱的映射表
# 这个表是固定的,无需修改 —— 即使 mixin_key 变化,打乱规则不变
mixin_key_enc_tab = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def get_mixin_key(orig: str) -> str:
    """
    对 img_key + sub_key 拼接后的字符串进行字符顺序打乱,
    取前 32 位作为 mixin_key（即签名时的 salt）。
    """
    return reduce(lambda s, i: s + orig[i], mixin_key_enc_tab, "")[:32]


def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """
    为请求参数进行 WBI 签名,返回附加了 wts 和 w_rid 的参数字典。

    签名步骤:
      1. 拼接 img_key + sub_key,通过 get_mixin_key 得到 salt
      2. 添加当前 Unix 时间戳 wts
      3. 按 key 字母序重排参数
      4. 过滤 value 中可能导致问题的特殊字符: !'()*
      5. URL 编码参数,拼接 salt 后做 MD5 得到 w_rid
    """
    mixin_key = get_mixin_key(img_key + sub_key)
    curr_time = round(time.time())

    # 添加时间戳
    params["wts"] = curr_time

    # 按 key 字母序排序（B站要求参数有序）
    params = dict(sorted(params.items()))

    # 过滤 value 中的特殊字符,避免影响签名校验
    params = {
        k: "".join(filter(lambda ch: ch not in "!'()*", str(v)))
        for k, v in params.items()
    }

    # URL 编码后拼接 mixin_key,做 MD5 得到 w_rid
    query = urllib.parse.urlencode(params)
    wbi_sign = md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = wbi_sign

    return params


def get_wbi_keys() -> tuple[str, str]:
    """
    从 B站导航接口获取最新的 img_key 和 sub_key。

    B站会不定期更换这两个 key,因此每次签名前都应动态获取,
    而非硬编码到代码中,否则签名会失效。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
    }

    # 导航接口无需登录即可获取 wbi 密钥
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    json_content = resp.json()

    # img_key 和 sub_key 隐藏在 wbi_img 的 URL 文件名中
    # 例如: https://i0.hdslb.com/bfs/wbi/xxx.png → 提取 xxx
    img_url: str = json_content["data"]["wbi_img"]["img_url"]
    sub_url: str = json_content["data"]["wbi_img"]["sub_url"]

    img_key = img_url.rsplit("/", 1)[1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[1].split(".")[0]

    return img_key, sub_key
