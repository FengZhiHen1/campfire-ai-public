"""SEC-04 防刷限流中间件。

使用 Redis ZSET + LUA 原子滑动窗口实现用户级和 IP 级双重限流。
Redis 故障时 fail-open（放行所有请求 + CRITICAL 日志告警）。

The middleware MUST be registered via app.add_middleware(RateLimitMiddleware).
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

import redis.exceptions
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge
from starlette.middleware.base import BaseHTTPMiddleware

from py_cache import get_redis_client, maybe_await
from py_config.security import get_security_config
from py_logger import logger

# ============================================================================
# LUA 脚本 — Redis ZSET 原子滑动窗口限流
# ============================================================================

RATE_LIMIT_LUA_SCRIPT = """
redis.replicate_commands()
local zset_key = KEYS[1]
local window_seconds = tonumber(ARGV[1])
local now_timestamp = tonumber(ARGV[2])

-- Generate unique member to avoid collision within the same second
local counter = redis.call("INCR", "ratelimit:counter")
local member = now_timestamp .. ":" .. counter

-- Add current request timestamp as score
redis.call("ZADD", zset_key, now_timestamp, member)

-- Remove expired members (scores outside the sliding window)
local cutoff = now_timestamp - window_seconds
if cutoff > 0 then
    redis.call("ZREMRANGEBYSCORE", zset_key, 0, cutoff)
end

-- Count members currently in the window
local count = redis.call("ZCARD", zset_key)

-- Set TTL with buffer (window + 10 seconds)
redis.call("EXPIRE", zset_key, window_seconds + 10)

