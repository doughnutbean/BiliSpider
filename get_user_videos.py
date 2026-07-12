"""
使用 WBI 签名获取指定用户的视频列表。

对 /x/space/wbi/arc/search 接口发起请求,支持分页获取。

用法:
    python get_user_videos.py

前提：
    1. 填入有效的 B站 Cookie
    2. 填入目标用户的 UID (mid)
"""

import requests

from bilispider.wbi import enc_wbi, get_wbi_keys


# ============================================================
# ⚠️ 使用前请修改以下变量
# ============================================================
MY_COOKIE = "Input_your_cookie_here"       # 你的 B站 Cookie (建议填写)
TARGET_UID = "2"                           # 目标用户的 UID (B站站长 bishi 的 UID 为 2)
PAGE_NUM = 1                               # 要获取的页码 (从 1 开始)


def get_user_videos(uid: str, cookie: str = "", page_num: int = 1) -> None:
    """
    使用 WBI 签名获取指定用户的视频列表。

    参数:
        uid: 目标用户的 UID（数字字符串）
        cookie: 你的 B站 Cookie（可选,但建议填写）
        page_num: 页码,从 1 开始。每页最多 30 条视频。
    """
    api_url = "https://api.bilibili.com/x/space/wbi/arc/search"

    # 需要签名的参数 —— 这些是 B站空间视频列表接口的标准参数
    params_to_sign = {
        "mid": uid,
        "ps": 30,                       # 每页视频数量 (page size)
        "tid": 0,                       # 分区 ID,0 表示不筛选
        "pn": page_num,                 # 页码
        "keyword": "",                  # 搜索关键词,空表示不筛选
        "order": "pubdate",             # 排序方式: pubdate(最新发布)
        "platform": "web",
        "web_location": 1550101,        # B站内部埋点参数
        "order_avoided": "true",
    }

    try:
        # 第一步: 动态获取最新的 WBI 密钥
        print("正在获取最新的 WBI keys...")
        img_key, sub_key = get_wbi_keys()
        print(f"  img_key: {img_key}, sub_key: {sub_key}")

        # 第二步: 对参数进行 WBI 签名
        print("正在进行 WBI 签名...")
        signed_params = enc_wbi(
            params=params_to_sign, img_key=img_key, sub_key=sub_key
        )
        print(f"  签名完成, wts={signed_params['wts']}, w_rid={signed_params['w_rid'][:8]}...")

        # 第三步: 构造请求头并发送
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://space.bilibili.com/{uid}/video",
        }
        if cookie and "SESSDATA" in cookie:
            headers["Cookie"] = cookie

        print(f"\n正在获取用户 UID={uid} 第 {page_num} 页的视频列表...")
        response = requests.get(
            api_url, params=signed_params, headers=headers, timeout=15
        )
        response.raise_for_status()
        result = response.json()

        if result.get("code") == 0:
            video_list = result["data"]["list"]["vlist"]
            total_count = result["data"]["page"]["count"]

            if not video_list:
                print("\n📭 这一页没有视频。")
                return

            print(f"\n🎉 获取成功！共 {total_count} 个视频,本页 {len(video_list)} 个:")
            for idx, video in enumerate(video_list, 1):
                print(
                    f"  {idx:2d}. {video['title'][:40]:40s} | "
                    f"BVID: {video['bvid']:12s} | "
                    f"播放: {video['play']}"
                )
        else:
            print(f"\n❌ 获取失败，API 返回错误码 {result.get('code')}: {result.get('message')}")
            print(f"完整响应: {result}")

    except requests.exceptions.RequestException as e:
        print(f"\n❌ 网络请求异常: {e}")
    except Exception as e:
        print(f"\n❌ 程序运行出错: {e}")


# --- 主程序入口 ---
if __name__ == "__main__":
    if "SESSDATA" not in MY_COOKIE or MY_COOKIE == "Input_your_cookie_here":
        print("❌ 错误: 请在脚本中填入有效的 B站 Cookie (必须包含 SESSDATA 字段)")
    else:
        get_user_videos(uid=TARGET_UID, cookie=MY_COOKIE, page_num=PAGE_NUM)
