"""FastAPI 入口：路由装配、中间件、健康检查与工具注册。

职责：装配 FastAPI 应用、SuperTokens 中间件与工具注册，并暴露自有路由。
边界：只做入口装配；面的 HTTP 与 SSE 契约不属于本模块。
参考：docs/项目结构设计.md 第 2、7 节。
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from campfire.core.config import Settings, apply_no_proxy_normalization, get_settings

# 进程级规范化 `no_proxy` 家族（2026-10-05，T18 修）——**必须早于一切 httpx 消费者**。
#
# 为什么卡在「项目的其它 import 之前」而不是放进 lifespan：lifespan 要等 ASGI 服务器把
# 应用拉起来，而**客户端构造可以发生在导入期或 `app` 构造期**。放在这里，本模块之后
# 导入的每一个模块、以及此后的 `app` 构造、lifespan、请求处理，**在时序上都必然在它之后**
# ——这是最强的位置，也给得出最省事的证明（不需要逐模块论证「它导入时建不建客户端」）。
# 唯一的前置 import 是 `core/config` 自身，它只依赖标准库与 pydantic，不构造任何客户端。
#
# 为什么需要它：宿主机 `no_proxy` 含带方括号的 IPv6 字面量（`[::1]`）时，httpx 与 httpx2
# 都在**客户端构造期**抛 `InvalidURL: Invalid port: ':1]'`。既有两处防护**都不覆盖**
# SuperTokens 的 querier（它在每次请求里自己建客户端，未传 `trust_env=False`）——
# 于是注册/登录整体 500，而 `/readyz` 的 auth 探针（`trust_env=False`）仍报 ok。
#
# 与 `core/auth/supertokens.py` 里那次调用的关系（**两处都要，不是重复**）：
#
# - 这里给的是**入口级时序**：本进程任何 httpx/openai 消费者都在其后；
# - 那次给的是**不可遗忘**：`init_supertokens` 是唯一的 SDK 装配入口，**API 与 CLI**
#   两个进程都经它，因此「谁忘了在入口调一次」不会让 querier 重新坏掉。
#   而那正是这条缺陷此前的形态——防护只存在于两个不覆盖 querier 的路径上。
#
# ⚠ **Worker 不在此列**（2026-10-06 订正，T18 复查发现的 P2）：`worker.py` **不调**
# `init_supertokens`，它靠**自己模块导入期**的 `apply_no_proxy_normalization()` 覆盖
# 同一件事（`worker.py:47` 与它上方 41-46 行的「入口级保证」论证）。
# **订正这句不是为了措辞准确**：原先的「三进程都经它」会让后来者以为 Worker 的入口调用
# 是多余的、从而删掉它，而删掉之后 Worker 侧会重新暴露在同一个代理陷阱下。
#
# 幂等，因此两处都调没有副作用（见 `core/config.apply_no_proxy_normalization`）。
apply_no_proxy_normalization()

from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed；行为由集成测试锁定
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError
from supertokens_python.framework.fastapi import get_middleware

from campfire.agent.model import check_model_endpoint
from campfire.core.auth import check_auth_core
from campfire.core.auth.supertokens import init_supertokens
from campfire.core.authz import set_authorizer
from campfire.core.cache import close_cache, get_cache
from campfire.core.config import EMBEDDING_DIM
from campfire.core.db import check_database, dispose_engine
from campfire.core.health import ComponentHealth, HealthReport, Status
from campfire.core.jobs import check_queue, set_dispatch_hook
from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields
from campfire.modules.library.routes import router as library_router
from campfire.modules.memory.errors import MemoryConfigurationError
from campfire.modules.memory.graph import aclose_shared_memory_graph, build_memory_embedder
from campfire.modules.memory.routes import router as memory_router
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.routes import router as profile_router
from campfire.surfaces.consult import composition as consult_composition
from campfire.surfaces.consult import router as consult_router
from campfire.surfaces.consult.assembly import ConsultAssemblyError, get_skill_registry, runner_is_wired
from campfire.surfaces.consult.runbus import cancel_pumps, drain_pumps

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
    async with AsyncExitStack() as cleanup:
        # 回调逆序执行；取消请求之后必须等待推进任务退出，才可关闭它们依赖的连接。
        # 某项关闭失败时仍释放后续资源，异常照常向调用方传播。
        cleanup.push_async_callback(dispose_engine)
        cleanup.push_async_callback(close_cache)
        cleanup.push_async_callback(aclose_shared_memory_graph)
        cleanup.push_async_callback(consult_composition.aclose)
        cleanup.push_async_callback(drain_pumps)
        cleanup.callback(cancel_pumps)
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

#: 业务接口的统一前缀。见下面 `include_router` 处的说明：它让接口路径与前端**页面**路径
#: 不再可能相撞（页面在 `/consult`，接口在 `/api/consult`）。
#:
#: 存活/就绪/诊断三个探针**不**加这个前缀：它们是基础设施判据，Docker healthcheck、
#: Nginx 与 CD 都按固定短路径访问，把部署机器人的地址绑到业务前缀上只会让两侧都更难改。
_API_PREFIX = "/api"

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
# 业务路由统一挂在 /api 下（2026-10-01 修正）。
#
# 为什么必须加这一层前缀（实测缺陷，不是风格偏好）：此前四个面的路由直接挂在根
# （`/consult/*`、`/profile/*`、`/memory/*`、`/library/*`），而前端**页面路由**用了
# 同样的前缀（`/consult`、`/consult/sessions/:id`、`/consult/emergency`、`/profile`）。
# Nginx 里「转发给 API」的 location 是正则 `^/(auth|consult|profile|memory|library)(/|$)`，
# 而 nginx 的正则 location 优先级高于 SPA 的 `location /`——于是这四个页面被转发给 API：
# 实测 `/consult` → 404 JSON、`/profile` → 404 JSON、`/consult/emergency` → 405 JSON。
# 用户直接访问或刷新对话页/档案页会看到裸的 API 错误，而不是应用界面。
#
# 加 /api 使两类路径不再可能相撞：页面在 `/consult`，接口在 `/api/consult`。
#
# `include_router(prefix=...)` 而不是改各 router 声明：面的前缀（`/profile` 等）是面的
# 边界，属于各模块；对外暴露路径是装配决策，属于这里。两者分开，模块不必知道部署形态。
app.include_router(profile_router, prefix=_API_PREFIX)
app.include_router(memory_router, prefix=_API_PREFIX)
app.include_router(library_router, prefix=_API_PREFIX)
# 咨询面的自有路由（HTTP 与 SSE 契约第 3、4 节）。`include_router` 而不是中间件：
# 这些是普通业务端点，鉴权由各自的 `require_session` 依赖完成；SDK 的 `/auth/*`
# 走中间件是因为它需要控制 cookie 与路径前缀的原生行为。
#
# 按面分组是因为路径前缀（`/consult`）就是面的边界，且将来的应急面与档案面各有
# 自己的路由表——一个 `include_router` 一行，装配处一眼能看出哪些面已挂载。
app.include_router(consult_router, prefix=_API_PREFIX)


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
    `try` 之外，于是 `/readyz` 在图库挂掉时回 500（未捕获异常）而不是「503 且
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


_EMBEDDING_PROBE_TIMEOUT_SECONDS = 5.0
"""嵌入探针单次请求的时间上界（与 `agent/model/probe.py` 的 5 秒同一论证）。

