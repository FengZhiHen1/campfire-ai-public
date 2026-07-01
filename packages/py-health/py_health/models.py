"""OBS-04 健康检查 — Pydantic 响应模型定义。

本模块定义健康检查的全部对外输出类型，严格对齐
``docs/contracts/OBS-04/`` 下的 5 份 JSON Schema 契约。

类型定义清单：
    - HealthStatus: 系统整体健康状态枚举
    - ComponentStatus: 组件连通性状态枚举
    - ComponentHealth: 单个组件检查详情
    - Components: 三个组件检查结果的容器
    - HealthCheckResponse: GET /health 端点响应体
    - ReadinessResponse: GET /ready 端点响应体
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    """系统整体健康状态枚举。

    每次健康检查请求实时计算全部三个基础服务的连通性，
    基于组件级结果判定整体状态。

    契约引用：docs/contracts/OBS-04/HealthStatus.json
    """

    healthy = "healthy"
    """全部三个组件（PostgreSQL、Redis、MinIO）均连通。"""
    degraded = "degraded"
    """至少一个组件不连通但非全部不连通，部分功能受损。"""
    unhealthy = "unhealthy"
    """全部三个组件均不连通，系统无法提供任何服务。"""


class ComponentStatus(str, Enum):
    """单个基础组件的连通性状态枚举。

    用于表示 PostgreSQL、Redis、MinIO 三个组件的各自健康检查结果。

    契约引用：docs/contracts/OBS-04/ComponentStatus.json
    """

    connected = "connected"
    """组件连通性检查通过。"""
    disconnected = "disconnected"
    """组件连通性检查失败。"""


class ComponentHealth(BaseModel):
    """单个基础组件的连通性检查详情。

    包含连通状态和可选的失败原因。内嵌于
    HealthCheckResponse.components.* 和 ReadinessResponse.database 中。

    契约引用：docs/contracts/OBS-04/ComponentHealth.json
    """

    status: ComponentStatus = Field(description="组件连通状态，connected 表示检查通过，disconnected 表示失败")
    error: str | None = Field(
        default=None,
        min_length=1,
        description=("连通性检查失败时的错误描述（如连接超时、认证失败、服务未启动）。connected 状态时此字段为 null"),
    )

    model_config = {"extra": "forbid"}


class Components(BaseModel):
    """三个基础服务连通性检查结果的容器。

    键名固定为 postgresql、redis、minio，
    对应 HealthCheckResponse.components 对象。

    契约引用：docs/contracts/OBS-04/HealthCheckResponse.json §components
    """

    postgresql: ComponentHealth = Field(description="PostgreSQL 数据库的连通性检查结果")
    redis: ComponentHealth = Field(description="Redis 缓存服务的连通性检查结果")
    minio: ComponentHealth = Field(description="MinIO 对象存储服务的连通性检查结果")

    model_config = {"extra": "forbid"}


class HealthCheckResponse(BaseModel):
    """GET /health 端点的 JSON 响应体。

    包含系统整体健康状态、三个基础服务各自的连通性详情和检查时间戳。
    当 status=healthy 时返回 HTTP 200；degraded 或 unhealthy 时返回 HTTP 503。

    契约引用：docs/contracts/OBS-04/HealthCheckResponse.json
    """

    status: HealthStatus = Field(description="系统整体健康状态，基于全部三个组件的连通性检查结果实时判定")
    version: str = Field(
        min_length=1,
        description="当前 API 服务的版本号，从 pyproject.toml 或环境变量读取",
        examples=["0.1.0"],
    )
    uptime_seconds: int = Field(
        ge=0,
        description="API 服务自启动以来的运行时长（秒）",
        examples=[3600],
    )
    components: Components = Field(description="三个基础服务的连通性检查详情")
    timestamp: str = Field(
        description="本次健康检查的执行时间，ISO 8601 格式，精确到秒",
        examples=["2026-05-26T23:07:02+08:00"],
    )

    model_config = {"extra": "forbid"}


class ReadinessResponse(BaseModel):
    """GET /ready 端点的 JSON 响应体。

    用于启动就绪判定，仅检查 PostgreSQL 组件的连通性状态
    （不检查 Redis/MinIO）。当 database.status=connected 时返回 HTTP 200；
    否则返回 HTTP 503。

    契约引用：docs/contracts/OBS-04/ReadinessResponse.json
    """

    ready: bool = Field(
        description="服务是否就绪：仅当 PostgreSQL 连通时为 true",
        examples=[True],
    )
    database: ComponentHealth = Field(description="PostgreSQL 数据库的连通性检查结果")
    timestamp: str = Field(
        description="本次就绪检查的执行时间，ISO 8601 格式，精确到秒",
        examples=["2026-05-26T23:07:02+08:00"],
    )

    model_config = {"extra": "forbid"}
