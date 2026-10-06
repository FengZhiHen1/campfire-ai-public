"""咨询面的 HTTP 与 SSE 路由。

职责：会话创建、会话列表、历史水合、发消息受理、运行事件流订阅、取消、应急入口与
引导跳过入口八条路径的请求解析、鉴权与归属判定、状态码映射，以及日常会话第一次运行的
引导注入装配。
边界：不做数据读写（经 `modules/*` 与 `core/*`）、不构造运行器（`assembly` 的注入点）、
不管缓冲与互斥的实现（`runbus`）。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 1、2、3、4、5、6、7、8 节；
编排器 T07 裁决 5、6、11，T07b 裁决 6、7、9。

端点顺序即处理顺序（第 2 节的通用约定）：先鉴权（401，由 `require_session` 给出），
再归属判定（404，越权与不存在同文案），最后才是状态判定（409 / 422 / 503）。
顺序不可换：把状态判定提到归属之前，一次对别人会话的请求会因为「那个会话正忙」
而拿到 409——状态码本身就成了会话存在性的旁证。

错误响应形状（本包统一，契约未逐字规定细节）：

401 由 SuperTokens 依赖直接给出；404 与 422 的 `detail` 是一条字符串文案；
409 的 `detail` 是错误码字符串（`session_busy` / `run_not_resumable` / `run_not_running`）；
503 的 `detail` 是「错误码: 说明」。用 `detail` 而不是自定义错误信封，
是为了与 FastAPI 自身的 422（载荷校验）保持同一种可读形状——前端只需读一个字段。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Annotated

from agents.items import TResponseInputItem
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from supertokens_python.recipe.session import SessionContainer

from campfire.agent.context.injection import InjectionBatch, InjectionItem, UnavailableSource
from campfire.agent.runtime import RunRequest
from campfire.agent.skill_runtime import Skill, build_activation_record
from campfire.core.auth.supertokens import require_session
from campfire.core.authz import OBJECT_NOT_ACCESSIBLE_MESSAGE, AuthorizationError, require_writable
from campfire.core.cache import RedisCache, get_cache
from campfire.core.config import Settings, get_settings
from campfire.core.db import session_scope
from campfire.modules.accounts import discard_session_owner
from campfire.modules.accounts.errors import (
    OnboardingTriggerError,
    OnboardingWriteError,
    SessionNotFoundError,
    SessionQueryError,
)
from campfire.modules.accounts.first_run_injection import mark_first_run_injected, read_first_run_injected
from campfire.modules.accounts.onboarding import onboarding_pending as read_onboarding_pending
from campfire.modules.accounts.onboarding import read_onboarding_state, should_inject_onboarding
from campfire.modules.accounts.onboarding_skip import skip_onboarding
from campfire.modules.accounts.onboarding_start import start_onboarding
from campfire.modules.accounts.sessions import (
    list_sessions as list_account_sessions,
)
from campfire.modules.accounts.sessions import (
    load_history,
    register_session,
    require_session_owner,
)
from campfire.modules.memory.derived import EmergencyMemory, read_emergency_facts
from campfire.modules.memory.errors import MemoryModuleError
from campfire.modules.memory.graph import get_shared_memory_graph
from campfire.modules.memory.identity import to_account_id
from campfire.modules.profile import (
    EmergencyContext,
    bind_first_object,
    discard_session_binding,
    emergency_context,
    resolve_default_object,
)
from campfire.surfaces.consult import assembly, runbus
from campfire.surfaces.consult.answers import SendMessageRequest, render_answers
from campfire.surfaces.consult.emergency import EmergencyConsultRequest
from campfire.surfaces.consult.injections import (
    EMERGENCY_MEMORY_SOURCE,
    ONBOARDING_NOTICE_SOURCE,
    build_emergency_injections,
    render_emergency_intake,
    render_onboarding_notice,
)
from campfire.surfaces.consult.object_names import read_object_names
from campfire.surfaces.consult.sse import (
    HEARTBEAT_FRAME,
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_LAST_EVENT_ID,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    TERMINAL_EVENT_TYPES,
    decode_frame,
)

logger = logging.getLogger(__name__)

#: 本面的标识（`RunRequest.surface`，用于按面收窄技能目录）。
SURFACE_NAME = "consult"

#: 未激活任何 skill 时的默认可用工具集（技能设计第 3 节：一期只含只读类）。
#:
#: 文档早已定调而实现此前未接线（授权语义重写时一并补上）：它是「历史激活并集
#: 为空」时的兜底，不是常驻底集——基座 `resolve_scope` 在有激活（含历史推导）时
#: 不再叠加默认集。
DEFAULT_ACTIVE_TOOLS: tuple[str, ...] = ("read_profile_summary", "search_knowledge")

#: 透传给产品侧工具的领域事实的键（`RunRequest.context_payload` → `ToolContext.payload`）。
#:
#: 键的所有者是**装配处**（本模块），不是工具层——`tools/*` 的依赖白名单禁止兄弟工具模块
#: 互相 import（`tests/test_layer_boundaries.py`），因此 `tools/profile.py`、`tools/memory.py`、
#: `tools/onboarding.py`、`tools/emergency_card.py` 各写了一份同值常量，取值一律以本处为准；
#: 五处是否一致由回归测试钉住（漂移的表现是「工具全部回缺少登录账号」）。
#:
#: 为什么必须传（QA-01 的根因）：这四个工具都是**账号级**的（建档、记忆、引导、应急卡），
#: 属主取登录态而不是取参数——参数通道一开，模型就能把数据写到别人名下。登录态进入工具
#: 可见范围的唯一通道就是这个 `payload`；不给它，四个工具一律回「缺少登录账号」。
ACCOUNT_PAYLOAD_KEY = "account_id"


def _tool_context_payload(account_id: str) -> dict[str, str]:
    """构造 `RunRequest.context_payload`：把登录态放进工具可见的领域事实。

    `payload` 的形状由产品侧拥有（基座不解读，见 `agent/tools/spec.py` 的
    `ToolContext.payload`）：本期只需要一个键，值是**登录态的原样字符串**，四个账号级工具
    读的都是它——`profile`（建档）、`memory`（记忆）、`onboarding`（引导）、
    `emergency_card`（应急卡）各有一份 `_account_from`，除 `account_id` 外**不读任何其他键**
    （逐个查过，无第二个必需字段）。

    为什么不做 `to_account_id` 归一化：`profile` 的账号键是列值，判据只是「非空字符串」
    （`tools/profile.py` 的 `_account_from` 已写明不套用记忆侧的字符集规则），记忆侧自己的
    `_account_from` 会做那次转换。在这里预先校验会让一个对档案合法的账号键被记忆侧规则拒掉，
    把两处不同的边界混成一处。`account_id` 的来源是身份服务的用户标识（[认证与账号]第 3 节，
    UUID v4 文本），落库与 Graphiti 图名两侧都已按同一判据收口，因此不需要在这里改写它。

    传的是裸 `str` 而不是对象或元组：四个工具的判据都是 `isinstance(raw, str)`——
    传包装类型会让它们走进「缺少登录账号」分支，与不传同效。
    """
    return {ACCOUNT_PAYLOAD_KEY: account_id}


#: 运行不存在或不属于当前账号的对外文案。与 :data:`SESSION_NOT_FOUND_MESSAGE` 同理：
#: 两种情形共用一条文案，区分二者等于提供运行枚举通道。
RUN_NOT_FOUND_MESSAGE = "运行不存在或不属于当前账号"

#: SSE 流的总时长上界（秒）。与事件缓冲的保留时长同源：缓冲到期后没有任何可续内容，
#: 继续挂着的连接只是占资源。它同时是 CORE-11 要求的显式上界（运行自身另有 180 秒上界，
#: 这里兜的是「运行进程消失、缓冲再也不会新增」的情形）。
STREAM_MAX_SECONDS = float(runbus.RUN_BUFFER_TTL_SECONDS)

#: 缓冲轮询间隔（秒）。为什么是轮询而不是 Redis 订阅：订阅方在断线续传时必须先补发
#: 历史的那些帧，而 pub/sub 不保留它们——两套机制（补历史 + 订阅增量）会让「补完历史」
#: 与「开始订阅」之间出现一个丢事件的窗口。轮询只有一个游标，窗口不存在。
#: 代价是每条事件最多晚 0.2 秒到达（单机 Redis 上一次 LRANGE 是亚毫秒级）。
STREAM_POLL_SECONDS = 0.2

router = APIRouter(prefix="/consult", tags=["consult"])

#: 会话校验依赖。持有工厂返回值本身（而不是每次调用 `require_session()`），
#: 这样测试可以用 `app.dependency_overrides` 按对象身份覆盖它——每次新建一个
#: 依赖函数会让覆盖失效，而那正是端到端用例需要的能力。
_session_dependency = require_session()

SessionDep = Annotated[SessionContainer, Depends(_session_dependency)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class CreateSessionRequest(BaseModel):
    """`POST /consult/sessions` 的请求体（契约 3.1）。"""

    model_config = ConfigDict(extra="forbid")

    support_object_id: str | None = None
    """要绑定的支持对象；省略时按支持对象第 6 节推导默认对象。"""


# ---------------------------------------------------------------------------
# 共享的失败映射
# ---------------------------------------------------------------------------


def _session_not_found() -> HTTPException:
    """会话不可访问 → 404，文案取自 `modules/accounts` 的唯一定义。

    文案从 `SessionNotFoundError.MESSAGE` 取而不是在本层再写一个字面量：
    两处字面量迟早会漂移，而漂移后的「越权与不存在文案不同」正是这条纪律要防的。
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SessionNotFoundError.MESSAGE)


