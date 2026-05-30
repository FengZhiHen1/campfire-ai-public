"""OBS-04 健康检查 — FastAPI 路由注册。

提供两个公开端点（无需 JWT 认证）：
    - GET /health（别名 /api/v1/health）：系统整体健康检查
    - GET /ready（别名 /api/v1/ready）：启动就绪探针（仅检查 PostgreSQL）

路由层极度精简 ——
探测逻辑完全委托给 ``py_health.checker``，本层仅负责：
    1. 调用 shared checker 获取结果
    2. 根据结果和连续失败计数判定 HTTP 状态码
    3. 构造 JSONResponse 返回

非 GET 请求由 FastAPI 自动返回 405 Method Not Allowed。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from py_health.checker import check_all, check_ready
from py_health.models import HealthStatus
from py_health.state import get_consecutive_failures
from py_logger import logger

router = APIRouter(tags=["health"])


async def _get_health(request: Request) -> JSONResponse:
    """GET /health — 系统整体健康检查端点。

    每次请求实时执行全部三个组件的连通性验证，不依赖缓存。

    Args:
        request: FastAPI Request 对象（用于提取 User-Agent 等调用方信息）。

    Returns:
        JSONResponse: 响应体符合 HealthCheckResponse 契约。
            200 OK：status="healthy" 且 consecutive_failures < 3
            503 Service Unavailable：status="degraded"/"unhealthy"
                或 consecutive_failures >= 3
    """
    response = await check_all()
    consecutive = get_consecutive_failures()
    if response.status == HealthStatus.healthy and consecutive < 3:
        status_code = 200
    else:
        status_code = 503
        logger.warning(
            service="api-server",
            message="health_check_degraded",
            extra={
                "status": response.status.value
                if hasattr(response.status, "value")
                else str(response.status),
                "consecutive_failures": consecutive,
            },
        )
    return JSONResponse(
        content=response.model_dump(),
        status_code=status_code,
    )


async def _get_ready(request: Request) -> JSONResponse:
    """GET /ready — 启动就绪探针端点。

    Args:
        request: FastAPI Request 对象。

    Returns:
        JSONResponse: 响应体符合 ReadinessResponse 契约。
            200 OK：PostgreSQL 连通
            503 Service Unavailable：PostgreSQL 不连通
    """
    response = await check_ready()
    status_code = 200 if response.ready else 503
    if not response.ready:
        logger.warning(
            service="api-server",
            message="readiness_check_failed",
            extra={"ready": False},
        )
    return JSONResponse(
        content=response.model_dump(),
        status_code=status_code,
    )


# 主路径（短路径，供 Docker HEALTHCHECK 和运维脚本使用）
router.get(
    "/health",
    summary="系统整体健康检查",
    description=(
        "并发探测 PostgreSQL、Redis、MinIO 三个基础服务的连通性。"
        "全部健康返回 200，任一不连通返回 503。"
    ),
    responses={
        200: {"description": "全部组件连通"},
        503: {"description": "部分或全部组件不连通"},
    },
)(_get_health)

router.get(
    "/ready",
    summary="启动就绪探针",
    description=(
        "仅检查 PostgreSQL 连通性（不检查 Redis/MinIO），"
        "用于容器启动阶段的就绪判定。"
    ),
    responses={
        200: {"description": "PostgreSQL 连通，服务就绪"},
        503: {"description": "PostgreSQL 不连通"},
    },
)(_get_ready)

# 版本化别名（供外部监控系统按需使用）
router.add_api_route(
    "/api/v1/health",
    endpoint=_get_health,
    methods=["GET"],
    summary="系统整体健康检查（版本化路径）",
    description="GET /health 的版本化别名，指向同一处理函数。",
    responses={
        200: {"description": "全部组件连通"},
        503: {"description": "部分或全部组件不连通"},
    },
)

router.add_api_route(
    "/api/v1/ready",
    endpoint=_get_ready,
    methods=["GET"],
    summary="启动就绪探针（版本化路径）",
    description="GET /ready 的版本化别名，指向同一处理函数。",
    responses={
        200: {"description": "PostgreSQL 连通，服务就绪"},
        503: {"description": "PostgreSQL 不连通"},
    },
)
