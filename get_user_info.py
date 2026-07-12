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
    使用 WBI 签名获取指定用户的主页信息。

    参数:
        uid: 目标用户的 UID（数字字符串）
        cookie: 你的 B站 Cookie（可选,但建议填写以获取更完整数据）
    """
    api_url = "https://api.bilibili.com/x/space/wbi/acc/info"

    # 需要签名的参数
    params_to_sign = {"mid": uid}

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
            # 加上 Referer 是好习惯,模拟从用户空间页面发起的请求
            "Referer": f"https://space.bilibili.com/{uid}/",
        }
        if cookie and "SESSDATA" in cookie:
            headers["Cookie"] = cookie

        print(f"\n正在向 B站 API 请求用户 UID={uid} 的主页信息...")
        response = requests.get(
            api_url, params=signed_params, headers=headers, timeout=10
        )
        response.raise_for_status()
        result = response.json()

        if result.get("code") == 0:
            data = result["data"]
            print("\n🎉 请求成功！获取到的用户信息如下：")
            print(f"  - 用户名: {data.get('name')}")
            print(f"  - UID: {data.get('mid')}")
            print(f"  - 等级: LV{data.get('level')}")
            print(f"  - 性别: {data.get('sex')}")
            print(f"  - 签名: {data.get('sign')}")
            print(f"  - 粉丝数: {data.get('follower')}")
            print(f"  - 关注数: {data.get('following')}")
        else:
            print(f"\n❌ 请求失败，API 返回错误码 {result.get('code')}: {result.get('message')}")
            print(f"完整响应: {result}")

    except requests.exceptions.RequestException as e:
        print(f"\n❌ 网络请求异常: {e}")
    except Exception as e:
        print(f"\n❌ 程序运行出错: {e}")


# --- 主程序入口 ---
if __name__ == "__main__":
    # 自动从 cookies.json 加载 Cookie
    cookie = get_cookie_string()
    if not cookie:
        print("❌ 未找到有效的 Cookie。")
        print("   请先运行 python login.py 扫码登录。")
        print("   若不想登录,也可以手动设置环境变量 BILI_COOKIE 后重试。")
    else:
        logged_in, username, uid = is_logged_in(cookie)
        if logged_in:
            print(f"当前登录: {username} (UID: {uid})")
        else:
            print("⚠️ Cookie 可能已失效,建议重新运行 python login.py 扫码登录。")

        get_user_info(uid=TARGET_UID, cookie=cookie)
