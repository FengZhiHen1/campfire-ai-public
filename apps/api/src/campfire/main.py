"""FastAPI 入口：路由装配、中间件、健康检查与工具注册。

装配职责见 docs/项目结构设计.md 第 2 节与第 7 节：**工具注册在装配处完成**，
因此 ``agent/*`` 不需要 import ``tools/*``。

一期只有 ``/health`` 一条路由。咨询面的 HTTP 与 SSE 契约归 ``surfaces/consult``，
工具注册与路由装配在此处接线；两者落地前不在此处发明占位端点。
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from campfire.agent.model import check_model_endpoint
from campfire.core.auth import check_auth_core
from campfire.core.config import Settings, get_settings
from campfire.core.db import check_database
from campfire.core.health import ComponentHealth, HealthReport, Status
from campfire.core.jobs import check_queue

logger = logging.getLogger("campfire")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """进程级生命周期：启动时按配置初始化日志，停止时记录一条结束日志。

    一期不在启动时连数据库或模型——健康检查按请求探测，避免启动顺序耦合。
    """
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("campfire api 启动：环境=%s", settings.app_env)
    yield
    logger.info("campfire api 停止")


async def check_model(settings: Settings) -> ComponentHealth:
    """把基座的模型端点探测结果映射为本进程的健康项。

    映射放在装配处而不是基座内：``agent/*`` 的依赖白名单只放行 ``core/config``
    （docs/项目结构设计.md 第 7 节），基座不得依赖 ``core/health``。
    """
    report = await check_model_endpoint(settings)
    if not report.configured:
        return ComponentHealth("model", Status.NOT_CONFIGURED, report.detail)
    status = Status.OK if report.reachable else Status.UNAVAILABLE
    return ComponentHealth("model", status, report.detail)


app = FastAPI(title="篝火智答 API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    """分别报告各项能力；有不可用时返回 503。

    四项对应 docs/项目结构设计.md 第 10 节。其中设计所写的「公开内容可达」与
    「全应用必须登录」（``RQ-ACC-01``，docs/技术栈设计.md 第 6 节）冲突——
    已不存在未登录可达的内容路径——故此处改为报告「认证 core 可达」。

    四项探测并发执行，避免串行累加超时。
    """
    settings = get_settings()
    components: tuple[ComponentHealth, ...] = tuple(
        await asyncio.gather(
            check_auth_core(settings),
            check_database(settings),
            check_model(settings),
            check_queue(settings),
        )
    )
    report = HealthReport(components)
    return JSONResponse(
        content=report.as_dict(),
        status_code=200 if report.is_ready else 503,
    )