def _run_not_found() -> HTTPException:
    """运行不可访问 → 404（与不存在同文案）。"""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_MESSAGE)


def _busy() -> HTTPException:
    """会话已有在跑的运行 → 409 `session_busy`（契约第 2 节）。"""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=runbus.SESSION_BUSY)


def _not_resumable() -> HTTPException:
    """缓冲已失效且无可续内容 → 409 `run_not_resumable`（契约 4.2）。"""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=runbus.RUN_NOT_RESUMABLE)


def _unprocessable(reason: str) -> HTTPException:
    """载荷或查询参数不合法 → 422。

    状态码用字面量而不是 `status.HTTP_422_UNPROCESSABLE_ENTITY`：新版 Starlette 已把它
    标记为弃用（改名成 `..._CONTENT`），而沿用旧名会在每次调用处打一条弃用警告；
    两条名字都可用期间，字面量是唯一不随版本漂移的写法。
    """
    return HTTPException(status_code=422, detail=reason)


def _unavailable(reason: str) -> HTTPException:
    """依赖不可用 → 503（契约第 2 节的 503 行）。"""
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=reason)


def _not_running() -> HTTPException:
    """取消一个已终结（或本进程已无消费方）的运行 → 409 `run_not_running`（契约 4.3）。"""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=runbus.RUN_NOT_RUNNING)


#: 运行标识的长度上界（CORE-11）。基座生成的是 32 位十六进制，128 对它留有余量；
#: 上界存在的意义是超长路径段不会变成一次超长 Redis 键查询。
MAX_RUN_ID_CHARS = 128


async def _require_run_meta(cache: RedisCache, *, run_id: str, account_id: str) -> runbus.RunMeta:
    """读运行元数据并判定归属；「不可访问」的三种情形共用同一条 404。

    三条路径的顺序就是处理顺序（第 2 节的通用约定）：先按形状拒掉不可能存在的
    标识，再读元数据，最后比归属。长度上界只在这里写一份，订阅端与取消端都
    经它进 Redis——上界的理由（:data:`MAX_RUN_ID_CHARS`）是「超长路径段不会变成
    一次超长 Redis 键查询」，而这个形状的路径段两端一模一样，一处写一处漏就等于
    上界在那一端不存在。

    超长标识按「不存在」处理而不是 422：基座生成的是 32 位十六进制，超长值不可能
    对应任何一次运行；与 :func:`_run_not_found` 同一条文案，不给出一条形状探测通道
    （契约第 2 节的 404 行；422 那一行指的是载荷不合法，而路径段不是载荷）。

    Raises:
        HTTPException: 标识超过 :data:`MAX_RUN_ID_CHARS`、运行不存在，或不属于
            当前账号（三者都是同一个 404 与同一条文案）。
    """
    if len(run_id) > MAX_RUN_ID_CHARS:
        raise _run_not_found()
    meta = await runbus.read_run_meta(cache, run_id=run_id)
    if meta is None or meta.account_id != account_id:
        raise _run_not_found()
    return meta