-- Return {count_before, ttl_remaining}
-- count_before = count - 1 (exclude the one we just inserted)
return {count - 1, window_seconds}
"""

# ============================================================================
# 白名单路径
# ============================================================================

RATE_LIMIT_WHITELIST_PATHS: set[str] = {"/health", "/metrics"}

# ============================================================================
# Prometheus 指标（模块级注册，不在 dispatch 热路径上注册）
# ============================================================================

RATE_LIMIT_CHECK_TOTAL = Counter(
    "rate_limit_check_total",
    "Total number of rate limit checks performed",
    ["status", "level"],
)

RATE_LIMIT_REDIS_HEALTH = Gauge(
    "rate_limit_redis_health",
    "Redis health status for rate limiting (1=healthy, 0=unhealthy)",
)
# Initialize as healthy
RATE_LIMIT_REDIS_HEALTH.set(1)


# ============================================================================
# 内部辅助函数
# ============================================================================


def _is_internal_ip(ip: str) -> bool:
    """判断 IP 是否为内网地址。

    检查以下内网段：
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16

    Args:
        ip: IPv4 地址字符串。

    Returns:
        True 表示内网地址，False 表示公网地址。
    """
    if ip.startswith("10."):
        return True
    if ip.startswith("192.168."):
        return True
    if ip.startswith("172."):
        parts = ip.split(".")
        if len(parts) >= 2:
            try:
                second_octet = int(parts[1])
                return 16 <= second_octet <= 31
            except (ValueError, IndexError):
                return False
    return False


def _resolve_client_ip(request: Request) -> str:
    """从 HTTP 请求中解析客户端真实 IP 地址。

    优先级：
    1. X-Forwarded-For 头中第一个非内网 IP
    2. request.client.host（含 X-Forwarded-For 全部为内网 IP 时的回退）
    3. "0.0.0.0"（兜底默认值）

    Args:
        request: FastAPI Request 对象。

    Returns:
        解析后的客户端 IP 地址字符串。
    """
    # 步骤 1：解析 X-Forwarded-For
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        for raw_ip in forwarded.split(","):
            ip = raw_ip.strip()
            if ip and not _is_internal_ip(ip):
                return ip
        # X-Forwarded-For 存在但全部为内网 IP，按契约回退到 request.client.host

    # 步骤 2：回退到 request.client.host
    if request.client is not None and request.client.host:
        return request.client.host

    # 步骤 3：兜底默认值（测试环境等无法获取客户端连接信息的场景）
    return "0.0.0.0"


def _handle_redis_degraded(
    ip: str,
    exc: Exception | None = None,
) -> None:
    """处理 Redis 故障降级：更新 Prometheus 指标并记录 CRITICAL 日志。

    Args:
        ip: 客户端 IP。
        exc: Redis 异常对象（若可用），用于记录 error_type/error_msg。
    """
    extra: dict[str, object] = {"ip": ip}
    if exc is not None:
        extra["error_type"] = type(exc).__name__
        extra["error_msg"] = str(exc)

    RATE_LIMIT_REDIS_HEALTH.set(0)
    RATE_LIMIT_CHECK_TOTAL.labels(status="degraded", level="none").inc()
    logger.critical(
        service="api-server",
        message="rate_limit_degraded",
        op_type="rate_limit_degraded",
        extra=extra,
    )


# ============================================================================
# 限流中间件
# ============================================================================


class RateLimitMiddleware(BaseHTTPMiddleware):
    """防刷限流全局中间件，在所有路由处理之前、身份认证之前执行。

    通过 Redis ZSET + LUA 原子滑动窗口实现用户级（30/min）和 IP 级（100/min）
    双重限流。采用短路优化：已登录用户先检查用户级，超限则直接拒绝不检查 IP 级。
    Redis 不可用时自动 fail-open 放行所有请求。

    The middleware MUST be registered via ``app.add_middleware(RateLimitMiddleware)``.
    """

    def __init__(self, app) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """限流检查主入口。

        Args:
            request: FastAPI 传入的请求实例。
            call_next: 下一个中间件或路由处理的调用函数。

        Returns:
            Response: 正常通过时返回下游处理的响应；超限时返回 429 JSONResponse。

        Side Effects:
            - 写入 Redis ZSET（限流计数器 member）
            - 记录 WARNING/CRITICAL 级别结构化日志
            - 递增 Prometheus Counter ``rate_limit_check_total``
        """
        # ---- 步骤 1：IP 来源解析 ----
        ip = _resolve_client_ip(request)

        # ---- 步骤 2：白名单匹配 ----
        if request.url.path in RATE_LIMIT_WHITELIST_PATHS:
            return await call_next(request)

        now_ts = int(time.time())
        window = get_security_config().RATE_LIMIT_WINDOW_SECONDS

        # 安全获取 user_id（未登录场景下 request.state 无 user 属性；
        # 最外层 getattr 防御 request 对象自身可能无 state 属性的极端场景）
        user_id: str | None = getattr(
            getattr(getattr(request, "state", None), "user", None), "id", None
        )

        # ---- 获取 Redis 客户端 ----
        try:
            redis_client = await get_redis_client()
        except Exception as exc:
            _handle_redis_degraded(ip, exc)
            return await call_next(request)

        if redis_client is None:
            _handle_redis_degraded(ip)
            return await call_next(request)

        # ---- 步骤 3：用户级限流（短路优化） ----
        if user_id is not None:
            user_key = f"ratelimit:user:{user_id}"
            try:
                result = await maybe_await(
                    redis_client.eval(
                        RATE_LIMIT_LUA_SCRIPT,
                        1,
                        user_key,
                        window,
                        now_ts,
                    )
                )
            except redis.exceptions.RedisError as exc:
                _handle_redis_degraded(ip, exc)
                return await call_next(request)

            user_count = int(result[0])
            if user_count >= get_security_config().RATE_LIMIT_USER_PER_MINUTE:
                return await self._build_429(
                    redis_client,
                    ip,
                    user_id,
                    "user",
                    user_count,
                    get_security_config().RATE_LIMIT_USER_PER_MINUTE,
                )

        # ---- 步骤 4：IP 级限流 ----
        ip_key = f"ratelimit:ip:{ip}"
        try:
            result = await maybe_await(
                redis_client.eval(
                    RATE_LIMIT_LUA_SCRIPT,
                    1,
                    ip_key,
                    window,
                    now_ts,
                )
            )
        except redis.exceptions.RedisError as exc:
            _handle_redis_degraded(ip, exc)
            return await call_next(request)

        ip_count = int(result[0])
        if ip_count >= get_security_config().RATE_LIMIT_IP_PER_MINUTE:
            return await self._build_429(
                redis_client,
                ip,
                user_id,
                "ip",
                ip_count,
                get_security_config().RATE_LIMIT_IP_PER_MINUTE,
            )

        # ---- 步骤 5：正常通过 ----
        # Redis 健康状态恢复
        RATE_LIMIT_REDIS_HEALTH.set(1)

        # 递增通过指标
        level = "user" if user_id is not None else "ip"
        RATE_LIMIT_CHECK_TOTAL.labels(status="passed", level=level).inc()

        return await call_next(request)

    async def _build_429(
        self,
        redis_client,
        ip: str,
        user_id: str | None,
        level: str,
        count: int,
        limit: int,
    ) -> JSONResponse:
        """构造限流拒绝响应（HTTP 429）并记录相关日志与指标。

        Args:
            redis_client: Redis 异步客户端，用于异常行为标记。
            ip: 客户端 IP。
            user_id: 用户 ID（可为 None）。
            level: 触发限流的级别（"user" 或 "ip"）。
            count: 当前窗口内请求计数。
            limit: 限流阈值。

        Returns:
            JSONResponse: HTTP 429，响应体遵循 RateLimitExceededResponse 契约。
        """
        window = get_security_config().RATE_LIMIT_WINDOW_SECONDS

        # 记录 WARNING 结构化日志
        extra: dict[str, object] = {
            "level": level,
            "ip": ip,
            "count": count,
            "limit": limit,
            "window_seconds": window,
        }
        if user_id is not None:
            extra["user_id"] = user_id
        logger.warning(
            service="api-server",
            message="rate_limit_exceeded",
            extra=extra,
        )

        # 递增拒绝指标
        RATE_LIMIT_CHECK_TOTAL.labels(status="rejected", level=level).inc()

        # 异常行为标记（仅对已登录用户，尽力而为）
        if user_id is not None:
            await self._mark_anomaly(redis_client, user_id, ip)

        # 构造 429 响应（严格遵循 RateLimitExceededResponse 契约）
        return JSONResponse(
            status_code=429,
            content={
                "detail": "请求过于频繁，请稍后重试",
                "retry_after_seconds": window,
            },
            headers={"Retry-After": str(window)},
        )

    async def _mark_anomaly(
        self,
        redis_client,
        user_id: str,
        ip: str,
    ) -> None:
        """标记潜在异常行为（尽力而为，失败不影响主流程）。

        在同一 user_id 于 5 分钟窗口内累计触发限流 >= 3 次时，
        记录 "potential_abnormal_behavior" 日志，供后续安全分析使用。

        Args:
            redis_client: Redis 异步客户端。
            user_id: 用户 ID。
            ip: 客户端 IP。
        """
        try:
            five_min_block = int(time.time() / 300)
            anomaly_key = f"ratelimit:anomaly:{user_id}:{five_min_block}"
            hit_count = await redis_client.incr(anomaly_key)
            if hit_count == 1:
                await redis_client.expire(anomaly_key, 310)
            if hit_count >= 3:
                logger.warning(
                    service="api-server",
                    message="potential_abnormal_behavior",
                    extra={
                        "user_id": user_id,
                        "ip": ip,
                        "anomaly_type": "frequent_rate_limit_hits",
                        "hit_count": hit_count,
                        "window_minutes": 5,
                    },
                )
        except Exception:
            # 异常行为标记是尽力而为的辅助分析，失败不影响限流拒绝流程
            pass
