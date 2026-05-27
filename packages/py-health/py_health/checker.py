"""OBS-04 健康检查 — 核心探测逻辑。

提供两个公共 async 函数：
    - check_all() → HealthCheckResponse: 并发检查全部三个组件的连通性
    - check_ready() → ReadinessResponse: 仅检查 PostgreSQL（启动就绪探针）

三个组件的检查均使用独立连接（不共享业务连接池），
各自有独立的超时控制，通过 asyncio.gather(return_exceptions=True)
确保一个组件的失败不终止其他组件的检查。

异常策略：所有组件级异常在最外层 try/except Exception 中捕获，
转换为 ComponentHealth.error 字段，永不向上传播到路由层。
"""

from __future__ import annotations

import asyncio
import time as time_module
from datetime import datetime, timezone

from py_config import get_settings
from py_logger import logger

from py_health.models import (
    ComponentHealth,
    ComponentStatus,
    Components,
    HealthCheckResponse,
    HealthStatus,
    ReadinessResponse,
)
from py_health.state import (
    get_consecutive_failures,
    get_last_status,
    increment_failures,
    reset_failures,
    set_last_status,
)

# ============================================================================
# 常量
# ============================================================================

PG_TIMEOUT: float = 3.0
"""PostgreSQL 连通性检查超时（秒）。"""

REDIS_TIMEOUT: float = 3.0
"""Redis 连通性检查超时（秒）。"""

MINIO_TIMEOUT: float = 5.0
"""MinIO 连通性检查超时（秒）。"""

ERROR_MSG_MAX_LEN: int = 256
"""错误信息最大字符数，超过部分截断。"""

BUCKET_NAME: str = "campfire"
"""MinIO 目标 bucket 名称。"""

API_VERSION: str = "0.1.0"
"""API 服务版本号，与根 pyproject.toml 保持一致。"""

# ============================================================================
# 进程启动时间（模块级常量，仅计算一次）
# ============================================================================

_process_start_time: float = time_module.time()
"""API 进程启动的 Unix 时间戳，用于计算 uptime_seconds。"""


# ============================================================================
# 内部工具函数
# ============================================================================

