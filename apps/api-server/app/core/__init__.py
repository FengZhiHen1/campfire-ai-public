"""api-server 核心基础设施层。

提供跨模块共享的基础能力：
    - health: 健康检查端点（/health, /ready）
    - dependencies: FastAPI Depends 依赖注入工厂
    - middleware: 全局中间件（限流、校验异常处理）
    - streaming: SSE 流式推送服务（惰性导入，避免启动期循环依赖）

Usage:
    from app.core.health import router as health_router
    from app.core.dependencies import get_db_session
    from app.core.middleware import RateLimitMiddleware, register_validation_handler
    from app.core.streaming import StreamSessionManager, SseStreamingService
"""

from app.core.dependencies import (
    get_anonymous_user,
    get_db_session,
    get_user_repository,
)
from app.core.health import router as health_router
from app.core.middleware import RateLimitMiddleware, register_validation_handler

# streaming 子包依赖 app.modules.consultation，在模块级导入会触发循环依赖。
# 使用者应直接从 app.core.streaming 导入所需符号。
#   from app.core.streaming import StreamSessionManager, SseStreamingService


def get_stream_session_manager():
    """惰性获取 StreamSessionManager 单例。"""
    from app.core.streaming import StreamSessionManager

    return StreamSessionManager()


def get_sse_streaming_service():
    """惰性获取 SseStreamingService 单例。"""
    from app.core.streaming import SseStreamingService

    return SseStreamingService()


__all__ = [
    # 健康检查
    "health_router",
    # 依赖注入
    "get_db_session",
    "get_user_repository",
    "get_anonymous_user",
    # 中间件
    "RateLimitMiddleware",
    "register_validation_handler",
    # 流式推送（惰性访问器）
    "get_stream_session_manager",
    "get_sse_streaming_service",
]
