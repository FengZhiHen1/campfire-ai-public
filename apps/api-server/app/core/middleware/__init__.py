"""中间件模块 — FastAPI 全局中间件集合。

提供：
    - RateLimitMiddleware: 防刷限流（Redis ZSET + LUA 滑动窗口）
    - register_validation_handler: 自定义校验异常处理器
"""

from app.core.middleware.rate_limit import RateLimitMiddleware
from app.core.middleware.validation_handler import register_validation_handler

__all__ = [
    "RateLimitMiddleware",
    "register_validation_handler",
]