# ---------------------------------------------------------------------------
# 3.1 创建会话
# ---------------------------------------------------------------------------


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> JSONResponse:
    """建一个日常会话：落归属行、绑定支持对象、判定引导是否待注入（契约 3.1）。

    三件事的顺序有依据：归属行必须先于一切（决策记录的实现约束：不得出现
    「能读但无归属」的会话），绑定只在归属成立之后做，引导判定最后（它是对
    账号状态的读，失败不该让一个已经建好的会话回滚）。

    传入 `support_object_id` 时以 `require_writable` 校验：归档对象不得绑定新会话，
    校验失败是 404。归属不符与已归档共用同一个 404 文案——调用方不需要、也不该
    区分「这个对象不是你的」与「这个对象已归档」。

    省略 `support_object_id` 时按第 6 节推导默认对象；账号一个在用对象都没有时
    返回 `null` 而不是报错（`AC-02`）：此时的正确行为是让引导对话去建第一个对象。

    Raises:
        HTTPException: 传入的支持对象不可写或不属于当前账号（404），
            或会话标识形状不合法（422，理论路径：标识由本层生成），
            或引导状态取值漂移出词表（503，与 `_first_run_injection` 同一处置）。
    """
    account_id = session.get_user_id()
    async with session_scope(settings) as db:
        object_id = payload.support_object_id
        if object_id is not None:
            try:
                await require_writable(account_id, object_id)
            except AuthorizationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=OBJECT_NOT_ACCESSIBLE_MESSAGE,
                ) from exc
        else:
            object_id = await resolve_default_object(db, account_id=account_id)

        session_id = uuid.uuid4().hex
        try:
            await register_session(db, session_id=session_id, account_id=account_id)
        except SessionQueryError as exc:  # pragma: no cover —— 标识由本层生成，形状必然合法
            raise _unprocessable(str(exc)) from exc

        if object_id is not None:
            # 绑定在归属行落定之后：failed 的绑定不该留下一条无归属的会话。
            await bind_first_object(db, session_id=session_id, account_id=account_id, support_object_id=object_id)

        try:
            pending = await read_onboarding_pending(db, account_id=account_id)
        except OnboardingTriggerError as exc:
            # 与 `_first_run_injection` 对同一异常同一处置：状态取值漂移不是使用者的载荷错，
            # 也不是「引导已完成」，回 503（契约第 2 节的 503 行）而不是让未映射异常落成 500。
            raise _unavailable(f"onboarding_state_unreadable: {type(exc).__name__}") from exc

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "session_id": session_id,
            "support_object_id": object_id,
            "onboarding_pending": pending,
        },
    )


# ---------------------------------------------------------------------------
# 3.2 会话列表
# ---------------------------------------------------------------------------


@router.get("/sessions")
async def list_sessions(
    session: SessionDep,
    settings: SettingsDep,
    cursor: str | None = None,
    limit: int | None = None,
) -> JSONResponse:
    """列出该账号的会话（契约 3.2）：按最近活动倒序、游标翻页。

    `limit` 的越界由用例层判定（`validate_limit`）并转成 422：超上界显式拒绝而不是
    截断到 50——调用方无法从响应里看出自己被截断了。

    Raises:
        HTTPException: 游标不可解析或 `limit` 越界（422）。
    """
    account_id = session.get_user_id()
    async with session_scope(settings) as db:

        async def reader(session_ids: Sequence[str]) -> dict[str, str]:
            """对象名取数：绑定与对象名都在 profile 侧（见 `object_names` 的说明）。"""
            return await read_object_names(db, account_id=account_id, session_ids=session_ids)

        try:
            page = await list_account_sessions(
                db,
                account_id=account_id,
                cursor=cursor,
                limit=limit,
                object_name_reader=reader,
            )
        except SessionQueryError as exc:
            raise _unprocessable(str(exc)) from exc

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "items": [
                {
                    "session_id": item.session_id,
                    "title": item.title,
                    "support_object_name": item.support_object_name,
                    "updated_at": item.updated_at.isoformat(),
                    "last_message_preview": item.last_message_preview,
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
        },
    )


# ---------------------------------------------------------------------------
# 3.3 历史水合
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/messages")
async def hydrate_history(session_id: str, session: SessionDep, settings: SettingsDep) -> JSONResponse:
    """水合一条会话的历史（契约 3.3）。

    失败与空对话必须可区分：归属不成立时 404，一条真的没有消息的会话返回
    `messages: []`——契约第 3.3 节明令「不显示空对话冒充成功」，而两者在数据层
    就是不同的结果（用例层的 `load_history` 只在前者抛错）。

    Raises:
        HTTPException: 会话不存在或不属于当前账号（404），或会话标识形状不合法（422）。
    """
    account_id = session.get_user_id()
    async with session_scope(settings) as db:
        try:
            history = await load_history(db, session_id=session_id, account_id=account_id)
        except SessionNotFoundError as exc:
            raise _session_not_found() from exc
        except SessionQueryError as exc:
            raise _unprocessable(str(exc)) from exc

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"session_id": history.session_id, "messages": list(history.messages)},
    )


# ---------------------------------------------------------------------------
# 4.1 发消息（两段式的第一段）
# ---------------------------------------------------------------------------


async def _activated_skill(settings: Settings, skill_name: str | None) -> tuple[Skill, ...]:
    """把技能选择器的选择翻成「程序注入的激活集合」（技能设计第 4 节）。

    `skill` 缺省或为 `null` 表示自动匹配：不注入任何激活集合，由模型侧激活工具
    按描述自行选择（`activated=()`）。给了名字就必须落在合法值域——模型可见
    目录集（`daily-consulting`、`profile-curation`），值域外（含
    `emergency-consulting`、`onboarding` 与未知名）一律 422
    （docs/技术设计/decisions/激活记录即授权真源.md）：

    - 静默忽略会让使用者以为自己选中的技能起了作用，而运行其实跑在自动模式上；
    - 应急与引导是 `autoload: "false"` 的程序注入技能，经此参数手选等于绕过
      它们的触发条件（入口唯一性）。

    「发送即消费」（契约 4.1）说的是选择器 UI 与本次激活，不是授权：激活记录
    落会话历史后授权跨运行持续（见 `send_message` 的装配）。
    """
    if skill_name is None:
        return ()
    try:
        registry = assembly.get_skill_registry(settings)
    except assembly.ConsultAssemblyError as exc:
        raise _unavailable(str(exc)) from exc
    selectable = {skill.name for skill in registry.activation_candidates()}
    if skill_name not in selectable:
        raise _unprocessable(
            f"技能 {skill_name} 不可手选：可选值为 {sorted(selectable)}（应急与引导由入口触发，不经选择器）"
        )
    return (registry.get(skill_name),)