理由：这是聚合等待的一端，不该吃掉调用方的容忍度；5 秒比一次真实运行的 180 秒上限
低一个半数量级，而一次极短输入的嵌入往返远快于它。**探针构造出的客户端
`max_retries=0`**（见 `build_memory_embedder`）⇒ 这个上界真是「一次请求」的上界，
不会被 SDK 重试放大成若干倍。"""

_EMBEDDING_PROBE_INPUT = "campfire readiness probe"
"""探针送入的文本：**固定字面量**，不含任何使用者数据，且远短于接口硬限。

为什么必须真的送一条：`GET /models` 只证明 chat 端点可达，抓不到**参数级**缺陷——
本项目真实踩过的那次是「embedder 未传 `encoding_format` ⇒ SDK 注入 `base64` ⇒
TokenHub 只接受 `float` ⇒ 400001 ⇒ 记忆写入路径整体不可用」，而当时 `/readyz` 全绿。"""


async def check_embedding(settings: Settings) -> ComponentHealth:
    """深度探针：真实发一次嵌入请求，并校验返回维度与常量一致。

    **为什么它不在 `/readyz` 里**（这是端点形状的决定性理由，不是疏忽）：
    这是一个**有成本**的探测——它会真的调用供应商、消耗配额。生产 healthcheck 是
    **每 15 秒**一次，把真实嵌入调用放进去约等于 **5760 次/天**。因此它与
    `/readyz` 分开，只在**发布验收与人工诊断**时按需调用（`/readyz/deep`）。

    **为什么必须有它**（同一形态的缺陷已真实发生两次）：
    `/readyz` 的 `model` 项只探 chat 端点（`GET /models`），而 chat 与 embedding 是两条
    独立链路。于是「健康检查全绿而记忆写入整体不可用」这类状态探不到——它发生过两次：
    宿主机 `no_proxy` 形态（注册/登录 500 而 `auth` 项绿）与 Graphiti embedder 漏传
    `encoding_format`（记忆写入全坏而 `model` 项绿）。

    覆盖的是**记忆写入路径**的嵌入器，而不是另建一个：构造经
    `modules/memory/graph.build_memory_embedder`——那是「记忆侧嵌入器怎么造」的唯一真源，
    生产装配（`build_memory_graph`）用的是同一个函数。若探针另写一份构造，就会与生产
    分叉，改坏生产也不会让它变红（那正是这类探针最典型的失效形态）。

    失败只回报异常类型与状态码，**不复述连接串、凭据或供应商响应体**（AGENTS.md 安全条款；
    与 `agent/model/probe.py` 的处置一致）。

    Note:
        维度断言的边界（实测，2026-10-05）：`TokenHubEmbedder.create()` 会把返回向量
        截断到 `EMBEDDING_DIM`。因此**「服务端返回更长」会被静默截掉而探不到**
        （实测 3072 → 返回 2560，探针绿），而「服务端返回更短」如实暴露为不一致
        （实测 2048 → 返回 2048，探针红）。这是本探针的已知残余，不是本包引入的：
        截断是 `TokenHubEmbedder` 的既有契约（该类的 docstring 明写「维度仍按
        `config.embedding_dim` 截断」），探针无法在不绕过生产构造的前提下绕过它。
    """
    try:
        # 自建客户端（不注入生产的 http_client）：探针要有自己的短超时，
        # 且它是服务端到服务端调用，不继承桌面代理豁免表（trust_env=False）。
        memory_embedder = build_memory_embedder(settings, timeout_seconds=_EMBEDDING_PROBE_TIMEOUT_SECONDS)
    except MemoryConfigurationError as exc:
        # 缺凭据：配置问题，不是可达性问题（与 `check_model` 的 not_configured 同形）。
        return ComponentHealth("embedding", Status.NOT_CONFIGURED, str(exc))
    except Exception as exc:  # noqa: BLE001 —— 构造失败（含代理词法问题）如实上报，不让端点 500
        return ComponentHealth(
            "embedding",
            Status.UNAVAILABLE,
            f"嵌入器构造失败（{type(exc).__name__}）",
        )

    model_name = settings.embedding_model_name
    try:
        vector = await memory_embedder.embedder.create(_EMBEDDING_PROBE_INPUT)
    except APITimeoutError as exc:
        # 顺序有讲究：实测 `APITimeoutError` 是 `APIConnectionError` 的子类，先判连接会把
        # 超时误报成网络问题——两者对排查者的含义完全不同（与 `agent/model/errors` 的
        # `classify_model_failure` 同一处判定、同一理由）。
        return ComponentHealth("embedding", Status.UNAVAILABLE, f"{model_name} 嵌入端点超时（{type(exc).__name__}）")
    except APIStatusError as exc:
        # **参数级缺陷落在这一档**：embedder 漏传 `encoding_format` 时 TokenHub 回
        # 400001（HTTP 400）⇒ `BadRequestError`（`APIStatusError` 的子类）。
        # 只报状态码与类型名：**不复述响应体**（可能含连接串/凭据片段）也不复述请求体。
        return ComponentHealth(
            "embedding",
            Status.UNAVAILABLE,
            f"{model_name} 嵌入端点返回 {exc.status_code}（{type(exc).__name__}）",
        )
    except APIConnectionError as exc:
        # 只把传输类异常说成不可达：其余异常（探针自身的编程错误）不得被描述成网络问题，
        # 否则会把排查者引向错误方向。
        return ComponentHealth("embedding", Status.UNAVAILABLE, f"{model_name} 嵌入端点不可达（{type(exc).__name__}）")
    except Exception as exc:  # noqa: BLE001 —— 但仍如实说明「这不是可达性结论」
        return ComponentHealth(
            "embedding",
            Status.UNAVAILABLE,
            f"探针自身异常（{type(exc).__name__}），无法判定嵌入端点状态",
        )
    finally:
        # 收口本探针创建的连接（`aclose` 级联关闭注入的 httpx2 客户端，实测）。
        # 关闭失败不得掩盖上面那条结论——探针的返回值已经确定。
        with suppress(Exception):
            await memory_embedder.aclose()

    if len(vector) != EMBEDDING_DIM:
        return ComponentHealth(
            "embedding",
            Status.UNAVAILABLE,
            f"{model_name} 返回 {len(vector)} 维，与常量 EMBEDDING_DIM={EMBEDDING_DIM} 不一致",
        )
    return ComponentHealth("embedding", Status.OK, f"{model_name} 返回 {EMBEDDING_DIM} 维")


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
    与 `/health` 的区别是它必须覆盖核心业务链——尤其是 Agent 装配：
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


#: 深度探针比 readiness 多出来的那一项。单独成一个常量，让「多了什么」一眼可见。
_EMBEDDING_PROBE: tuple[str, Callable[[Settings], Awaitable[ComponentHealth]]] = ("embedding", check_embedding)


def _deep_probes() -> tuple[tuple[str, Callable[[Settings], Awaitable[ComponentHealth]]], ...]:
    """深度探针清单 = `_READINESS_PROBES` **加上**真实嵌入探测。

    **刻意与 `_READINESS_PROBES` 分开**（这是本包的核心决定，不是重复）：
    `check_embedding` 会真的调用供应商、消耗配额，而 `_READINESS_PROBES` 是
    **周期性**判据——生产 healthcheck 每 15 秒跑一次，把它并进去约等于 5760 次/天。
    分开之后，`/readyz` 与 `/health` 的口径逐字未变（仍是那七项、仍全 ok 才 200），
    而真实嵌入探测只在 `/readyz/deep` 这条**按需**路径上发生。

    为什么是函数、**按调用时读取** `_READINESS_PROBES`，而不是在导入期算成一个常量：
    导入期快照会与「运行时被替换过的清单」脱节（`apps/api/tests/test_health.py` 的
    文件头正是为同一个坑写的）。按调用时展开，readiness 清单增删一项时 `/readyz/deep`
    自动跟上，不会静默少探一项。

    同名去重（**先出现者胜**）是刻意的防御：万一有人把 `embedding` 挪进了
    `_READINESS_PROBES`（本包明确不许可的那种改法），这里也不会把它探**两次**
    ——重复探测意味着双倍配额成本，而它正是本包要避免的成本形态。
    """
    seen: set[str] = set()
    probes: list[tuple[str, Callable[[Settings], Awaitable[ComponentHealth]]]] = []
    for name, probe in (*_READINESS_PROBES, _EMBEDDING_PROBE):
        if name in seen:
            continue
        seen.add(name)
        probes.append((name, probe))
    return tuple(probes)


@app.get("/readyz/deep")
async def readyz_deep() -> JSONResponse:
    """深度就绪探针：`/readyz` 的全部项，**外加一次真实的嵌入探测**。

    **⚠ 只供发布验收与人工诊断按需调用，绝不可进入周期性健康检查。**
    本端点会真的调用 TokenHub 的嵌入端点（一次极短输入的请求），因此**有配额成本**：
    按生产 healthcheck 的 15 秒节奏计算约 5760 次/天。Docker healthcheck、Nginx
    upstream 检查与 CD 的发布轮询都**不得**指向这里——它们继续用 `/readyz`。

    为什么需要它：`/readyz` 的 `model` 项只探 chat 端点（`GET /models`）。chat 与
    embedding 是两条独立链路，而「探针只覆盖前者」这一盲区**已真实造成两次**
    「健康检查全绿而业务整体不可用」——最近一次是记忆侧的 embedder 漏传
    `encoding_format`（TokenHub `400001` ⇒ 记忆写入路径整体不可用）。参数的形状
    缺陷 `GET /models` 抓不到，只有真发一次请求才抓得到。

    与 `/readyz` 的关系：判据是「全部项 ok 才 200，否则 503」，与 `/readyz` 同形；
    差别只在组件集合多了 `embedding` 一项。**未登录可达**：它与 `/readyz`、`/health`
    同属运维探针端点（`AC-01` 的「运维探针端点除外」），Nginx 上游检查与人工诊断
    都不持会话。

    安全（AGENTS.md）：只发一条固定字面量（不含任何使用者数据），失败只回报异常类型与
    HTTP 状态码，**不复述连接串、凭据或供应商响应体**。

    Note:
        生产经 Nginx 访问需要额外一条 `location = /readyz/deep`（见
        `infrastructure/docker/app-locations.conf`）。**未配置时该路径会落到 SPA 的
        `location /` 并被 `try_files` 回成 `index.html` ⇒ HTTP 200 + HTML**，
        比 404 更难辨认。这是**已确认的部署前置条件**，不是本端点的实现缺陷。
    """
    settings = get_settings()
    components: tuple[ComponentHealth, ...] = tuple(
        await asyncio.gather(*(probe(settings) for _, probe in _deep_probes()))
    )
    report = HealthReport(components)
    return JSONResponse(
        content=report.as_dict(),
        status_code=200 if report.is_ready else 503,
    )
