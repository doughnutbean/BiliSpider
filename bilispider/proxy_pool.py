"""
代理池模块 — 多来源代理获取与轮换。

支持来源:
  1. haipproxy Redis 代理池 (需部署 haipproxy + Redis)
  2. 手动配置的代理列表
  3. flclash 本地代理自动检测

用法:
    from bilispider.proxy_pool import ProxyPool

    pool = ProxyPool()
    pool.add_manual("http://127.0.0.1:7890")   # flclash 代理
    pool.add_haipproxy(host="127.0.0.1", port=6379, db=0)  # haipproxy

    proxy = pool.get_proxy()       # 获取一个代理
    proxies = pool.get_proxies(5)  # 获取多个代理
"""

from __future__ import annotations

import random
import sys
import time
from typing import Optional

import requests as _plain_requests


class ProxyPool:
    """多来源代理池,支持轮换和健康检查。"""

    def __init__(self) -> None:
        self._manual: list[str] = []        # 手动配置的代理
        self._redis_proxies: list[str] = []  # 从 haipproxy Redis 获取的代理
        self._all_proxies: list[str] = []     # 合并后的代理列表
        self._index = 0
        self._redis_client = None            # haipproxy Redis 连接
        self._last_redis_fetch = 0.0
        self._redis_fetch_interval = 300.0   # 每5分钟刷新一次 Redis 代理
        self._test_url = "https://www.bilibili.com"
        self._test_timeout = 3.0

    # ── 添加代理 ──

    def add_manual(self, proxy: str) -> None:
        """添加手动配置的代理 (支持多次调用)。"""
        if proxy and proxy not in self._manual:
            self._manual.append(proxy)
            self._refresh_cache()

    def add_manuals(self, proxies: list[str]) -> None:
        """批量添加手动配置的代理。"""
        for p in proxies:
            if p and p not in self._manual:
                self._manual.append(p)
        self._refresh_cache()

    def add_haipproxy(
        self,
        host: str = "127.0.0.1",
        port: int = 6379,
        password: str = "",
        db: int = 0,
        site: str = "bilibili",
    ) -> bool:
        """
        接入 haipproxy Redis 代理池。

        参数:
            host: Redis 主机地址
            port: Redis 端口
            password: Redis 密码
            db: Redis 数据库编号
            site: 目标站点标识 (haipproxy 按站点分队列,如'zhihu','bilibili')

        返回:
            True 表示连接成功
        """
        try:
            import redis  # type: ignore
            self._redis_client = redis.Redis(
                host=host, port=port, password=password or None, db=db,
                socket_connect_timeout=3, socket_timeout=3,
            )
            self._redis_client.ping()
            self._redis_site = site
            print(f"[*] 已连接 haipproxy Redis ({host}:{port})")
            self._fetch_from_redis()
            return True
        except ImportError:
            print("[!] redis 库未安装,无法连接 haipproxy (pip install redis)")
            return False
        except Exception as e:
            print(f"[!] 连接 haipproxy Redis 失败: {e}")
            self._redis_client = None
            return False

    def auto_detect_flclash(self) -> bool:
        """自动检测本地 flclash 代理。"""
        auto_proxy = "http://127.0.0.1:7890"
        try:
            _plain_requests.get("http://127.0.0.1:7890", timeout=0.3)
        except Exception:
            return False
        self.add_manual(auto_proxy)
        return True

    # ── 获取代理 ──

    def get_proxy(self) -> Optional[str]:
        """获取一个可用代理 (轮换)。"""
        if not self._all_proxies:
            self._refresh_cache()
        if not self._all_proxies:
            return None
        proxy = self._all_proxies[self._index % len(self._all_proxies)]
        self._index += 1
        return proxy

    def get_proxies(self, count: int = 5) -> list[str]:
        """获取多个可用代理。"""
        if not self._all_proxies:
            self._refresh_cache()
        if not self._all_proxies:
            return []
        result = []
        for i in range(min(count, len(self._all_proxies))):
            result.append(self._all_proxies[(self._index + i) % len(self._all_proxies)])
        self._index += len(result)
        return result

    def get_proxy_dict(self) -> dict[str, str]:
        """获取代理字典 (用于 requests 的 proxies 参数)。"""
        p = self.get_proxy()
        if p:
            return {"http": p, "https": p}
        return {}

    def count(self) -> int:
        return len(self._all_proxies)

    # ── 健康检查 ──

    def test_proxy(self, proxy: str) -> bool:
        """测试代理是否可用 (针对 B站)。"""
        try:
            r = _plain_requests.get(
                self._test_url,
                proxies={"http": proxy, "https": proxy},
                timeout=self._test_timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            return r.status_code == 200
        except Exception:
            return False

    def validate_all(self) -> int:
        """验证所有代理的可用性,返回可用数量。"""
        valid = [p for p in self._all_proxies if self.test_proxy(p)]
        self._all_proxies = valid
        return len(valid)

    # ── 内部方法 ──

    def _refresh_cache(self) -> None:
        """刷新代理缓存: 合并手动 + Redis 来源。"""
        # 定期从 Redis 刷新
        if self._redis_client and time.time() - self._last_redis_fetch > self._redis_fetch_interval:
            self._fetch_from_redis()
        self._all_proxies = self._manual + self._redis_proxies
        random.shuffle(self._all_proxies)

    def _fetch_from_redis(self) -> None:
        """从 haipproxy Redis 获取最新代理列表。"""
        if not self._redis_client:
            return
        try:
            key = f"haipproxy:valid:{self._redis_site}"
            members = self._redis_client.smembers(key)
            proxies = []
            for m in members:
                try:
                    decoded = m.decode() if isinstance(m, bytes) else str(m)
                    if decoded.startswith("http"):
                        proxies.append(decoded)
                except Exception:
                    pass
            if proxies:
                self._redis_proxies = proxies
                self._last_redis_fetch = time.time()
                print(f"[*] 从 haipproxy 获取 {len(proxies)} 个代理")
        except Exception as e:
            print(f"[!] 从 haipproxy 获取代理失败: {e}")

    def close(self) -> None:
        """关闭 Redis 连接。"""
        if self._redis_client:
            try:
                self._redis_client.close()
            except Exception:
                pass


# ─── 全局单例 ──────────────────────────────────────────────────

_pool: Optional[ProxyPool] = None


def get_pool() -> ProxyPool:
    """获取全局代理池单例。"""
    global _pool
    if _pool is None:
        _pool = ProxyPool()
    return _pool