def _now_iso() -> str:
    """生成当前 UTC 时间的 ISO 8601 字符串，精确到秒。

    Returns:
        str: 格式为 "2026-05-26T23:07:02+00:00" 的时间戳。
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _truncate_error(raw: str) -> str:
    """截断错误信息至最大允许长度。

    Args:
        raw: 原始错误字符串。

    Returns:
        str: 截断后的字符串（超出部分以"..."替换末尾 3 字符）。
    """
    if len(raw) <= ERROR_MSG_MAX_LEN:
        return raw
    return raw[: ERROR_MSG_MAX_LEN - 3] + "..."


def _uptime_seconds() -> int:
    """计算自进程启动以来的运行时长（秒）。

    Returns:
        int: 向上取整的秒数。
    """
    return int(time_module.time() - _process_start_time)


# ============================================================================
# 组件连通性检查函数（内部，永不抛异常）
# ============================================================================


async def _check_postgresql() -> ComponentHealth:
    """检查 PostgreSQL 数据库连通性。

    使用独立的 SQLAlchemy AsyncEngine
    （pool_size=1, max_overflow=0，不共享业务连接池），
    执行 SELECT 1 验证 TCP 连接 + 认证 + 查询三层。

    连接参数从 py_config.config.settings.DATABASE_URL 获取。

    Returns:
        ComponentHealth: 包含连通状态和失败原因（如有）。
    """
    engine = None
    conn = None
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        db_url = str(settings.DATABASE_URL)

        engine = create_async_engine(
            db_url,
            pool_size=1,
            max_overflow=0,
        )

        async def _do_check() -> None:
            nonlocal conn
            conn = await engine.connect()
            result = await conn.execute(text("SELECT 1"))
            await result.fetchone()

        await asyncio.wait_for(_do_check(), timeout=PG_TIMEOUT)

        return ComponentHealth(status=ComponentStatus.connected)

    except asyncio.TimeoutError:
        return ComponentHealth(
            status=ComponentStatus.disconnected,
            error=f"timeout: exceeded {PG_TIMEOUT}s",
        )
    except Exception as exc:
        return ComponentHealth(
            status=ComponentStatus.disconnected,
            error=_truncate_error(f"{type(exc).__name__}: {exc}"),
        )
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
        if engine is not None:
            try:
                await engine.dispose()
            except Exception:
                pass


async def _check_redis() -> ComponentHealth:
    """检查 Redis 缓存服务连通性。

    使用独立的 redis.asyncio.Redis 短连接（用完即关），
    执行 PING 命令验证 TCP 连接 + 协议级保活。

    连接参数从 py_config.config.settings.REDIS_URL 获取。

    Returns:
        ComponentHealth: 包含连通状态和失败原因（如有）。
    """
    client = None
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        redis_url = str(settings.REDIS_URL)

        client = aioredis.Redis.from_url(
            redis_url,
            socket_connect_timeout=REDIS_TIMEOUT,
        )

        async def _do_ping() -> bool:
            return await client.ping()

        await asyncio.wait_for(_do_ping(), timeout=REDIS_TIMEOUT)

        return ComponentHealth(status=ComponentStatus.connected)

    except asyncio.TimeoutError:
        return ComponentHealth(
            status=ComponentStatus.disconnected,
            error=f"timeout: exceeded {REDIS_TIMEOUT}s",
        )
    except Exception as exc:
        return ComponentHealth(
            status=ComponentStatus.disconnected,
            error=_truncate_error(f"{type(exc).__name__}: {exc}"),
        )
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


async def _check_minio() -> ComponentHealth:
    """检查 MinIO 对象存储服务连通性。

    使用独立的 Minio 客户端短连接，调用 bucket_exists("campfire")
    验证 TCP 连接 + 认证 + 基本 I/O。bucket_exists 为同步调用，
    在 asyncio.to_thread() 中执行以避免阻塞事件循环。

    连接参数从 py_config.config.settings 的
    MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY 获取。

    Returns:
        ComponentHealth: 包含连通状态和失败原因（如有）。
            bucket 不存在时标记为 connected 但 error 记录提醒信息。
    """
    try:
        from minio import Minio

        settings = get_settings()
        endpoint = settings.MINIO_ENDPOINT
        access_key = settings.MINIO_ACCESS_KEY.get_secret_value()
        secret_key = settings.MINIO_SECRET_KEY.get_secret_value()

        client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=False,
        )

        async def _do_bucket_check() -> bool:
            return await asyncio.to_thread(
                client.bucket_exists, BUCKET_NAME
            )

        bucket_found = await asyncio.wait_for(
            _do_bucket_check(), timeout=MINIO_TIMEOUT
        )

        if bucket_found:
            return ComponentHealth(status=ComponentStatus.connected)
        else:
            return ComponentHealth(
                status=ComponentStatus.connected,
                error=f"bucket_not_found: {BUCKET_NAME}",
            )

    except asyncio.TimeoutError:
        return ComponentHealth(
            status=ComponentStatus.disconnected,
            error=f"timeout: exceeded {MINIO_TIMEOUT}s",
        )
    except Exception as exc:
        return ComponentHealth(
            status=ComponentStatus.disconnected,
            error=_truncate_error(f"{type(exc).__name__}: {exc}"),
        )


# ============================================================================
# 公共接口
# ============================================================================


async def check_all() -> HealthCheckResponse:
    """执行系统整体健康检查，并发探测全部三个基础服务的连通性。

    每次请求实时执行全部三个组件的连通性验证，不依赖缓存或上次结果。
    所有组件级异常内部捕获，永不向上传播。

    Side Effects:
        - 创建并释放三个独立连接（PG AsyncEngine、Redis 短连接、MinIO 客户端）
        - 状态变更时通过 py_logger 写入结构化日志
        - 更新模块级内存变量 _last_overall_status 和 _consecutive_failures

    Returns:
        HealthCheckResponse: 完整的健康检查响应（含整体状态、组件详情、时间戳）。
    """
    # 步骤 1：并发执行三个组件的连通性检查
    results: list[ComponentHealth | BaseException] = (
        await asyncio.gather(
            _check_postgresql(),
            _check_redis(),
            _check_minio(),
            return_exceptions=True,
        )
    )

    # 步骤 2：提取各组件健康状态
    pg_health = _unwrap_result(results[0], "postgresql")
    redis_health = _unwrap_result(results[1], "redis")
    minio_health = _unwrap_result(results[2], "minio")

    # 步骤 3：判定整体健康状态
    disconnected_count = sum(
        1
        for h in (pg_health, redis_health, minio_health)
        if h.status == ComponentStatus.disconnected
    )

    if disconnected_count == 0:
        overall = HealthStatus.healthy
    elif disconnected_count == 3:
        overall = HealthStatus.unhealthy
    else:
        overall = HealthStatus.degraded

    # 步骤 4：更新连续失败计数
    any_failure = disconnected_count > 0
    if any_failure:
        # MinIO bucket_not_found 不应计入失败（连通性正常）
        actual_failures = _count_actual_failures(
            pg_health, redis_health, minio_health
        )
        if actual_failures > 0:
            increment_failures()
    else:
        reset_failures()

    # 步骤 5：状态变更防抖 — 仅状态变化时写日志
    previous_status = get_last_status()
    if previous_status != overall:
        _log_status_change(previous_status, overall, pg_health, redis_health, minio_health)
        set_last_status(overall)

    # 步骤 6：构建响应
    return HealthCheckResponse(
        status=overall,
        version=API_VERSION,
        uptime_seconds=_uptime_seconds(),
        components=Components(
            postgresql=pg_health,
            redis=redis_health,
            minio=minio_health,
        ),
        timestamp=_now_iso(),
    )


async def check_ready() -> ReadinessResponse:
    """执行启动就绪检查，仅验证 PostgreSQL 组件的连通性。

    用于容器启动阶段的就绪判定。在数据库迁移期间，
    Redis 和 MinIO 可能尚未就绪——此函数提供精确的就绪信号，
    避免容器在启动期间被错误标记为 unhealthy。

    Side Effects:
        - 创建并释放 PostgreSQL 独立连接
        - 状态变更时通过 py_logger 写入结构化日志

    Returns:
        ReadinessResponse: 就绪检查响应（仅含 PostgreSQL 状态）。
    """
    pg_health = await _check_postgresql()
    ready = pg_health.status == ComponentStatus.connected

    return ReadinessResponse(
        ready=ready,
        database=pg_health,
        timestamp=_now_iso(),
    )


# ============================================================================
# 内部辅助函数
# ============================================================================


def _unwrap_result(
    result: ComponentHealth | BaseException,
    component_name: str,
) -> ComponentHealth:
    """从 asyncio.gather 结果中安全提取 ComponentHealth。

    若结果为 BaseException（在 return_exceptions=True 时可能发生），
    降级为 disconnected 状态——尽管所有检查函数都应内部捕获异常，
    此函数提供额外的安全网。

    Args:
        result: asyncio.gather 返回的单个结果。
        component_name: 组件名称（仅用于兜底错误信息）。

    Returns:
        ComponentHealth: 提取或降级后的组件健康状态。
    """
    if isinstance(result, ComponentHealth):
        return result
    # 安全网：不应该到达这里，但万一检查函数有漏网的异常
    return ComponentHealth(
        status=ComponentStatus.disconnected,
        error=f"internal_error: {component_name} check raised unhandled exception",
    )


def _count_actual_failures(
    pg: ComponentHealth,
    redis: ComponentHealth,
    minio: ComponentHealth,
) -> int:
    """统计实际连通性失败数（排除 bucket_not_found）。"""
    count = 0
    for h in (pg, redis, minio):
        if h.status == ComponentStatus.disconnected:
            count += 1
        elif h.error and h.error.startswith("bucket_not_found"):
            pass  # bucket_not_found 不计入失败
        else:
            pass
    return count


def _log_status_change(
    previous: HealthStatus | None,
    current: HealthStatus,
    pg: ComponentHealth,
    redis: ComponentHealth,
    minio: ComponentHealth,
) -> None:
    """记录健康状态变更的结构化日志。

    退化（healthy/unhealthy → degraded/unhealthy）写 WARNING，
    恢复写 INFO。首次检查（previous 为 None）写 INFO。

    Args:
        previous: 变更前的状态（None 表示首次检查）。
        current: 变更后的状态。
        pg: PostgreSQL 组件健康详情。
        redis: Redis 组件健康详情。
        minio: MinIO 组件健康详情。
    """
    is_worse = _is_status_degraded(previous, current)
    message = _build_status_change_message(previous, current)

    extra: dict[str, object] = {
        "previous_status": previous.value if previous else "none",
        "current_status": current.value,
        "components": {
            "postgresql": pg.model_dump(),
            "redis": redis.model_dump(),
            "minio": minio.model_dump(),
        },
    }

    if is_worse:
        logger.warning("api-server", message, extra=extra)
    else:
        logger.info("api-server", message, extra=extra)


def _is_status_degraded(
    previous: HealthStatus | None,
    current: HealthStatus,
) -> bool:
    """判定状态变化是否为退化方向。

    退化：healthy → degraded/unhealthy，degraded → unhealthy。
    恢复：unhealthy → degraded/healthy，degraded → healthy。
    首次检查（previous=None）返回 False。

    Args:
        previous: 变更前状态。
        current: 变更后状态。

    Returns:
        bool: True 表示退化，False 表示恢复或首次检查。
    """
    if previous is None:
        return False
    order = {"healthy": 0, "degraded": 1, "unhealthy": 2}
    return order.get(current.value, 0) > order.get(previous.value, 0)


def _build_status_change_message(
    previous: HealthStatus | None,
    current: HealthStatus,
) -> str:
    """构建状态变更日志消息。

    Args:
        previous: 变更前状态。
        current: 变更后状态。

    Returns:
        str: 人类可读的状态变更描述。
    """
    if previous is None:
        return f"Initial health check completed: status={current.value}"
    return (
        f"Health status changed: {previous.value} -> {current.value}"
    )