def _program_skill(settings: Settings, name: str) -> Skill:
    """取一个由程序注入的技能（应急入口与引导注入用它）。

    与 :func:`_activated_skill` 的区别是失败方向：那个是使用者给了名字（名字不在值域里
    是载荷不合法，422），这里是服务端自己要用的技能（内容根目录里没有它属于装配不完整，
    503）——回 422 会把一个部署缺陷说成使用者的错。

    Raises:
        HTTPException: 技能注册表不可用，或目录里没有该技能（503）。
    """
    try:
        registry = assembly.get_skill_registry(settings)
    except assembly.ConsultAssemblyError as exc:
        raise _unavailable(f"skill_registry_unavailable: {type(exc).__name__}") from exc
    if name not in registry.names():
        raise _unavailable(f"skill_missing: 内容目录里没有技能 {name}")
    return registry.get(name)


def _activation_records(skills: tuple[Skill, ...]) -> tuple[TResponseInputItem, ...]:
    """把本轮程序注入的激活集合翻成合成激活记录对（授权真源的写入端）。

    依据 docs/技术设计/decisions/激活记录即授权真源.md：激活记录落会话历史，
    授权跨运行、只增不减。手选与程序注入（引导/应急）都经这里；记录对由
    `build_activation_record` 合成，与模型侧 `skill` 工具的真实调用同形。
    """
    records: list[TResponseInputItem] = []
    for index, skill in enumerate(skills, start=1):
        call, output = build_activation_record(skill, call_id=f"app-activate-{index}")
        # 类型逃逸与 runner._as_items 同理：`Item` 是 Mapping[str, object]，SDK 的输入项
        # 是 TypedDict 联合——静态类型看不穿这层「运行时形状一致」，显式转一次。
        records.append(dict(call))  # type: ignore[arg-type]  # 运行时形状与 SDK 的 function_call 条目一致
        records.append(dict(output))  # type: ignore[arg-type]  # 同上
    return tuple(records)


@dataclass(frozen=True, slots=True)
class _OnboardingInjection:
    """日常会话第一次运行要程序注入的引导内容（技能 + 一条静态告知消息）。"""

    skill: Skill
    notice: InjectionItem


async def _first_run_injection(
    settings: Settings,
    *,
    session_id: str,
    account_id: str,
) -> _OnboardingInjection | None:
    """判定本次运行要不要注入引导；要，就把注入内容准备好（契约 3.1）。

    两个判据缺一不可：

    - 这个会话的第一次运行（`campfire_session.first_run_injected` 为假）；
    - 该账号的引导未终结（`campfire_onboarding` 无行或 `in_progress`）。

    第二条在这里重读，不复用会话创建时算出的 `onboarding_pending`：那个值只对创建
    那一刻成立，而第一次运行可能发生在很久之后——期间使用者在另一个会话里跳过了引导
    或走完了它。按旧值注入，是在用户已经明确结束引导之后再塞一段引导。

    两次读表在同一事务里，且都在归属判定之后、占位之前：判定本身没有副作用
    （注入的记账在运行起步成功后才写，见 :func:`_settle_first_run`），因此这里
    失败不需要回滚任何东西。

    Raises:
        HTTPException: 会话归属行消失（404，理论路径）、引导状态取值漂移（503）、
            或技能内容缺失（503）。
    """
    async with session_scope(settings) as db:
        try:
            settled = await read_first_run_injected(db, session_id=session_id)
        except SessionNotFoundError as exc:
            # 上方刚判定过归属；走到这里说明行在两次查询之间消失了（并发注销）。
            raise _session_not_found() from exc
        except SessionQueryError as exc:
            raise _unprocessable(str(exc)) from exc
        if settled:
            return None
        try:
            state = await read_onboarding_state(db, account_id=account_id)
            # 判定复用 `modules/accounts` 的纯函数，不在面层重写词表语义。
            if not should_inject_onboarding(state):
                return None
        except OnboardingTriggerError as exc:
            # 状态取值漂移：注入与不注入都会掩盖漂移，因此本次运行明确失败（`CORE-07`）。
            raise _unavailable(f"onboarding_state_unreadable: {type(exc).__name__}") from exc

    return _OnboardingInjection(skill=_program_skill(settings, assembly.ONBOARDING_SKILL_NAME), notice=_notice_item())


def _notice_item() -> InjectionItem:
    """把静态告知包成一条注入项。

    角色取 `assistant` 而不是默认的 `user`：这条告知必须让使用者真的读到，而
    `user` 角色的注入会被水合与标题推导当成机器上下文跳过（前缀在
    `session_items.INJECTED_MESSAGE_PREFIXES` 里就进不了历史）。取 `assistant` 之后
    它落在会话真源里就是首条助手消息——水合按原样呈现，模型也把它当成自己说过的话，
    于是「回执不重复念一遍告知全文」这条纪律由形状本身保证
    （`telling-first.md` 第 2、5 节）。

    代价如实写明：前端若为告知设计了专门的呈现组件，需要按 `assistant` 消息处理；
    当前页面设计文档里没有这一条，已登记到报告「未决问题」。
    """
    return InjectionItem(
        source=ONBOARDING_NOTICE_SOURCE,
        content=render_onboarding_notice(),
        role="assistant",
    )


