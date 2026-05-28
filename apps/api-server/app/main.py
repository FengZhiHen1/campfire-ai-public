"""Campfire-AI API Server — FastAPI 应用入口。

MVP Phase 0 精简版：
- 认证完全绕过（从 X-Device-Id 提取匿名身份）
- 挂载全部业务路由
- CORS / 限流 / 校验异常处理器
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.cases import router as cases_router
from app.api.v1.consult import router as consult_router
from app.api.v1.consult.stream import router as stream_router
from app.api.v1.consultations import router as consultations_router
from app.api.v1.health import router as health_router
from app.api.v1.profiles import router as profiles_router
from app.api.v1.reviews import router as reviews_router
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.validation_handler import register_validation_handler
from py_config import get_settings
from py_logger import logger


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

    yield
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
    app.include_router(consult_router)
    app.include_router(stream_router)
    app.include_router(consultations_router)
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
        log_level="info",
    )


if __name__ == "__main__":
    main()
