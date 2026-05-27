"""py-health: Campfire-AI 健康检查共享包。

提供系统整体健康检查的核心探测逻辑和公共接口。

通过 ``from py_health import check_all, check_ready`` 导入核心函数，
在 FastAPI 路由中直接调用。

导出清单：
    - check_all(): 执行全部三个基础服务的并发连通性检查
    - check_ready(): 仅检查 PostgreSQL（启动就绪探针）
    - HealthCheckResponse: GET /health 响应模型
    - ReadinessResponse: GET /ready 响应模型
    - ComponentHealth: 单个组件检查详情
    - HealthStatus: 系统整体健康状态枚举
    - ComponentStatus: 组件连通性状态枚举
"""

from __future__ import annotations

from py_health.checker import check_all, check_ready
from py_health.models import (
    ComponentHealth,
    ComponentStatus,
    Components,
    HealthCheckResponse,
    HealthStatus,
    ReadinessResponse,
)

__all__ = [
    "check_all",
    "check_ready",
    "HealthCheckResponse",
    "ReadinessResponse",
    "ComponentHealth",
    "Components",
    "HealthStatus",
    "ComponentStatus",
]
