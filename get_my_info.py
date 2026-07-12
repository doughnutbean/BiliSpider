"""
使用 Cookie 获取当前登录用户的个人信息。

这个接口属于无需 WBI 签名的 API，直接带 Cookie 即可请求。

用法:
    python get_my_info.py

前提：需要在脚本内填入有效的 B站 Cookie（SESSDATA 字段必须有值）。
"""

import requests


# ============================================================
# ⚠️ 使用前请将下面的字符串替换为你自己的 B站 Cookie
#    获取方式: 浏览器登录 B站后, F12 → Application → Cookies → 复制完整 cookie
# ============================================================
MY_COOKIE = "Input_your_cookie_here"


def get_my_account_info(cookie: str) -> None:
    """
    使用 Cookie 获取当前登录用户的个人信息。

    这是一个典型的无需 WBI 签名的 API。
    """
    # 此接口无需任何 URL 参数,仅凭 Cookie 中 SESSDATA 即可识别用户身份
    api_url = "https://api.bilibili.com/x/space/myinfo"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
        "Cookie": cookie,
    }

    print("正在使用 Cookie 访问个人信息 API...")

    try:
        response = requests.get(url=api_url, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get("code") == 0:
            print("\n✅ 请求成功！账户信息如下：")
            account = result["data"]
            print(f"  - 用户名: {account['name']}")
            print(f"  - UID: {account['mid']}")
            print(f"  - 等级: LV{account['level']}")
            print(f"  - 硬币数: {account['coins']}")
            print(f"  - VIP 状态: {'是' if account['vip']['status'] == 1 else '否'}")
        else:
            print(f"\n❌ 请求失败，API 返回错误码 {result.get('code')}: {result.get('message')}")
            print(f"完整响应: {result}")

    except requests.exceptions.RequestException as e:
        print(f"\n❌ 网络请求异常: {e}")
    except (KeyError, TypeError) as e:
        print(f"\n❌ 解析响应失败,可能 Cookie 已失效: {e}")


# --- 主程序入口 ---
if __name__ == "__main__":
    if "SESSDATA" not in MY_COOKIE or MY_COOKIE == "Input_your_cookie_here":
        print("❌ 错误: 请在脚本中填入有效的 B站 Cookie (必须包含 SESSDATA 字段)")
    else:
        get_my_account_info(cookie=MY_COOKIE)
