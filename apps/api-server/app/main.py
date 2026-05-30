"""Campfire-AI API Server — FastAPI 应用入口。

MVP Phase 0 精简版：
- 认证完全绕过（从 X-Device-Id 提取匿名身份）
- 挂载全部业务路由
- CORS / 限流 / 校验异常处理器
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send, Message

# 确保 root logger 有 stdout handler，uvicorn access log 依赖此配置
logging.basicConfig(format="%(message)s", stream=sys.stdout, force=True)


class AccessLogMiddleware:
    """ASGI 中间件，通过 py_logger 输出结构化 access log。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_code: int = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        client = scope.get("client")
        addr = f"{client[0]}:{client[1]}" if client else "-"
        duration_ms = (time.monotonic() - start) * 1000

        logger.info(
            "api-server",
            f"{addr} - \"{method} {path}\" {status_code}",
            op_type="access",
            extra={
                "method": method,
                "path": path,
                "status_code": status_code,
                "client_addr": addr,
                "duration_ms": round(duration_ms, 2),
            },
        )

from app.core.dependencies.auth_dependencies import _get_session_factory
from app.core.health import router as health_router
from app.core.middleware.rate_limit import RateLimitMiddleware
from app.core.middleware.validation_handler import register_validation_handler
from app.modules.auth import auth_router
from app.modules.cases import cases_router, narratives_router, reviews_router
from app.modules.consultation import consult_router, consultations_router, stream_router
from app.modules.profiles import events_router, experts_router, profiles_router
from py_config import get_settings
from py_logger import logger
from py_rag.indexing.worker import start_worker, stop_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理器。

    启动：加载配置、预热日志、记录启动事件。
    关闭：记录关闭事件。
    """
    settings = get_settings()
    logger.info(
        "api-server",
        "Campfire-AI API Server 启动中",
        extra={
            "database_url": str(settings.DATABASE_URL),
            "redis_url": str(settings.REDIS_URL),
        },
    )

    # 自动初始化 MinIO bucket（若不存在则创建，失败不阻塞启动）
    try:
        from minio import Minio

        minio_client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY.get_secret_value(),
            secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
            secure=False,
        )
        if not minio_client.bucket_exists("campfire"):
            minio_client.make_bucket("campfire")
            logger.info("api-server", "MinIO bucket 'campfire' 已自动创建")
    except Exception:
        # 开发环境 MinIO 可能未运行，失败不影响主流程
        pass

    # 设置数据库会话工厂（Worker 消费任务时创建独立会话）
    app.state.db_session_factory = _get_session_factory()

    # 启动索引 Worker 协程（监听 Redis 队列，消费案例索引任务）
    start_worker(app)

    yield

    # 优雅停止 Worker
    stop_worker(app)
    logger.info("api-server", "Campfire-AI API Server 关闭中")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""

    app = FastAPI(
        title="Campfire-AI API",
        description="篝火智答 — 孤独症家属智能应急咨询平台 MVP API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # CORS 中间件（允许微信小程序开发环境）
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # MVP 阶段放开，生产环境需限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # access log 中间件（uvicorn 原生格式）
    app.add_middleware(AccessLogMiddleware)

    # ------------------------------------------------------------------
    # 限流中间件（Redis ZSET 滑动窗口）
    # ------------------------------------------------------------------
    app.add_middleware(RateLimitMiddleware)

    # ------------------------------------------------------------------
    # 全局异常处理器（Pydantic 422 → 统一格式）
    # ------------------------------------------------------------------
    register_validation_handler(app)

    # ------------------------------------------------------------------
    # 路由挂载
    # ------------------------------------------------------------------
    # 健康检查（无 prefix）
    app.include_router(health_router)

    # 业务路由
    # 注意：reviews_router 必须在 cases_router 之前注册，
    # 否则 cases_router 的 /{case_id} 会拦截 /review-queue
    app.include_router(auth_router)
    app.include_router(reviews_router)
    app.include_router(cases_router)
    app.include_router(narratives_router)
    app.include_router(consult_router)
    app.include_router(stream_router)
    app.include_router(consultations_router)
    app.include_router(events_router)
    app.include_router(experts_router)
    app.include_router(profiles_router)

    return app


# 全局应用实例（供 uvicorn / gunicorn 导入）
app = create_app()


def main() -> None:
    """CLI 入口：uvicorn app.main:app --reload。"""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        access_log=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