async def _settle_first_run(settings: Settings, *, session_id: str, account_id: str) -> None:
    """结算这次首轮注入：置会话标记 + 落账号的引导开始状态（首次触发时）。

    在运行起步成功之后调用、且只记日志不抛错：此时 `run_id` 已经回给前端，
    任何异常都无法再改变这个事实——把它抛出去只会让 202 变成一个假的失败
    （调用方以为没起运行，于是重发，而会话位与幂等键都已被这次运行占着）。
    失败的后果是下次运行可能重复注入一次引导（技能设计第 4 节接受这个代价：
    漏注入不可恢复，重复注入只是多一段可跳过的引导），记警告供排查。

    两件事写在同一个事务里：它们同属「这次注入结算了」这一个事实的两个视角
    （会话侧：本会话不必再注入；账号侧：引导已开始）。分开提交会让一个成立而另一个
    不成立，而两种半成品都会让后续判定做出错误结论。
    """
    try:
        async with session_scope(settings) as db:
            await mark_first_run_injected(db, session_id=session_id)
            await start_onboarding(db, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 —— 运行已起步，这里再抛错只会伪造一次失败
        logger.warning(
            "首轮注入结算失败：会话=%s 异常=%s",
            session_id,
            type(exc).__name__,
        )


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(
    session_id: str,
    payload: SendMessageRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> JSONResponse:
    """受理一条使用者消息并启动一次运行（契约 4.1）。

    202 只表示已受理：使用者消息此时尚未落库（它由基座在运行时写入会话真源），
    因此响应里只有 `run_id` 与 `session_id`，没有任何「消息已保存」的承诺。

    从校验到启动的顺序，每一步的理由：

    1. 归属判定先于幂等与互斥——对别人的会话，任何状态码都不该泄露它是否正忙；
    2. 首轮引导判定（契约 3.1）在读幂等、占位与技能校验之前：它只读表、没有副作用，
       因此后面每一条提前返回的路径（幂等命中、互斥被拒、起步失败）都不必为它做清理；
    3. 技能校验先于任何状态写入——一个未知技能名的请求不该占住会话位再回滚。
       唯一的例外是首次运行：那一次 `skill` 参数被忽略（契约 4.1），因此先用不上的
       名字把整次运行拒掉（422）是错的——校验排在首轮判定之后就是为这一条；
    4. 幂等命中直接返回原 `run_id`，不碰会话位、也不追加消息；
    5. 互斥失败回 409 且不追加消息（契约第 2 节与质量地板 ③）；
    6. 命中首轮引导时，本次运行的程序注入集合被引导替换（技能与静态告知），
       使用者给的 `skill` 选择被忽略——那一次是引导，不是他选的那件事；
       记账（会话标记 + 账号引导开始）在运行起步成功之后才写；
    7. 启动失败（首个事件不是 `run_started`）时释放占位并回 503——此时没有
       `run_id`，回 202 会让前端订阅一个不存在的路径；首轮记账不写，下次运行仍会注入。

    Raises:
        HTTPException: 会话不可访问（404）、载荷不合法或非首次运行的技能未知（422）、
            会话已有在跑的运行（409），或运行器未装配、运行未能启动、
            引导状态取值漂移（503）。
    """
    account_id = session.get_user_id()

    async with session_scope(settings) as db:
        try:
            await require_session_owner(db, session_id=session_id, account_id=account_id)
        except SessionNotFoundError as exc:
            raise _session_not_found() from exc
        except SessionQueryError as exc:
            raise _unprocessable(str(exc)) from exc

    try:
        runner = assembly.get_runner(settings)
    except assembly.ConsultAssemblyError as exc:
        raise _unavailable(str(exc)) from exc

    cache = get_cache(settings)
    client_message_id = payload.client_message_id

    # 首轮引导判定在读幂等、占位与技能校验之前：它没有副作用（记账在运行起步成功后才写），
    # 因此幂等命中与互斥被拒这两条路径都不必为它做任何清理。
    onboarding = await _first_run_injection(settings, session_id=session_id, account_id=account_id)

    # 首次运行忽略 `skill`（契约 4.1）：本次运行的程序注入集合整份被引导替换，使用者的
    # 选择不会被消费，所以这里不校验它——先校验后忽略会让一个用不上的名字拒掉整次运行。
    # 非首次运行照旧校验（未知技能名 422）。
    activated = () if onboarding is not None else await _activated_skill(settings, payload.skill)

    settled = await runbus.read_idempotent_run_id(cache, session_id=session_id, client_message_id=client_message_id)
    if settled is not None:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"run_id": settled, "session_id": session_id},
        )

    if not await runbus.reserve_idempotency(cache, session_id=session_id, client_message_id=client_message_id):
        # 同一个幂等键的另一个请求正在跑（值还是占位）。它有没有结论取决于那个请求
        # 会不会成功，等待没有上界，因此按「会话忙」处理；前端重试会拿到结论或再被拒。
        raise _busy()

    lease = await runbus.claim_session_run(cache, session_id=session_id)
    if lease is None:
        await runbus.drop_idempotency(cache, session_id=session_id, client_message_id=client_message_id)
        raise _busy()

    user_input = (
        render_answers(payload.answers, batch_id=payload.resolve_batch_id())
        if payload.answers is not None
        else (payload.content or "")
    )
    activated_record: tuple[TResponseInputItem, ...] = ()
    if onboarding is not None:
        # 引导注入整份替换这次运行的技能集合：这一次是引导，不是日常咨询。集合与注入项
        # 在同一支里一起定，避免「注入了引导但技能集合还是用户选的那个」这种半注入状态
        # ——那会让模型同时拿到两套互相冲突的操作纪律（上面的 activated 初值因此是空的）。
        activated = (onboarding.skill,)
        injections = InjectionBatch(items=(onboarding.notice,))
        activated_record = _activation_records(activated)
    else:
        injections = InjectionBatch()
        activated_record = _activation_records(activated)
    request = RunRequest(
        session_id=session_id,
        surface=SURFACE_NAME,
        instructions=assembly.CONSULT_INSTRUCTIONS,
        injections=injections,
        user_input=user_input,
        activated=activated,
        activated_record=activated_record,
        default_active_tools=DEFAULT_ACTIVE_TOOLS,
        # 登录态进工具可见通道：这一轮激活的引导 skill 会调 create_support_object /
        # write_memory / finish_onboarding，三者都按账号归属取数；不给 payload 就是 QA-01
        # 的建档失败（工具回「缺少登录账号」）与引导无法收束。
        context_payload=_tool_context_payload(account_id),
    )
    pump = runbus.RunPump(
        cache=cache,
        runner=runner,
        request=request,
        account_id=account_id,
        lease=lease,
    )
    try:
        run_id = await pump.begin()
    except runbus.RunStartupFailure as exc:
        await runbus.release_session_run(cache, lease)
        await runbus.drop_idempotency(cache, session_id=session_id, client_message_id=client_message_id)
        raise _unavailable(f"{exc.code}: {exc.detail}") from exc

    if onboarding is not None:
        # 记账放在起步成功之后：起步失败时这次注入没有发生过，标记不该被消耗掉。
        await _settle_first_run(settings, session_id=session_id, account_id=account_id)

    await runbus.commit_idempotency(
        cache,
        session_id=session_id,
        client_message_id=client_message_id,
        run_id=run_id,
    )
    runbus.start_pump(pump)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"run_id": run_id, "session_id": session_id},
    )


# ---------------------------------------------------------------------------
# 4.2 订阅事件流（两段式的第二段）
# ---------------------------------------------------------------------------


def parse_last_event_id(raw: str | None) -> int:
    """解析 `Last-Event-ID` 头；缺省为 0（从头开始）。

    Raises:
        HTTPException: 非整数、负数，或超过 :data:`MAX_LAST_EVENT_ID`。都是 422：
            这个头是客户端的续传凭据，不是业务载荷，一个不合法的值只可能是
            客户端实现有误或有人在伪造。
    """
    if raw is None or raw == "":
        return 0
    try:
        value = int(raw)
    except ValueError as exc:
        raise _unprocessable("Last-Event-ID 必须是整数") from exc
    if value < 0:
        raise _unprocessable("Last-Event-ID 不能为负")
    if value > MAX_LAST_EVENT_ID:
        raise _unprocessable("Last-Event-ID 超出上界")
    return value


