"""FastAPI 入口：路由装配、中间件、健康检查与工具注册。

职责：装配 FastAPI 应用、SuperTokens 中间件与工具注册，并暴露自有路由。
边界：只做入口装配；面的 HTTP 与 SSE 契约不属于本模块。
参考：docs/项目结构设计.md 第 2、7 节。
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed；行为由集成测试锁定
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from supertokens_python.framework.fastapi import get_middleware

from campfire.agent.model import check_model_endpoint
from campfire.core.auth import check_auth_core
from campfire.core.auth.supertokens import init_supertokens
from campfire.core.authz import set_authorizer
from campfire.core.cache import close_cache, get_cache
from campfire.core.config import Settings, get_settings
from campfire.core.db import check_database, dispose_engine
from campfire.core.health import ComponentHealth, HealthReport, Status
from campfire.core.jobs import check_queue, set_dispatch_hook
from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields
from campfire.modules.library.routes import router as library_router
from campfire.modules.memory.routes import router as memory_router
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.routes import router as profile_router
from campfire.surfaces.consult import composition as consult_composition
from campfire.surfaces.consult import router as consult_router
from campfire.surfaces.consult.assembly import ConsultAssemblyError, get_skill_registry, runner_is_wired
from campfire.surfaces.consult.runbus import cancel_pumps

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
    # Redis 客户端按进程建一次（连接池复用；见 core/cache 的说明）。这里只是让
    # 「第一次请求才建池」提前到启动，池的构造本身不发连接，因此不影响启动顺序。
    get_cache(settings)
    # 咨询面的生产装配（2026-10-01）：构造模型网关、工具池、技能注册表、引用索引与会话
    # 工厂，装成 AgentRunner 并注入注入点。此前这里只记一条 warning，发消息端点在生产
    # 路径上必然回 503。
    #
    # 装配失败不让进程起不来（刻意取舍）：`/health`、档案面、记忆面、资料库面都不跑 Agent，
    # 它们照常可用；而 `install` 失败会留下未注入状态，`/readyz` 因此报 503
    # （见 `check_agent_assembly`）——部署系统据此不给流量，运维则仍能 curl `/health`
    # 看到失败原因。若在这里直接抛，容器会反复重启，连诊断入口都没有。
    try:
        consult_composition.install(settings)
    except Exception as exc:  # noqa: BLE001 —— 装配失败是启动期可诊断状态，不是崩溃
        # 只记异常类型名，可能带上可操作的一行：模型网关的配置错误文案本身不含凭据
        # （见 `ModelConfigurationError` 的构造点），而底层驱动异常可能含代理 URL。
        logger.error(
            "咨询面运行器装配失败（%s）：发消息端点将回 503，/readyz 会报 agent_assembly 不可用",
            type(exc).__name__,
        )
    logger.info("campfire api 启动：环境=%s", settings.app_env)
    yield
    # 收尾顺序（有依赖方向，不可随意交换）：
    # 1. 先停后台推进任务——它们会继续写 Redis，且在途的运行还要用模型网关；
    # 2. 再关模型网关的 HTTP 连接池（此时已无运行在用）;
    # 3. 再关 Redis 连接池；
    # 4. 最后释放数据库引擎（会话工厂由它派生，先放它会留下悬空引擎引用）。
    cancel_pumps()
    await consult_composition.aclose()
    await close_cache()
    await dispose_engine()
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
# 咨询面的自有路由（HTTP 与 SSE 契约第 3、4 节）。`include_router` 而不是中间件：
# 这些是普通业务端点，鉴权由各自的 `require_session` 依赖完成；SDK 的 `/auth/*`
# 走中间件是因为它需要控制 cookie 与路径前缀的原生行为。
#
# 按面分组是因为路径前缀（`/consult`）就是面的边界，且将来的应急面与档案面各有
# 自己的路由表——一个 `include_router` 一行，装配处一眼能看出哪些面已挂载。
app.include_router(consult_router)


async def check_falkordb(settings: Settings) -> ComponentHealth:
    """探测 FalkorDB 图库可达性（`PING`）。

    为什么需要它：记忆面（时间线、纠正、删除）与应急预注入都要读图库，而它此前不在
    任何健康项里——图库挂了 `/health` 仍可能全绿，直到使用者第一次回看记忆才暴露。

    用底层驱动的 `PING` 而不构造 `MemoryGraph`：后者会建三个模型客户端与一个 HTTP
    客户端（`build_memory_graph` 的 docstring 记录了每次重建泄漏一整套连接池），
    而探针不该为了探活把生产资源拉起来。探针按调用建连、用毕即关。

    失败只回报异常类型：FalkorDB 的报错文本可能含主机与端口。

    构造也必须在 `try` 内（实测教训，2026-10-01）：`FalkorDB(...)` 的构造函数**本身就
    发网络 I/O**——图库不可达时它在构造期就抛 `ConnectionError`。第一版把构造写在
    `try` 之外，于是 `/readyz` 在图库挂掉时回 **500**（未捕获异常）而不是「503 且
    falkordb 项不可用」。这正好毁掉这个探针存在的意义：让健康检查如实报告，
    而不是把自己炸掉。同一教训在 `tests/conftest.py` 的
    `connect_falkordb_or_skip` 里已有记录（那里也是为此把构造放进 try）。
    """
    client: FalkorDB | None = None
    try:
        client = FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            password=(settings.falkordb_password.get_secret_value() if settings.falkordb_password else None),
            socket_timeout=settings.falkordb_timeout_seconds,
            socket_connect_timeout=settings.falkordb_timeout_seconds,
        )
        await client.connection.ping()
    except Exception as exc:  # noqa: BLE001 —— 探针吞掉一切驱动异常并如实上报
        return ComponentHealth("falkordb", Status.UNAVAILABLE, f"图库不可达（{type(exc).__name__}）")
    finally:
        # 构造失败时 client 仍为 None，故先判空；关闭失败不得掩盖上面那条结论
        # （探针的返回值已经确定，收尾异常只吞掉，否则健康检查会因清理失败而 500）。
        if client is not None:
            with suppress(Exception):
                await client.connection.aclose()
    return ComponentHealth("falkordb", Status.OK, "连接正常")


async def check_agent_assembly(_settings: Settings) -> ComponentHealth:
    """报告咨询面运行器是否已完成生产装配。

    为什么这一项必须进 readiness（2026-10-01）：`AgentRunner` 的装配此前只在启动日志里
    留一条 warning，于是存在这种完全可能的生产状态——

        GET /health → 200 OK
        POST /consult/... → 503 runner not wired

    部署系统据此认为一个不能提供核心业务的版本已经健康，Docker healthcheck、
    Nginx upstream 与 CD 发布验证全都被骗过。把装配状态变成一个探针，这条假健康就
    在机器层面不成立。

    只看注入点是否就绪（`runner_is_wired`），不在这里构造运行器：构造要连库与建工具池，
    而那是启动期已经做过的事；探针只回答「那时候成没成」。
    """
    if not runner_is_wired():
        return ComponentHealth(
            "agent_assembly",
            Status.UNAVAILABLE,
            "咨询面运行器未装配：发消息端点会回 503（见 surfaces/consult/composition.py）",
        )
    return ComponentHealth("agent_assembly", Status.OK, "运行器已装配")


async def check_skill_registry(settings: Settings) -> ComponentHealth:
    """探测技能内容根目录可发现（skill 是产品方法论的载体，缺了运行照跑但没技能可用）。

    与 `check_agent_assembly` 分开（理由见 `_READINESS_PROBES` 的说明）：注册表发现失败
    的文案能直接指向内容目录，而并入装配项后那句文案会被「运行器没接线」掩盖。

    发现结果按路径缓存在 `assembly`，因此这个探针在稳态下不重复读盘。
    """
    try:
        registry = get_skill_registry(settings)
    except ConsultAssemblyError as exc:
        return ComponentHealth("skills", Status.UNAVAILABLE, str(exc))
    return ComponentHealth("skills", Status.OK, f"已发现 {len(registry.names())} 个 skill")


#: readiness 探测的能力清单。`/readyz` 与 `/health` 共用它，因此两处口径不会漂移。
#:
#: 七项对应 docs/项目结构设计.md 第 10 节与上线前清单：认证 core、主库、队列（Redis）、
#: 模型、图库、Agent 装配、skill 注册表。
#:
#: 为什么 skill 注册表单独一项而不是并入 agent_assembly：技能内容坏掉（畸形 frontmatter）
#: 时装配会整体失败，但那时「哪一半坏的」看不出来；而注册表发现失败有单独的异常路径
#: （`ConsultAssemblyError` 的文案区分「运行器没接线」与「内容根目录不可用」），
#: 分开报能让排查直接指向内容而不是代码。
_READINESS_PROBES: tuple[tuple[str, Callable[[Settings], Awaitable[ComponentHealth]]], ...] = (
    ("auth", check_auth_core),
    ("database", check_database),
    ("queue", check_queue),
    ("model", check_model),
    ("falkordb", check_falkordb),
    ("agent_assembly", check_agent_assembly),
    ("skills", check_skill_registry),
)


@app.get("/livez")
async def livez() -> JSONResponse:
    """存活探针：进程还活着就 200，不探测任何依赖。

    与 `/readyz` 分开的理由是两者的故障语义相反：依赖不可用时进程本身没坏，
    重启它没有意义（还可能有损），而容器编排需要能区分这两种状态——
    只有分开，才能在「主库短时抖动」时不触发一轮无谓重启。
    """
    return JSONResponse(content={"status": "ok"}, status_code=200)


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """就绪探针：全部依赖与装配都可用才 200，否则 503。

    这是给部署系统用的判据（Docker healthcheck、Nginx upstream、CD 发布验证），
    与 `/health` 的区别是它**必须覆盖核心业务链**——尤其是 Agent 装配：
    缺了那一项，一个核心咨询功能必然 503 的版本会被判为健康。

    探测并发执行，避免串行累加超时。
    """
    settings = get_settings()
    components: tuple[ComponentHealth, ...] = tuple(
        await asyncio.gather(*(probe(settings) for _, probe in _READINESS_PROBES))
    )
    report = HealthReport(components)
    return JSONResponse(
        content=report.as_dict(),
        status_code=200 if report.is_ready else 503,
    )


@app.get("/health")
async def health() -> JSONResponse:
    """组件诊断：分别报告各项能力，有不可用时返回 503。

    保留它与 `/health` 这个路径，是因为既有部署脚本、探针与前端都可能引用它
    （`test_consult_endpoints_integration.py` 也断言它未登录可达）。语义上与
    `/readyz` 相同（同一份探针清单），差别只在用途命名：`/readyz` 面向机器判据，
    `/health` 面向人排查——因此这里额外回报每项的 detail。

    未登录可达（`AC-01`）：Nginx 上游检查与容器健康检查不持会话。它不构成业务能力，
    且只回报组件状态与异常类型，不复述连接串、凭据或内部拓扑。

    七项对应 docs/项目结构设计.md 第 10 节与上线前清单。其中设计所写的「公开内容可达」
    与「全应用必须登录」（`RQ-ACC-01`）冲突——已不存在未登录可达的内容路径——
    故此处报告「认证 core 可达」。
    """
    return await readyz()
