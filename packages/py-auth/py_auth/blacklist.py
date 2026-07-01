"""py-auth Token 失效管理 — RedisBlacklist 实现。

实现 TokenBlacklist 契约，使用 Redis 异步客户端管理 Token 黑名单。
两层防护：角色变更撤销 + Refresh Token 单次使用检测。

核心类:
  - RedisBlacklist: 实现 TokenBlacklist 契约，Redis 持久化

降级策略 (fail-open): Redis 不可用时放行，仅记录 warning 日志。

Usage:
    from py_auth.blacklist import RedisBlacklist
    bl = RedisBlacklist()
    await bl.add_to_blacklist("some-jti-uuid")
    if await bl.is_blacklisted("some-jti-uuid"):
        raise HTTPException(401)
"""

from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
from py_config import get_settings

from py_auth.auth_contract import TokenBlacklist

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_TOKEN_BLACKLIST_PREFIX: str = "token_blacklist:"
"""Redis Key 前缀，格式 token_blacklist:{jti}。"""


class RedisBlacklist(TokenBlacklist):
    """Redis 持久化的 Token 黑名单，继承 TokenBlacklist 契约。

    惰性初始化 Redis 连接，异步线程安全。
    """

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def _get_client(self) -> aioredis.Redis:
        """获取或创建 Redis 异步客户端（惰性初始化，线程安全）。"""
        if self._client is not None:
            return self._client

        async with self._lock:
            if self._client is not None:
                return self._client
            settings = get_settings()
            self._client = aioredis.from_url(str(settings.REDIS_URL))
            return self._client

    # ------------------------------------------------------------------
    # 契约钩子
    # ------------------------------------------------------------------

    async def _do_add_blacklist(self, jti: str) -> None:
        """将 jti 写入 Redis 黑名单，TTL=900s。

        Key: token_blacklist:{jti}
        """
        client = await self._get_client()
        key = f"{_TOKEN_BLACKLIST_PREFIX}{jti}"
        await client.setex(key, self._BLACKLIST_TTL, jti)

    async def _do_check_blacklist(self, jti: str) -> bool:
        """查询 Redis 黑名单中是否存在指定 jti。"""
        client = await self._get_client()
        key = f"{_TOKEN_BLACKLIST_PREFIX}{jti}"
        result = await client.get(key)
        return result is not None

    async def _do_mark_refresh(self, jti: str) -> None:
        """标记 Refresh Token 已使用，TTL=7d。

        Key: refresh_used:{jti}
        """
        client = await self._get_client()
        key = f"refresh_used:{jti}"
        await client.setex(key, self._REFRESH_USED_TTL, "1")

    async def _do_check_refresh(self, jti: str) -> bool:
        """查询 Refresh Token 是否已被使用。"""
        client = await self._get_client()
        key = f"refresh_used:{jti}"
        result: bool = await client.exists(key) > 0
        return result

    # ------------------------------------------------------------------
    # 连接生命周期管理
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """关闭 Redis 连接，释放资源。

        幂等——重复调用安全。关闭后再次调用 _get_client 会重新创建连接。
        """
        if self._client is not None:
            client = self._client
            self._client = None
            await client.aclose()

    async def __aenter__(self) -> "RedisBlacklist":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()


# ============================================================================
# 惰性初始化（避免 import 时触发 Redis 连接池创建）
# ============================================================================

_blacklist_instance: RedisBlacklist | None = None


def _get_blacklist() -> RedisBlacklist:
    """获取 RedisBlacklist 单例（惰性初始化）。"""
    global _blacklist_instance
    if _blacklist_instance is None:
        _blacklist_instance = RedisBlacklist()
    return _blacklist_instance


# ============================================================================
# 便捷函数（兼容旧 API）
# ============================================================================


async def add_to_blacklist(jti: str) -> None:
    """便捷函数——将 Token jti 加入黑名单。"""
    await _get_blacklist().add_to_blacklist(jti)


async def is_blacklisted(jti: str) -> bool:
    """便捷函数——查询 jti 是否在黑名单中。"""
    return await _get_blacklist().is_blacklisted(jti)


async def mark_refresh_used(jti: str) -> None:
    """便捷函数——标记 Refresh Token 已使用。"""
    await _get_blacklist().mark_refresh_used(jti)


async def is_refresh_used(jti: str) -> bool:
    """便捷函数——查询 Refresh Token 是否已使用。"""
    return await _get_blacklist().is_refresh_used(jti)


__all__ = [
    "RedisBlacklist",
    "add_to_blacklist",
    "is_blacklisted",
    "mark_refresh_used",
    "is_refresh_used",
]
