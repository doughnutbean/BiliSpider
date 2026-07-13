"""
B站登录模块 —— 扫码登录 + Cookie 持久化管理。

核心流程:
  1. 调用 B站二维码生成接口,获取登录二维码 URL 和 qrcode_key
  2. 在终端以 ASCII 形式打印二维码,用户用 B站 App 扫码
  3. 轮询扫码状态: 等待扫码 → 扫码成功 → 收集 Cookie
  4. 校验登录态,将有效 Cookie 持久化到 data/cookies.json

参考来源: biliskin 项目 (E:\\file\\school\\code\\biliskin)
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable, Optional

import requests

from .paths import COOKIES_PATH, ensure_data_dir

# 状态回调类型: 用于向调用方报告登录进度
StatusCallback = Optional[Callable[[str], None]]

# 项目根目录 (bilispider 包的上层目录)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COOKIES_PATH = str(COOKIES_PATH)

# B站通用请求头
_COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get_cookies_path() -> str:
    """返回 data/cookies.json 的绝对路径。"""
    return _COOKIES_PATH


def load_cookies() -> dict[str, str]:
    """
    从 data/cookies.json 加载已保存的 Cookie。

    返回:
        键为 Cookie 名称、值为 Cookie 值的字典。
        文件不存在或损坏时返回空字典。
    """
    try:
        with open(_COOKIES_PATH, "r", encoding="utf-8") as fh:
            cookies = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    if isinstance(cookies, dict):
        return {str(k): str(v) for k, v in cookies.items() if v}
    return {}


def save_cookies(cookies: dict[str, str]) -> None:
    """
    将 Cookie 字典持久化到 data/cookies.json。

    参数:
        cookies: Cookie 名称到值的映射字典
    """
    # 只保留有值的 Cookie 条目
    cleaned = {k: v for k, v in cookies.items() if v}
    ensure_data_dir()
    with open(_COOKIES_PATH, "w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, ensure_ascii=False, indent=2)


def get_cookie_string(cookies: dict[str, str] | None = None) -> str:
    """
    将 Cookie 字典格式化为 HTTP 请求头中可用的字符串。

    格式: "key1=value1; key2=value2; ..."

    参数:
        cookies: 若为 None,则自动从 data/cookies.json 加载
    """
    if cookies is None:
        cookies = load_cookies()
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


def is_logged_in(cookie_string: str | None = None) -> tuple[bool, Optional[str], Optional[int]]:
    """
    验证当前 Cookie 是否仍处于有效登录状态。

    返回:
        (是否已登录, 用户名, UID)
    """
    if cookie_string is None:
        cookie_string = get_cookie_string()

    if not cookie_string:
        return False, None, None

    headers = {
        **_COMMON_HEADERS,
        "Cookie": cookie_string,
        "Referer": "https://www.bilibili.com/",
    }

    try:
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        if data.get("isLogin"):
            return True, data.get("uname"), data.get("mid")
    except Exception:
        pass

    return False, None, None


def _ensure_basic_cookies(session: requests.Session) -> None:
    """
    确保 session 中存在 buvid3 等基础 Cookie。
    B站二维码接口需要这些基础 Cookie 才能正常生成二维码。
    """
    if "buvid3" in session.cookies:
        return
    try:
        resp = requests.get(
            "https://www.bilibili.com/",
            headers={
                "User-Agent": _COMMON_HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": _COMMON_HEADERS["Accept-Language"],
            },
            timeout=10,
        )
        for cookie in resp.cookies:
            if cookie.value and cookie.name not in session.cookies:
                session.cookies.set(cookie.name, cookie.value)
    except Exception:
        pass


def _passport_headers() -> dict:
    """构造 passport.bilibili.com 请求所需的请求头。"""
    return {
        **_COMMON_HEADERS,
        "Referer": "https://passport.bilibili.com/login",
        "Origin": "https://passport.bilibili.com",
    }


def _get_qrcode(session: requests.Session) -> dict:
    """调用 B站接口生成登录二维码,返回包含 url 和 qrcode_key 的字典。"""
    _ensure_basic_cookies(session)

    resp = requests.get(
        "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
        headers=_passport_headers(),
        cookies=session.cookies,
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取二维码失败: {payload.get('message', '未知错误')}")

    return payload["data"]  # {"url": "...", "qrcode_key": "..."}


def _poll_qrcode(session: requests.Session, qrcode_key: str) -> dict:
    """轮询二维码扫码状态。"""
    resp = requests.get(
        "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
        params={"qrcode_key": qrcode_key},
        headers=_passport_headers(),
        cookies=session.cookies,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _extract_cookies_from_login_url(session: requests.Session, login_url: str) -> None:
    """
    扫码成功后,从 B站返回的登录回调 URL 中提取 Cookie。
    通过跟随重定向链来收集服务端 Set-Cookie。
    """
    current_url = login_url
    # B站扫码后可能有多次重定向,最多跟随 5 次收集 Cookie
    for _ in range(5):
        resp = requests.get(
            current_url,
            headers={
                "User-Agent": _COMMON_HEADERS["User-Agent"],
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
            },
            cookies=session.cookies,
            allow_redirects=False,
            timeout=10,
        )
        for cookie in resp.cookies:
            if cookie.value:
                session.cookies.set(cookie.name, cookie.value)

        # 不再重定向,结束收集
        if resp.status_code not in {301, 302, 303, 307, 308}:
            break

        location = resp.headers.get("Location", "")
        if not location:
            break
        current_url = (
            location
            if location.startswith("http")
            else requests.compat.urljoin(current_url, location)
        )


def _exchange_refresh_token(session: requests.Session, refresh_token: str) -> None:
    """用 refresh_token 换取更多持久化 Cookie。"""
    try:
        resp = requests.get(
            "https://passport.bilibili.com/x/passport-login/web/cookie/info",
            params={"refresh_token": refresh_token},
            headers=_passport_headers(),
            cookies=session.cookies,
            timeout=10,
        )
        for cookie in resp.cookies:
            if cookie.value:
                session.cookies.set(cookie.name, cookie.value)
    except Exception:
        return


def qr_login(
    status_callback: StatusCallback = None,
    cancel_event: threading.Event | None = None,
    show_terminal_qr: bool = True,
) -> bool:
    """
    执行扫码登录流程,登录成功后自动将 Cookie 保存到 data/cookies.json。

    参数:
        status_callback: 可选的进度回调函数,接收状态描述字符串
        cancel_event: 可选的多线程取消事件,设置后中止登录
        show_terminal_qr: 是否在终端打印 ASCII 二维码。GUI 调用时应关闭。

    返回:
        True 表示登录成功,False 表示登录失败或用户取消
    """
    session = requests.Session()

    def _log(msg: str) -> None:
        if status_callback:
            status_callback(msg)
        else:
            print(msg)

    # ============================================================
    # 第一步: 生成二维码
    # ============================================================
    try:
        qr_data = _get_qrcode(session)
    except Exception as e:
        _log(f"获取二维码失败: {e}")
        return False

    qrcode_url = qr_data["url"]
    qrcode_key = qr_data["qrcode_key"]

    # ============================================================
    # 第二步: 显示二维码 (终端 ASCII + URL)
    # ============================================================
    _log("请使用哔哩哔哩手机 App 扫描下方二维码登录:")
    _log(f"二维码链接: {qrcode_url}")

    if show_terminal_qr:
        # 尝试在终端打印 ASCII 二维码
        try:
            import qrcode  # type: ignore

            qr = qrcode.QRCode(border=2)
            qr.add_data(qrcode_url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            _log("(提示: 安装 qrcode[pil] 可在终端直接显示二维码图案)")
        except Exception:
            pass

    # 向 GUI 调用方传递二维码 URL（供渲染图像用）
    if status_callback:
        status_callback(f"__QRCODE_URL__:{qrcode_url}")

    # ============================================================
    # 第三步: 轮询扫码状态
    # ============================================================
    if cancel_event is None:
        cancel_event = threading.Event()

    while True:
        if cancel_event.is_set():
            _log("已取消扫码登录。")
            return False

        try:
            result = _poll_qrcode(session, qrcode_key)
        except Exception as e:
            _log(f"轮询扫码状态失败: {e}")
            time.sleep(1.5)
            continue

        status_data = result.get("data", {})
        status_code = status_data.get("code", result.get("code"))

        # 状态码含义:
        #   0      — 扫码成功
        #   86038  — 二维码已过期
        #   86090  — 已扫码,等待用户在手机上确认
        #   86101  — 等待扫码
        if status_code == 0:
            break
        elif status_code == 86038:
            _log("二维码已过期,请重新运行登录程序。")
            return False
        elif status_code == 86090:
            _log("已扫码,请在手机上点击确认...")
        elif status_code != 86101:
            _log(f"扫码状态异常: code={status_code}")

        time.sleep(1.5)

    # ============================================================
    # 第四步: 扫码成功 — 收集 Cookie
    # ============================================================
    login_url = status_data.get("url", "")
    refresh_token = status_data.get("refresh_token", "")

    if login_url:
        _extract_cookies_from_login_url(session, login_url)

    if refresh_token:
        _exchange_refresh_token(session, refresh_token)

    # ============================================================
    # 第五步: 校验登录态并持久化
    # ============================================================
    all_cookies = {k: v for k, v in session.cookies.items() if v}
    cookie_string = "; ".join(f"{k}={v}" for k, v in all_cookies.items())

    logged_in, username, uid = is_logged_in(cookie_string)
    if logged_in:
        save_cookies(all_cookies)
        _log(f"✅ 登录成功: {username} (UID: {uid})")
        return True
    else:
        _log("扫码已确认,但登录校验失败。请重试。")
        return False
