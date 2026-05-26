"""Token 失效管理 — Redis 操作模块。

两层防护：
1. 角色变更撤销：add_to_blacklist / is_blacklisted，Key 模式 token_blacklist:{jti}，TTL=900s
2. Refresh Token 单次使用：mark_refresh_used / is_refresh_used，Key 模式 refresh_used:{jti}，TTL=7d

降级策略（fail-open）：
Redis 不可用时放行，仅记录 warning 日志。
"""

from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from py_config import get_settings
from py_logger import logger

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_TOKEN_BLACKLIST_PREFIX: str = "token_blacklist:"
"""Redis Key 前缀，统一使用 token_blacklist: 格式。"""

_BLACKLIST_TTL: int = 900
"""黑名单 Key 过期时间（秒），与 Access Token 有效期一致。"""

# ---------------------------------------------------------------------------
# 模块级 Redis 客户端（惰性初始化）
# ---------------------------------------------------------------------------

_redis_client: aioredis.Redis | None = None
_redis_lock: asyncio.Lock = asyncio.Lock()


async def _get_redis() -> aioredis.Redis:
    """获取或创建 Redis 异步客户端（惰性初始化，异步线程安全）。

    首次调用时从 py-config 读取 REDIS_URL 创建连接。
    后续调用复用同一连接实例。

    Returns:
        Redis 异步客户端实例。

    Raises:
        连接失败时向上传播异常，由调用方按 fail-open 策略处理。
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    async with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        settings = get_settings()
        _redis_client = aioredis.from_url(str(settings.REDIS_URL))
        return _redis_client


# ===========================================================================
# 公开接口
# ===========================================================================


async def add_to_blacklist(jti: str) -> None:
    """将被撤销 Token 的 jti 加入 Redis 黑名单，TTL 为 900 秒。

    在角色变更时调用，使旧 Token 立即失效，用户需重新登录以获取
    携带新角色信息的 Token。

    Key 格式：token_blacklist:{jti}
    Value：被撤销 Token 的 jti（字符串）
    TTL：900 秒（与 Access Token 有效期一致）

    Args:
        jti: JWT Token 的唯一标识符（jti claim），UUID v4 格式。

    Returns:
        None —— 无返回值。正常写入静默完成。

    Side Effects:
        - 向 Redis 执行 SETEX 写入（KV 操作）
        - Redis 不可用时记录 warning 日志并跳过写入（fail-open）
    """
    try:
        client = await _get_redis()
        key = f"{_TOKEN_BLACKLIST_PREFIX}{jti}"
        await client.setex(key, _BLACKLIST_TTL, jti)
    except (RedisError, ConnectionError, OSError) as exc:
        logger.warning(
            "py-auth",
            "Redis 不可用，黑名单写入跳过（fail-open）",
            op_type="权限拒绝",
            extra={
                "jti": jti,
                "ttl": _BLACKLIST_TTL,
                "error": str(exc),
                "strategy": "fail_open",
            },
        )


async def is_blacklisted(jti: str) -> bool:
    """查询指定 jti 是否在 Redis 黑名单中。

    由 AUTH-02 的 get_current_user Depends 在校验 JWT 后调用。
    若 jti 命中黑名单 → 返回 True（应拒绝请求，返回 401）。
    若 jti 未命中黑名单 → 返回 False（正常放行）。

    Redis 不可用时执行 fail-open 降级：返回 False（放行），
    旧角色 Token 继续有效直到自然过期（最多 15 分钟）。

    Args:
        jti: JWT Token 的唯一标识符（jti claim）。

    Returns:
        bool: True 表示 jti 在黑名单中（应拒绝），
              False 表示未命中或 Redis 不可用（均应放行）。

    Side Effects:
        - 向 Redis 执行 GET 查询（只读操作）
        - Redis 不可用时记录 warning 日志
    """
    try:
        client = await _get_redis()
        key = f"{_TOKEN_BLACKLIST_PREFIX}{jti}"
        result = await client.get(key)
        return result is not None
    except (RedisError, ConnectionError, OSError) as exc:
        logger.warning(
            "py-auth",
            "Redis 连接失败，黑名单查询降级（fail-open）",
            op_type="权限拒绝",
            extra={
                "jti": jti,
                "key": f"{_TOKEN_BLACKLIST_PREFIX}{jti}",
                "strategy": "fail_open",
                "error": str(exc),
            },
        )
        return False


async def mark_refresh_used(jti: str) -> None:
    """将续期令牌标记为已使用（防止重放攻击）。

    Key 格式：refresh_used:{jti}
    TTL：7 天（与 Refresh Token 有效期一致）

    Args:
        jti: 续期令牌的 jti claim。
    """
    try:
        client = await _get_redis()
        key = f"refresh_used:{jti}"
        await client.setex(key, _REFRESH_USED_TTL, "1")
    except (RedisError, ConnectionError, OSError) as exc:
        logger.warning(
            "py-auth",
            "Refresh 标记写入失败（fail-open）",
            op_type="认证",
            extra={"jti": jti, "strategy": "fail_open", "error": str(exc)},
        )


async def is_refresh_used(jti: str) -> bool:
    """查询续期令牌是否已被使用过。

    Redis 不可用时返回 False（fail-open 放行）。
    """
    try:
        client = await _get_redis()
        key = f"refresh_used:{jti}"
        return await client.exists(key) > 0
    except (RedisError, ConnectionError, OSError) as exc:
        logger.warning(
            "py-auth",
            "Refresh 查询失败（fail-open）",
            op_type="认证",
            extra={"jti": jti, "strategy": "fail_open", "error": str(exc)},
        )
        return False


_REFRESH_USED_TTL: int = 7 * 24 * 3600  # 7 天


__all__ = [
    "add_to_blacklist",
    "is_blacklisted",
    "mark_refresh_used",
    "is_refresh_used",
]