async def _stream_frames(
    cache: RedisCache,
    *,
    run_id: str,
    after_seq: int,
) -> AsyncIterator[str]:
    """按序产出 SSE 帧：先补缓冲里的，再跟新增的；空闲时心跳。

    三类结束条件，都不静默：

    - 送出终态事件（`run_finished` / `run_failed`）——契约 4.2 的「终态后关流」；
    - 运行已终结且缓冲里没有更新的事件——客户端已拿到全部内容；
    - 缓冲到期（元数据消失）——此时没有任何可续内容；响应已经开始，
      无法再回 409（那个判定发生在响应头之前），因此如实关流，由前端按第 8 节
      的「重连耗尽」走历史水合。

    时间上界见 :data:`STREAM_MAX_SECONDS`。
    """
    cursor = after_seq
    deadline = time.monotonic() + STREAM_MAX_SECONDS
    last_heartbeat = time.monotonic()
    terminal_seen = False

    while not terminal_seen:
        frames = await runbus.read_events_after(cache, run_id=run_id, after_seq=cursor)
        for seq, raw in frames:
            cursor = max(cursor, seq)
            yield raw
            # 这里不再捕获解析异常：能读出来的帧都已经过 read_events_after 的解析过滤
            # （被截断的超长帧在那里就被丢弃并记了日志），所以这一段拿到的原文必然是
            # 本模块编码出的完整帧。真出现解析失败就是编解码分叉，那要显式暴露，
            # 而不是在流里静默略过——静默正是「半截 JSON 被送出去」的成因。
            _seq, name = decode_frame(raw)
            if name in TERMINAL_EVENT_TYPES:
                terminal_seen = True
                break

        if terminal_seen:
            return

        if not frames:
            meta = await runbus.read_run_meta(cache, run_id=run_id)
            if meta is None:
                logger.info("事件缓冲已到期，订阅结束：运行=%s", run_id)
                return
            if meta.status == runbus.RUN_STATUS_FINISHED:
                return

        now = time.monotonic()
        if now > deadline:
            logger.info("订阅达到时长上界，主动关流：运行=%s", run_id)
            return
        if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            last_heartbeat = now
            yield HEARTBEAT_FRAME
        await asyncio.sleep(STREAM_POLL_SECONDS)


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    session: SessionDep,
    settings: SettingsDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """订阅一次运行的事件流（契约 4.2）：三行帧 + 续传 + 心跳。

    顺序仍然是「先鉴权、再归属、最后状态」：运行元数据里带账号标识，因此归属判定
    不需要解析事件正文。运行不存在与非本账号返回同一个 404（与 :func:`_run_not_found`
    的说明一致）。

    缓冲不存在的语义是「已经没有任何可续内容」（TTL 到期），回 409
    `run_not_resumable`，前端据此改走历史水合（契约第 8 节）。运行已终结但缓冲
    还在时不回 409——缓冲里的事件照发，发完关流。

    Raises:
        HTTPException: 运行不存在或不属于当前账号（404）、缓冲已失效（409），
            或 `Last-Event-ID` 不可解析（422）。
    """
    account_id = session.get_user_id()
    after_seq = parse_last_event_id(last_event_id)

    cache = get_cache(settings)
    await _require_run_meta(cache, run_id=run_id, account_id=account_id)
    if not await cache.exists(runbus.events_key(run_id)):
        raise _not_resumable()

    return StreamingResponse(
        _stream_frames(cache, run_id=run_id, after_seq=after_seq),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


# ---------------------------------------------------------------------------
# 4.3 取消
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: str, session: SessionDep, settings: SettingsDep) -> JSONResponse:
    """取消一次运行（契约 4.3）：停掉本进程里这条运行的消费方，不发终态事件。

    顺序仍是「先鉴权、再归属、最后状态」：运行元数据里带账号标识，因此归属判定不需要
    碰事件缓冲。运行不存在与非本账号返回同一个 404。

    三条约定在这里的落法：

    - 已终结的运行 → 409 `run_not_running`（契约 4.3 只写了状态码，错误码是本面补的，
      见 `runbus.RUN_NOT_RUNNING` 的说明）。先读元数据判状态、再去取消，而不是直接取消：
      直接取消时「没有可取消的任务」既可能是「已经跑完」也可能是「运行在别的进程」，
      两者都回 409，但只有读元数据之后才能确定前者的判据成立。
    - 取消不发终态事件（基座第 9 节）：取消的是消费方任务，基座随之停掉 SDK 侧的
      运行并把 `CancelledError` 抛出去，因此不会有人再产出 `run_finished`。
      前端据此自行把已渲染的部分标为「本次回答中断」（契约 4.3）。
    - 收尾（落终结状态、释放会话位）由推进任务的 `finally` 完成，故本端点返回 202 之后
      这个会话马上就能再发消息——不必等 TTL。

    Raises:
        HTTPException: 运行不存在或不属于当前账号（404），或运行已不在跑（409）。
    """
    account_id = session.get_user_id()
    cache = get_cache(settings)
    meta = await _require_run_meta(cache, run_id=run_id, account_id=account_id)
    if meta.status == runbus.RUN_STATUS_FINISHED:
        raise _not_running()
    if not runbus.request_cancel(run_id):
        # 元数据说在跑，而本进程里没有它的消费方：已终结的收尾还没落状态，或运行不在
        # 本进程（多进程部署）。两种情况都无法完成取消，如实回 409 而不是回一个
        # 「已受理」的 202——后者会让前端以为停止按钮生效了。
        raise _not_running()

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"run_id": run_id, "cancelled": True},
    )


# ---------------------------------------------------------------------------
# 5 应急入口
# ---------------------------------------------------------------------------


