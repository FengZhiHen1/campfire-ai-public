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
from campfire.core.config import Settings, get_settings
from campfire.core.db import check_database
from campfire.core.health import ComponentHealth, HealthReport, Status
from campfire.core.jobs import check_queue, set_dispatch_hook
from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields
from campfire.modules.library.routes import router as library_router
from campfire.modules.memory.routes import router as memory_router
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.routes import router as profile_router

# 投递钩子的实现属于 Worker 入口（任务对象 `consume_memory_episode_task` 定义在那里），
# 而投递的发生点在请求路径上（写入路径第 4 节第 1 条：请求事务提交后再投递）。
# 两个入口文件之间直接引用：`main.py` / `worker.py` 都不属于任何层，层白名单不管它们，
# 而把任务定义搬到第三个模块属另一主题的重构（本次不改）。
from campfire.worker import dispatch_pending_write_to_queue

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

    投递钩子也必须在本入口注入（`set_dispatch_hook`）：写入路径第 4 节第 1 条要求
    「请求事务提交后再投递 Taskiq 任务」，而投递调用发生在请求路径上的产品侧工具里
    （`tools/memory`、`tools/profile`）。只由 Worker 入口注入时 API 进程的钩子是空的，
    每次投递都落进 `core/jobs` 的 warning，所有写入要等 Worker 每 5 分钟的兜底扫描
    ——那与第 4 节第 1 条相反（2026-09-30 修复前的实际行为）。
    实现从 `campfire.worker` 引用：任务对象定义在那里，本文件与它同属入口、不在层白名单管辖内。
    """
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_supertokens(settings, api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)
    set_authorizer(OwnerAuthorizer(settings))
    set_dispatch_hook(dispatch_pending_write_to_queue)
    logger.info("campfire api 启动：环境=%s", settings.app_env)
    yield
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

# 非 Agent 面的自有路由：档案面、记忆面、资料库面。
#
# 这三个面不装配 Agent 运行（docs/项目结构设计.md 第 5 节），因此不建 `surfaces/`，
# 路由就放在各自的业务模块里（`modules/<m>/routes.py`）——契约的用例就在该模块，
# 路由是用例的 HTTP 皮肤。这与「认证不建面、契约归认证与账号」同构。
#
# 它们经 `include_router` 挂载而不是中间件：这些是我们自建的普通业务端点，
# 路径前缀由各自的 router 声明（认证面那条 `/auth/*` 是 SDK 提供的路由，
# 必须走中间件，见上）。
app.include_router(profile_router)
app.include_router(memory_router)
app.include_router(library_router)


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
