"""AUTH-04 Token 黑名单 — Redis 操作模块。

提供角色变更后 Token 实时失效所需的 Redis 黑名单操作：
- add_to_blacklist(jti): 将 jti 写入 Redis 黑名单，TTL=900s
- is_blacklisted(jti) -> bool: 查询 jti 是否在黑名单中

Key 模式：token_blacklist:{jti}
TTL：900 秒（15 分钟，与 Access Token 有效期一致）

降级策略（fail-open）：
Redis 不可用时 is_blacklisted 返回 False（放行），旧角色 Token 继续有效
直到自然过期（最多 15 分钟）。add_to_blacklist 在 Redis 不可用时不写入，
仅记录 warning 日志。

契约引用：
- TokenBlacklistKey: docs/contracts/AUTH-04/TokenBlacklistKey.json
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


__all__ = [
    "add_to_blacklist",
    "is_blacklisted",
]