@router.post("/emergency", status_code=status.HTTP_202_ACCEPTED)
async def start_emergency(
    payload: EmergencyConsultRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> JSONResponse:
    """一次调用完成「建会话 → 落第一条消息 → 启动运行」（契约第 5 节）。

    顺序按第 2 节的通用约定排：鉴权（401，依赖给出）→ 归属（404）→ 装配与状态
    （503）→ 写入。因此下面的取技能与取运行器放在归属判定之后、任何写入之前：

    - 放在归属之后：对别人的对象，任何状态码都不该泄露它的存在性——先取装配会让
      一次越权请求拿到 503 而不是 404，状态码本身就成了旁证（与 `send_message`
      的「归属判定先于幂等与互斥」同一条纪律）；
    - 放在写入之前：技能内容或运行器缺失时这次请求根本跑不起来，先把会话建出来会留下
      一个再也跑不起来的空会话（前端重试还会不断堆积）。

    随后五件事的顺序与理由：

    1. 解析支持对象：传入时以 `require_writable` 校验（归档对象不得绑定新会话，
       越权与不存在共用同一条 404 文案），省略时按支持对象第 6 节推导默认对象；
    2. 一个事务里落归属行、绑定支持对象、把首轮注入标记置真：三者同属「这个应急会话
       建好了」。标记置真是必要的——应急会话永不触发引导（`RQ-EMG-03`），
       而它后续的消息走 `send_message`，那里的判据正是这个标记；
    3. 同一个事务里取档案（`emergency_context`，键是支持对象）与记忆
       （`read_emergency_facts`，键是账号）——两条取数的分区键不同，不可混用；
       记忆取数失败时不构造空记忆（那等于宣称「这个账号没有记忆」），
       而是记一条来源不可用，由基座显式告知模型；
    4. 八项渲染成第一条使用者消息（缺项写「未采集（未排除）」），档案与记忆作为注入
       排在它前面——注入消息由基座追加在末尾，顺序即「档案 → 记忆 → 使用者输入」；
    5. 会话位与新会话不可能冲突（标识刚生成），但仍按同一形状占位并启动；
       起步失败时先补偿删除这次建的会话行与绑定、再释放占位，然后回 503
       （没有 `run_id` 就没有可订阅的路径）——那三行已经提交，而调用方拿不到
       `session_id`，不补偿就是一个永远不可达的会话（理由见
       :func:`_discard_emergency_session`）。

    越权与不存在的文案统一：传入的支持对象不可写或不属于当前账号时 404，
    与「支持对象不存在」同一条文案（`OBJECT_NOT_ACCESSIBLE_MESSAGE`）。

    Raises:
        HTTPException: 传入的支持对象不可访问（404）、载荷不合法（422），
            或技能/运行器/依赖不可用（503）。
    """
    account_id = session.get_user_id()
    session_id = uuid.uuid4().hex
    unavailable: list[UnavailableSource] = []
    async with session_scope(settings) as db:
        object_id = payload.support_object_id
        if object_id is not None:
            try:
                await require_writable(account_id, object_id)
            except AuthorizationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=OBJECT_NOT_ACCESSIBLE_MESSAGE,
                ) from exc
        else:
            object_id = await resolve_default_object(db, account_id=account_id)

        # 归属已成立、且到这里还没有写过一个字节：装配缺失只回 503，不留会话。
        skill = _program_skill(settings, assembly.EMERGENCY_SKILL_NAME)
        try:
            runner = assembly.get_runner(settings)
        except assembly.ConsultAssemblyError as exc:
            raise _unavailable(str(exc)) from exc

        try:
            await register_session(db, session_id=session_id, account_id=account_id)
        except SessionQueryError as exc:  # pragma: no cover —— 标识由本层生成，形状必然合法
            raise _unprocessable(str(exc)) from exc
        if object_id is not None:
            await bind_first_object(db, session_id=session_id, account_id=account_id, support_object_id=object_id)
        try:
            await mark_first_run_injected(db, session_id=session_id)
        except SessionNotFoundError as exc:  # pragma: no cover —— 归属行刚在同一个事务里插入
            raise _session_not_found() from exc

        profile = await _read_emergency_profile(db, account_id=account_id, support_object_id=object_id)
        memory = await _read_emergency_memory(db, account_id=account_id, unavailable=unavailable)

    cache = get_cache(settings)
    lease = await runbus.claim_session_run(cache, session_id=session_id)
    if lease is None:  # pragma: no cover —— 标识刚生成，不可能已有运行占位
        raise _busy()

    batch = build_emergency_injections(profile=profile, memory=memory, unavailable=unavailable)
    request = RunRequest(
        session_id=session_id,
        surface=SURFACE_NAME,
        instructions=assembly.CONSULT_INSTRUCTIONS,
        injections=batch,
        user_input=render_emergency_intake(payload.items),
        activated=(skill,),
        activated_record=_activation_records((skill,)),
        # 同一个根因的第二个落点，必须一起修：应急 skill 的输出工具
        # `emit_emergency_action_card` 与日常侧那三个工具一样按登录态取账号
        # （`tools/emergency_card.py` 的 `_account_from` 读同一个键）。只改 `send_message`
        # 会留下「日常咨询能用、应急咨询发不出行动卡」的半修——而应急卡是本 skill 唯一的
        # 结构化输出通道，缺 payload 的表现是「卡发不出去」而不是任何可见的装配错误。
        context_payload=_tool_context_payload(account_id),
    )
    pump = runbus.RunPump(
        cache=cache,
        runner=runner,
        request=request,
        account_id=account_id,
        lease=lease,
    )
    try:
        run_id = await pump.begin()
    except runbus.RunStartupFailure as exc:
        # 补偿先于释放占位：先清掉不可逆的业务行（会话行一旦留下就永久不可达，
        # 而占位键有 TTL、释放失败只会晚一点过期）；反过来时一次 Redis 抖动
        # 会让补偿被整段跳过。
        await _discard_emergency_session(settings, session_id=session_id)
        await runbus.release_session_run(cache, lease)
        raise _unavailable(f"{exc.code}: {exc.detail}") from exc

    runbus.start_pump(pump)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"session_id": session_id, "run_id": run_id},
    )


