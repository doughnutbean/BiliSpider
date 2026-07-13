"""
B站扫码登录工具。

运行此脚本将通过终端二维码完成 B站登录，
登录成功后 Cookie 自动保存到 data/cookies.json，
后续所有爬取脚本将自动使用该 Cookie。

用法:
    python login.py

初次使用请先安装 qrcode 依赖:
    pip install qrcode[pil]
"""

from bilispider.login import is_logged_in, load_cookies, qr_login


def main() -> None:
    # 先检查是否已经登录
    logged_in, username, uid = is_logged_in()
    if logged_in:
        print(f"当前已登录: {username} (UID: {uid})")
        answer = input("是否重新登录? (y/N): ").strip().lower()
        if answer != "y":
            print("保持当前登录状态,无需重新登录。")
            return

    print("\n正在生成登录二维码...\n")
    success = qr_login()

    if success:
        cookies = load_cookies()
        key_count = len(cookies)
        print(f"\n已保存 {key_count} 个 Cookie 字段到 data/cookies.json")
        print("现在可以运行 examples/get_my_info.py / examples/get_user_info.py / examples/get_user_videos.py")


if __name__ == "__main__":
    main()
