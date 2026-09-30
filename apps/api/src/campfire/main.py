"""FastAPI 入口：路由装配、中间件、健康检查与工具注册。

职责：装配 FastAPI 应用、SuperTokens 中间件与工具注册，并暴露自有路由。
边界：只做入口装配；面的 HTTP 与 SSE 契约不属于本模块。
参考：docs/项目结构设计.md 第 2、7 节。
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from supertokens_python.framework.fastapi import get_middleware

from campfire.agent.model import check_model_endpoint
from campfire.core.auth import check_auth_core
from campfire.core.auth.supertokens import init_supertokens
from campfire.core.authz import set_authorizer
from campfire.core.cache import close_cache, get_cache
from campfire.core.config import Settings, get_settings
from campfire.core.db import check_database
from campfire.core.health import ComponentHealth, HealthReport, Status
from campfire.core.jobs import check_queue
from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.surfaces.consult import router as consult_router
from campfire.surfaces.consult.assembly import runner_is_wired
from campfire.surfaces.consult.runbus import cancel_pumps

logger = logging.getLogger("campfire")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """进程级生命周期：初始化日志与认证 SDK，停止时记录一条结束日志。

    装配职责见 docs/项目结构设计.md 第 2 节与第 7 节：工具注册与复写注入在装配处完成，
    因此 `core/auth` 不需要 import `modules/accounts`。

    一期只有 `/health` 一条自有路由。咨询面的 HTTP 与 SSE 契约归 `surfaces/consult`；
    认证面（`/auth/*`）由 SuperTokens 中间件挂载，其契约归
    docs/技术设计/technical-details/认证与账号.md 第 5 节。

    一期不在启动时连数据库或模型——健康检查按请求探测，避免启动顺序耦合。
    认证 SDK 是例外：它必须在应用开始处理请求之前完成装配，否则 `/auth/*`
    与 `require_session` 都会在首次请求时才失败。

    注册复写在装配处注入（`api_overrides`）：邀请码的状态机在
    `modules/accounts`，而 `core/auth` 不得依赖 `modules/*`（项目结构设计第 7 节）。
    这与「工具注册在装配处完成」是同一种做法。

    授权实现同样在装配处注入（`set_authorizer`）：端口与错误类型在 `core/authz`，
    而「属主即允许」要读支持对象表、属 `modules/profile`——`core/*` 不得依赖
    `modules/*`（支持对象第 5.1 节）。注入只需一次，判定按调用自开会话
    （实现不能绑定某个请求的会话，见 `OwnerAuthorizer` 的说明）。
    """
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_supertokens(settings, api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)
    set_authorizer(OwnerAuthorizer(settings))
    # Redis 客户端按进程建一次（连接池复用；见 core/cache 的说明）。这里只是让
    # 「第一次请求才建池」提前到启动，池的构造本身不发连接，因此不影响启动顺序。
    get_cache(settings)
    if not runner_is_wired():  # pragma: no cover —— 生产装配缺失时的启动期提示
        # 咨询面的运行器由装配处注入，而它需要引用索引的持久化实现（全仓库尚无）。
        # 这里只记一条警告：发消息端点会回 503，而不是回一个调用不了的 202。
        logger.warning("咨询面运行器尚未装配：发消息端点将回 503（见 surfaces/consult/assembly.py）")
    logger.info("campfire api 启动：环境=%s", settings.app_env)
    yield
    # 收尾顺序：先停后台推进任务（它们会继续写 Redis），再关连接池。
    cancel_pumps()
    await close_cache()
    logger.info("campfire api 停止")


async def check_model(settings: Settings) -> ComponentHealth:
    """把基座的模型端点探测结果映射为本进程的健康项。

    映射放在装配处而不是基座内：`agent/*` 的依赖白名单只放行 `core/config`
    （docs/项目结构设计.md 第 7 节），基座不得依赖 `core/health`。
    """
    report = await check_model_endpoint(settings)
    if not report.configured:
        return ComponentHealth("model", Status.NOT_CONFIGURED, report.detail)
    status = Status.OK if report.reachable else Status.UNAVAILABLE
    return ComponentHealth("model", status, report.detail)


app = FastAPI(title="篝火智答 API", version="0.1.0", lifespan=lifespan)

# SuperTokens 中间件：它负责挂载 `/auth/*`（signup、signin、refresh、signout、
# 密码重置等由 SDK 提供的路由）。认证面的接入点由「SDK 挂载的路由」与「我们自建的
# 业务端点」两部分组成（认证与账号第 5 节），这是前者。
#
# 中间件而非 `include_router`：SDK 内部按 path 前缀分派，且需要读写 cookie，
# 用中间件才能保持它的原生行为。
app.add_middleware(get_middleware())

# 咨询面的自有路由（HTTP 与 SSE 契约第 3、4 节）。`include_router` 而不是中间件：
# 这些是普通业务端点，鉴权由各自的 `require_session` 依赖完成；SDK 的 `/auth/*`
# 走中间件是因为它需要控制 cookie 与路径前缀的原生行为。
#
# 按面分组是因为路径前缀（`/consult`）就是面的边界，且将来的应急面与档案面各有
# 自己的路由表——一个 `include_router` 一行，装配处一眼能看出哪些面已挂载。
app.include_router(consult_router)


@app.get("/health")
async def health() -> JSONResponse:
    """分别报告各项能力；有不可用时返回 503。

    这是全应用唯一的未登录可达端点（`AC-01`）：Nginx 上游检查与容器健康检查
    不持会话，因此它必须匿名可达；但它不构成业务能力，且只回报组件状态与异常
    类型，不复述连接串、凭据或内部拓扑。

    四项对应 docs/项目结构设计.md 第 10 节。其中设计所写的「公开内容可达」与
    「全应用必须登录」（`RQ-ACC-01`）冲突——已不存在未登录可达的内容路径——
    故此处报告「认证 core 可达」。

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
