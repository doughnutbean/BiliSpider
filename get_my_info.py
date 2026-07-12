"""
使用 Cookie 获取当前登录用户的个人信息。

这个接口属于无需 WBI 签名的 API，直接带 Cookie 即可请求。

用法:
    # 第一步: 先扫码登录
    python login.py

    # 第二步: 获取个人信息
    python get_my_info.py

Cookie 自动从 cookies.json 加载,无需手动填入。
"""

import requests

from bilispider.login import get_cookie_string, is_logged_in


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
    # 自动从 cookies.json 加载 Cookie
    cookie = get_cookie_string()
    if not cookie:
        print("❌ 未找到有效的 Cookie。")
        print("   请先运行 python login.py 扫码登录。")
    else:
        logged_in, username, uid = is_logged_in(cookie)
        if logged_in:
            print(f"当前登录: {username} (UID: {uid})")
            get_my_account_info(cookie=cookie)
        else:
            print("❌ Cookie 已失效,请重新运行 python login.py 扫码登录。")