async def _discard_emergency_session(settings: Settings, *, session_id: str) -> None:
    """补偿删除应急入口在运行起步失败时留下的会话行与绑定。

    为什么必须补偿：归属行、绑定与首轮注入标记在 `pump.begin()` 之前就已提交，而起步
    失败时调用方拿不到 `session_id`——这个会话没有任何入口可达。留下的后果都不是残留级别：

    - 标记已为真，而它是本面判定「该会话是否已注入引导」的依据，账号侧的引导状态
      又由该账号「是否已开始引导」共同决定，于是使用者下一次的日常消息会被判成
      「已注入」而跳过引导告知——O-4 要保证的那次告知他永远看不到；
    - 绑定行会参与 `resolve_default_object` 的推导（`bound_at` 最大的绑定），
      一个不存在的会话决定该账号下一次新建会话绑哪个对象；
    - 前端按契约第 2 节对 503 重试，每次重试再堆一条，且这些会话会以空标题出现在
      `GET /consult/sessions` 里。

    为什么不在原事务里回滚：写入与起步分属两个事务——起步要在 Redis 上占会话位、
    还要真的驱动运行器产出首个事件，跨事务的原子性在这里拿不到，只能事后补偿。

    为什么只删业务侧两行、不动 SDK 的会话真源：那两张表的内容由 SDK 拥有
    （`SessionAccountPurger` 同一条口径），且本例的失败码本就是「会话真源不可用」；
    归属行一旦删除，那里的残留已不可达（水合与列表都以归属行为准）。

    补偿本身失败只记警告、不抛：503 已经注定要回给前端，把它换成另一个失败对调用方
    没有任何好处，而残留会真实发生——因此日志带上会话标识，供人工清理。
    """
    try:
        async with session_scope(settings) as db:
            # 先删子行（绑定）再删归属行：两行没有外键，删的顺序不影响结果，
            # 但读代码的人不该去推「先删哪一行才对」。
            await discard_session_binding(db, session_id=session_id)
            await discard_session_owner(db, session_id=session_id)
    except Exception as exc:  # noqa: BLE001 —— 503 必须照回，删不掉只记日志供人工清理
        logger.warning("应急会话补偿删除失败：会话=%s 异常=%s", session_id, type(exc).__name__)


async def _read_emergency_profile(
    db: AsyncSession,
    *,
    account_id: str,
    support_object_id: str | None,
) -> EmergencyContext | None:
    """取应急档案预取；账号没有支持对象时返回 `None`（`AC-02`，不是错误）。

    `emergency_context` 内部自带属主校验（`require_owned`），校验失败会抛
    `AuthorizationError`——本函数把它翻成与「对象不存在」相同的 404 文案：
    调用方不需要、也不该区分这两件事（支持对象第 5.3 节）。
    """
    if support_object_id is None:
        return None
    try:
        return await emergency_context(db, account_id=account_id, support_object_id=support_object_id)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=OBJECT_NOT_ACCESSIBLE_MESSAGE,
        ) from exc


async def _read_emergency_memory(
    db: AsyncSession,
    *,
    account_id: str,
    unavailable: list[UnavailableSource],
) -> EmergencyMemory | None:
    """取应急记忆预取；取数失败时登记来源不可用并返回 `None`。

    为什么失败时不返回空的 `EmergencyMemory`：空结果在注入里渲染成
    「该账号还没有可用记忆」——那是一句关于数据的事实陈述，而这里的事实是
    「取数失败」。两者混同会让模型在缺数据时以为自己知道全部
    （通用记忆第 6 节：图库不可用必须与没有记忆严格区分）。

    `MemoryModuleError` 是记忆模块全部失败的基类：图库不可用与取回数据不合法
    都在其中，两者对模型的处置相同（这份来源本次不可用），因此合并处理。

    `account_id` 来自登录态，是裸 `str`，而取数的分区键要求 `AccountId`。此前裸 `str`
    直接穿过函数边界，校验实际由 `read_emergency_facts` 内部的 `deleted_episode_keys`
    代做（那里抛 `AccountIdError`，是 `MemoryModuleError` 的子类，被同一个 `except`
    收口）。这里在边界处显式构造 `AccountId`，并且与取图库句柄的先后顺序保持原样
    （先取句柄、再校验账号）：两句都只抛 `MemoryModuleError` 子类，顺序只影响
    `reason` 记下哪个异常类型，保持原序即保持这一处诊断不变。转换一旦提到 `try`
    之外，非法账号标识就会变成未捕获异常（500），那是对外行为的变化。
    """
    try:
        graph = get_shared_memory_graph()
        account = to_account_id(account_id)
        return await read_emergency_facts(db, graph, account)
    except MemoryModuleError as exc:
        unavailable.append(UnavailableSource(source=EMERGENCY_MEMORY_SOURCE, reason=type(exc).__name__))
        return None


# ---------------------------------------------------------------------------
# 6 引导跳过入口
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/onboarding/skip")
async def skip_session_onboarding(
    session_id: str,
    session: SessionDep,
    settings: SettingsDep,
) -> JSONResponse:
    """把该会话所属账号的引导状态置为 `skipped`（契约第 6 节）。

    幂等：已是 `skipped` 或 `completed` 时同样 200，返回当前状态而不是一律回
    `skipped`——后者在已 `completed` 的账号上会陈述一个存储层并不成立的事实。
    两条写通道互不代写（认证与账号第 8 节）：本端点不覆盖 `completed`，
    `finish_onboarding` 也不覆盖 `skipped`。

    路径上带 `session_id` 而状态是账号级的：会话标识是归属凭据——先按它判定
    「这个会话是不是你的」（不是则 404，与不存在同文案），再写该账号的状态。
    没有这一步，任何登录账号都能改别人的引导状态。

    本端点只写状态，不取消正在跑的运行：跳过引导对话的中途退出是另一件事，
    按契约 4.3 走取消端点（第 6 节末行）。

    Raises:
        HTTPException: 会话不存在或不属于当前账号（404），或引导状态写入失败（503）。
    """
    account_id = session.get_user_id()
    async with session_scope(settings) as db:
        try:
            await require_session_owner(db, session_id=session_id, account_id=account_id)
        except SessionNotFoundError as exc:
            raise _session_not_found() from exc
        except SessionQueryError as exc:
            raise _unprocessable(str(exc)) from exc

        try:
            state = await skip_onboarding(db, account_id=account_id)
        except OnboardingWriteError as exc:
            # 写入失败明确回 503：不得回执 skipped——那会让前端以为使用者的跳过已生效，
            # 而下次会话仍会注入引导（`finish_onboarding` 契约第 5 节末行的补救通道，
            # 在这里就是「再点一次」，本端点是幂等的）。
            raise _unavailable(f"onboarding_write_failed: {type(exc).__name__}") from exc

    return JSONResponse(status_code=status.HTTP_200_OK, content={"state": state})


__all__ = [
    "MAX_RUN_ID_CHARS",
    "RUN_NOT_FOUND_MESSAGE",
    "STREAM_MAX_SECONDS",
    "STREAM_POLL_SECONDS",
    "SURFACE_NAME",
    "cancel_run",
    "create_session",
    "hydrate_history",
    "list_sessions",
    "parse_last_event_id",
    "router",
    "send_message",
    "skip_session_onboarding",
    "start_emergency",
    "stream_run",
]
