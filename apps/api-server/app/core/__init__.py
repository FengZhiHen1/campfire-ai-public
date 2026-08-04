"""api-server 核心基础设施层。

提供跨模块共享的基础能力：
    - health: 健康检查端点（/health, /ready）
    - dependencies: FastAPI Depends 依赖注入工厂
    - middleware: 全局中间件（限流、校验异常处理）
    - streaming: SSE 流式推送服务（S3 由内核事件总线驱动重建）

Usage:
    from app.core.health import router as health_router
    from app.core.dependencies import get_db_session
    from app.core.middleware import RateLimitMiddleware, register_validation_handler
"""

from app.core.dependencies import (
    get_current_user,
    get_db_session,
    get_user_repository,
    require_roles,
)
from app.core.health import router as health_router
from app.core.middleware import RateLimitMiddleware, register_validation_handler

__all__ = [
    # 健康检查
    "health_router",
    # 依赖注入
    "get_db_session",
    "get_user_repository",
    "get_current_user",
    "require_roles",
    # 中间件
    "RateLimitMiddleware",
    "register_validation_handler",
]
