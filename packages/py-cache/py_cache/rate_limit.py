"""SEC-01 Redis 滑动窗口限流。

使用 redis.asyncio.Redis 实现用户级和 IP 级双重滑动窗口限流。
Redis 故障时 fail-open（放行所有请求 + CRITICAL 日志告警）。

限流算法：
- 窗口内每秒一个 key，格式 ``ratelimit:{type}:{id}:{unix_second}``
- INCR 当前秒 key + EXPIRE 设置 TTL（窗口 + 60s 缓冲）
- MGET 窗口内所有 key 的值并求和，与阈值比较
- 用户级优先：超限立即返回 False，不再执行 IP 级检查

公开函数：
  - check_rate_limit: 异步限流检查（不幂等）
"""

from __future__ import annotations

import asyncio
import time

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from py_config import get_settings
from py_config.security import get_security_config
from py_logger import logger

# 模块级 Redis 客户端（惰性初始化）
_redis_client: aioredis.Redis | None = None
_redis_lock = asyncio.Lock()


async def _get_redis() -> aioredis.Redis:
    """获取或创建 Redis 异步客户端（惰性初始化，异步线程安全）。

    Returns:
        Redis 异步客户端实例。

    Raises:
        连接失败时向上传播异常，由调用方 fail-open 处理。
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    async with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        settings = get_settings()
        _redis_client = aioredis.from_url(
            str(settings.REDIS_URL),
        )
        return _redis_client


async def check_rate_limit(
    user_id: str | None = None,
    *,
    ip: str,
) -> bool:
    """Redis 滑动窗口限流检查，支持用户级和 IP 级双重限流。

    限流流程：
    1. 若 user_id 非空 → 执行用户级限流
    2. 始终执行 IP 级限流
    3. 任一级别超限 → 返回 False
    4. Redis 不可用时 → fail-open 返回 True，记录 CRITICAL 日志

    Args:
        user_id: 已登录用户的 ID；None 则仅执行 IP 级限流。
        ip: 客户端 IP 地址。

    Returns:
        bool: True=允许通过，False=触发限流。

    Raises:
        不抛异常。Redis 故障时 fail-open 返回 True。

    Side Effects:
        - 向 Redis 写入 INCR + EXPIRE（TTL = WINDOW_SECONDS + 60）
        - Redis 不可用时记录 CRITICAL 日志：
          ``logger.critical("py-cache", "rate_limit_redis_unavailable", op_type="rate_limit_degraded", ...)``
    """
    config = get_security_config()
    window = config.RATE_LIMIT_WINDOW_SECONDS
    current_ts = int(time.time())

    # 获取 Redis 连接（失败则 fail-open）
    try:
        redis_client = await _get_redis()
    except Exception as exc:
        logger.critical(
            "py-cache",
            "rate_limit_redis_unavailable",
            op_type="rate_limit_degraded",
            extra={
                "event": "rate_limit_redis_unavailable",
                "ip": ip,
                "user_id": user_id,
                "error": str(exc),
            },
        )
        return True

    try:
        # 步骤 1：用户级限流
        if user_id is not None:
            user_allowed = await _check_sliding_window(
                redis_client=redis_client,
                key_prefix=f"ratelimit:user:{user_id}",
                window_seconds=window,
                current_timestamp=current_ts,
                threshold=config.RATE_LIMIT_USER_PER_MINUTE,
                ttl=window + 60,
            )
            if not user_allowed:
                return False

        # 步骤 2：IP 级限流
        ip_allowed = await _check_sliding_window(
            redis_client=redis_client,
            key_prefix=f"ratelimit:ip:{ip}",
            window_seconds=window,
            current_timestamp=current_ts,
            threshold=config.RATE_LIMIT_IP_PER_MINUTE,
            ttl=window + 60,
        )
        return ip_allowed

    except RedisError as exc:
        logger.critical(
            "py-cache",
            "rate_limit_redis_unavailable",
            op_type="rate_limit_degraded",
            extra={
                "event": "rate_limit_redis_unavailable",
                "ip": ip,
                "user_id": user_id,
                "error": str(exc),
            },
        )
        return True


async def _check_sliding_window(
    redis_client: aioredis.Redis,
    key_prefix: str,
    window_seconds: int,
    current_timestamp: int,
    threshold: int,
    ttl: int,
) -> bool:
    """执行单一级别的滑动窗口限流检查。

    Args:
        redis_client: Redis 异步客户端。
        key_prefix: Redis key 前缀（如 ``ratelimit:user:uid-001``）。
        window_seconds: 滑动窗口大小（秒）。
        current_timestamp: 当前 Unix 时间戳（秒）。
        threshold: 窗口内最大允许请求数。
        ttl: key 的过期时间（秒）。

    Returns:
        bool: True=允许通过（未超限），False=超限。
    """
    # 生成窗口内所有 key
    window_keys = [
        f"{key_prefix}:{current_timestamp - offset}"
        for offset in range(window_seconds)
    ]
    current_key = window_keys[0]

    # Pipeline: INCR + EXPIRE + MGET（减少网络往返）
    pipe = redis_client.pipeline(transaction=False)
    pipe.incr(current_key)
    pipe.expire(current_key, ttl)
    pipe.mget(window_keys)
    results = await pipe.execute()

    # results[0]: INCR 返回值
    # results[1]: EXPIRE 返回值 (bool)
    # results[2]: MGET 返回的 list[int|None]
    counts: list = results[2]
    total = sum(int(c) for c in counts if c is not None)

    return total <= threshold


async def get_redis_client() -> aioredis.Redis:
    """获取 Redis 异步客户端实例（惰性初始化，异步线程安全）。

    基于 _get_redis() 的内部逻辑，提供公开访问入口。
    返回的客户端实例具备 eval() 方法，可用于执行 LUA 原子脚本。

    Returns:
        Redis 异步客户端实例。

    Raises:
        ConnectionError: 仅在显式 PING 验证时抛出；惰性初始化不主动连接。
    """
    return await _get_redis()


async def close_redis_client() -> None:
    """关闭 Redis 客户端连接池。

    应在进程优雅关闭时调用。关闭后再次调用 get_redis_client()
    会重新创建客户端。
    """
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


__all__ = [
    "check_rate_limit",
    "close_redis_client",
    "get_redis_client",
]
