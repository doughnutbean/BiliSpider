"""
使用 WBI 签名获取指定用户的主页信息。

对 /x/space/wbi/acc/info 接口发起请求,该接口需要 WBI 签名。

用法:
    # 第一步: 先扫码登录
    python login.py

    # 第二步: 获取用户信息
    python get_user_info.py

Cookie 自动从 cookies.json 加载,只需在脚本中填入目标用户的 UID。
"""

import requests

from bilispider.login import get_cookie_string, is_logged_in
from bilispider.wbi import enc_wbi, get_wbi_keys


# ============================================================
# ⚠️ 使用前请修改: 目标用户的 UID
#    (B站站长 bishi 的 UID 为 2)
# ============================================================
TARGET_UID = "2"


def get_user_info(uid: str, cookie: str = "") -> None:
    """
    使用 WBI 签名获取指定用户的完整信息 (基本信息 + 统计数据)。

    数据来源:
      /x/space/wbi/acc/info — 用户名/等级/性别/签名/生日
      /x/relation/stat      — 粉丝数/关注数
      /x/space/upstat       — 获赞数/总播放量

    参数:
        uid: 目标用户的 UID（数字字符串）
        cookie: 你的 B站 Cookie（可选,但建议填写以获取更完整数据）
    """
    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://space.bilibili.com/{uid}/",
    }
    if cookie and "SESSDATA" in cookie:
        base_headers["Cookie"] = cookie

    try:
        # ── 第一步: 获取 WBI 密钥 ──
        print("正在获取最新的 WBI keys...")
        img_key, sub_key = get_wbi_keys()
        print(f"  img_key: {img_key}, sub_key: {sub_key}")

        # ── 第二步: 并行请求三个接口 ──
        print(f"\n正在查询用户 UID={uid} 的信息...")

        # 接口1: 基本信息
        signed = enc_wbi({"mid": uid}, img_key=img_key, sub_key=sub_key)
        resp_info = requests.get(
            "https://api.bilibili.com/x/space/wbi/acc/info",
            params=signed, headers=base_headers, timeout=10,
        )
        resp_info.raise_for_status()
        info_data = resp_info.json()

        # 接口2: 粉丝/关注统计
        signed_stat = enc_wbi({"vmid": uid}, img_key=img_key, sub_key=sub_key)
        resp_stat = requests.get(
            "https://api.bilibili.com/x/relation/stat",
            params=signed_stat, headers=base_headers, timeout=10,
        )
        resp_stat.raise_for_status()
        stat_data = resp_stat.json()

        # 接口3: 获赞/播放统计
        signed_up = enc_wbi({"mid": uid}, img_key=img_key, sub_key=sub_key)
        resp_up = requests.get(
            "https://api.bilibili.com/x/space/upstat",
            params=signed_up, headers=base_headers, timeout=10,
        )
        resp_up.raise_for_status()
        upstat_data = resp_up.json()

        # ── 第三步: 合并展示 ──
        if info_data.get("code") != 0:
            print(f"\n[X] 请求失败，API 返回错误码 {info_data.get('code')}: {info_data.get('message')}")
            print(f"完整响应: {info_data}")
            return

        data = info_data["data"]

        # 从 stat 接口获取粉丝/关注
        follower_num = 0
        following_num = 0
        if stat_data.get("code") == 0:
            sd = stat_data["data"]
            follower_num = sd.get("follower", 0)
            following_num = sd.get("following", 0)

        # 从 upstat 接口获取获赞/播放
        likes_num = 0
        total_views = 0
        if upstat_data.get("code") == 0:
            ud = upstat_data["data"]
            likes_num = ud.get("likes", 0)
            archive = ud.get("archive", {})
            if isinstance(archive, dict):
                total_views = archive.get("view", 0)

        print("\n[OK] 请求成功！获取到的用户信息如下：")
        print(f"  - 用户名  : {data.get('name')}")
        print(f"  - UID     : {data.get('mid')}")
        print(f"  - 等级    : LV{data.get('level')}")
        print(f"  - 性别    : {data.get('sex')}")
        print(f"  - 签名    : {data.get('sign')}")
        print(f"  - 生日    : {data.get('birthday')}")
        print(f"  - 粉丝数  : {follower_num:,}")
        print(f"  - 关注数  : {following_num:,}")
        print(f"  - 获赞数  : {likes_num:,}")
        print(f"  - 总播放量: {total_views:,}")

    except requests.exceptions.RequestException as e:
        print(f"\n[X] 网络请求异常: {e}")
    except Exception as e:
        print(f"\n[X] 程序运行出错: {e}")


# --- 主程序入口 ---
if __name__ == "__main__":
    # 自动从 cookies.json 加载 Cookie
    cookie = get_cookie_string()
    if not cookie:
        print("[X] 未找到有效的 Cookie。")
        print("   请先运行 python login.py 扫码登录。")
        print("   若不想登录,也可以手动设置环境变量 BILI_COOKIE 后重试。")
    else:
        logged_in, username, uid = is_logged_in(cookie)
        if logged_in:
            print(f"当前登录: {username} (UID: {uid})")
        else:
            print("[!] Cookie 可能已失效,建议重新运行 python login.py 扫码登录。")

        get_user_info(uid=TARGET_UID, cookie=cookie)
