"""咨询面的 HTTP 与 SSE 路由。

职责：会话创建、会话列表、历史水合、发消息受理、运行事件流订阅五条路径的
请求解析、鉴权与归属判定、状态码映射。
边界：不做数据读写（经 `modules/*` 与 `core/*`）、不构造运行器（`assembly` 的注入点）、
不管缓冲与互斥的实现（`runbus`）。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 1、2、3、4、7、8 节；
编排器 T07 裁决 5、6。

端点顺序即处理顺序（第 2 节的通用约定）：先鉴权（401，由 `require_session` 给出），
再归属判定（404，越权与不存在同文案），最后才是状态判定（409 / 422 / 503）。
顺序不可换：把状态判定提到归属之前，一次对别人会话的请求会因为「那个会话正忙」
而拿到 409——状态码本身就成了会话存在性的旁证。

错误响应形状（本包统一，契约未逐字规定细节）：

401 由 SuperTokens 依赖直接给出；404 与 422 的 `detail` 是一条字符串文案；
409 的 `detail` 是错误码字符串（`session_busy` / `run_not_resumable`）；
503 的 `detail` 是「错误码: 说明」。用 `detail` 而不是自定义错误信封，
是为了与 FastAPI 自身的 422（载荷校验）保持同一种可读形状——前端只需读一个字段。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from supertokens_python.recipe.session import SessionContainer

from campfire.agent.runtime import RunRequest
from campfire.agent.skill_runtime import Skill
from campfire.core.auth.supertokens import require_session
from campfire.core.authz import OBJECT_NOT_ACCESSIBLE_MESSAGE, AuthorizationError, require_writable
from campfire.core.cache import RedisCache, get_cache
from campfire.core.config import Settings, get_settings
from campfire.core.db import session_scope
from campfire.modules.accounts.errors import SessionNotFoundError, SessionQueryError
from campfire.modules.accounts.onboarding import onboarding_pending as read_onboarding_pending
from campfire.modules.accounts.sessions import (
    list_sessions as list_account_sessions,
)
from campfire.modules.accounts.sessions import (
    load_history,
    register_session,
    require_session_owner,
)
from campfire.modules.profile import bind_first_object, resolve_default_object
from campfire.surfaces.consult import assembly, runbus
from campfire.surfaces.consult.answers import SendMessageRequest, render_answers
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
            或会话标识形状不合法（422，理论路径：标识由本层生成）。
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

        pending = await read_onboarding_pending(db, account_id=account_id)

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
    """把技能选择器的选择翻成「程序注入的激活集合」（裁决 11、技能设计第 4 节）。

    `skill` 缺省或为 `null` 表示自动匹配：不注入任何激活集合，由模型侧激活工具
    按描述自行选择（`activated=()`）。给了名字就必须是已注册的技能，未知值 422
    ——静默忽略会让使用者以为自己选中的技能起了作用，而运行其实跑在自动模式上。

    「发送即消费」（契约 4.1）由本函数的形状保证：它只在本次请求里生效，
    不写任何持久状态，因此下一次发消息默认回到自动。
    """
    if skill_name is None:
        return ()
    try:
        registry = assembly.get_skill_registry(settings)
    except assembly.ConsultAssemblyError as exc:
        raise _unavailable(str(exc)) from exc
    if skill_name not in registry.names():
        raise _unprocessable(f"未知的技能：{skill_name}")
    return (registry.get(skill_name),)


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

    1. 技能校验先于一切状态写入——一个未知技能名的请求不该占住会话位再回滚；
    2. 归属判定先于幂等与互斥——对别人的会话，任何状态码都不该泄露它是否正忙；
    3. 幂等命中直接返回原 `run_id`，不碰会话位、也不追加消息；
    4. 互斥失败回 409 且不追加消息（契约第 2 节与质量地板 ③）；
    5. 启动失败（首个事件不是 `run_started`）时释放占位并回 503——此时没有
       `run_id`，回 202 会让前端订阅一个不存在的路径。

    Raises:
        HTTPException: 会话不可访问（404）、载荷或技能不合法（422）、
            会话已有在跑的运行（409），或运行器未装配、运行未能启动（503）。
    """
    account_id = session.get_user_id()
    activated = await _activated_skill(settings, payload.skill)

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

    user_input = render_answers(payload.answers) if payload.answers is not None else (payload.content or "")
    request = RunRequest(
        session_id=session_id,
        surface=SURFACE_NAME,
        instructions=assembly.CONSULT_INSTRUCTIONS,
        user_input=user_input,
        activated=activated,
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
            try:
                _seq, name = decode_frame(raw)
            except ValueError:
                # 截断过的帧：id 行仍可读时按事件送出去，读不出就当它不存在。
                continue
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
    meta = await runbus.read_run_meta(cache, run_id=run_id)
    if meta is None or meta.account_id != account_id:
        raise _run_not_found()
    if not await cache.exists(runbus.events_key(run_id)):
        raise _not_resumable()

    return StreamingResponse(
        _stream_frames(cache, run_id=run_id, after_seq=after_seq),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


__all__ = [
    "RUN_NOT_FOUND_MESSAGE",
    "STREAM_MAX_SECONDS",
    "STREAM_POLL_SECONDS",
    "SURFACE_NAME",
    "create_session",
    "hydrate_history",
    "list_sessions",
    "parse_last_event_id",
    "router",
    "send_message",
    "stream_run",
]
