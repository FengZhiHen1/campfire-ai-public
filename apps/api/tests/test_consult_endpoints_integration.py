"""咨询面 T07a 端到端：会话端点、发消息受理、事件流订阅（真实库 + 真实 Redis + 真实 ASGI）。

对应 `docs/技术设计/面/consult/HTTP与SSE契约.md` 第 1、2、3、4.1、4.2、7、8 节。

    docker compose up -d postgres redis
    uv run pytest -m integration apps/api/tests/test_consult_endpoints_integration.py

这里钉住的五类事

1. 会话端点：默认对象推导、显式对象的可写校验、列表的字段与分页边界、水合的空对话
   与失败的区别。
2. 越权不可分辨：不存在与会话/运行属于别人，必须是同一个 404 与同一条文案。
3. 202 的语义：只表示受理；`run_id` 可订阅；使用者消息由运行写入真源。
4. 并发与幂等：同会话真并发两 POST（`asyncio.gather`）恰好一 202 一 409；
   同 `client_message_id` 重发返回原 `run_id` 且消息只落一条。
5. SSE 线格式：断言原始字节的三行制、心跳与终态关流，以及 `Last-Event-ID` 续传。

为什么用一个脚本化运行器

被测的是面（受理、状态码、缓冲、线格式），不是模型调用。脚本化运行器按固定脚本产出
基座事件，并像真实运行那样把使用者消息写进 SDK 会话真源——后者是幂等与并发用例能
断言「消息只落一条」的前提。因此它替换的是模型与工具，不是被测的写入路径。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import campfire.main as main_module
from campfire.agent.runtime import (
    RunEvent,
    RunFailedEvent,
    RunFinishedEvent,
    RunRequest,
    RunStartedEvent,
    RunUsage,
    TextDeltaEvent,
)
from campfire.agent.runtime.session import build_sqlalchemy_session
from campfire.core.auth.supertokens import init_supertokens
from campfire.core.authz import OBJECT_NOT_ACCESSIBLE_MESSAGE, set_authorizer
from campfire.core.cache import RedisCache, set_cache
from campfire.core.config import Settings, get_settings
from campfire.core.db import get_engine, session_scope
from campfire.core.db.sdk_session import AgentMessage, AgentSession
from campfire.modules.accounts import session_repository as accounts_repo
from campfire.modules.accounts.first_run_injection import read_first_run_injected
from campfire.modules.accounts.models import (
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    ONBOARDING_SKIPPED,
    CampfireOnboarding,
    CampfireSession,
)
from campfire.modules.accounts.onboarding import read_onboarding_state
from campfire.modules.accounts.onboarding_completion import complete_onboarding
from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields
from campfire.modules.accounts.session_items import message_text
from campfire.modules.accounts.session_repository import get_session_owner
from campfire.modules.memory.derived import EmergencyMemory
from campfire.modules.memory.errors import MemoryUnavailableError
from campfire.modules.profile import archive_object, create_object
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.models import SessionObjectBinding, SupportObject
from campfire.surfaces.consult import assembly as consult_assembly
from campfire.surfaces.consult import routes as consult_routes
from campfire.surfaces.consult.injections import (
    EMERGENCY_INTAKE_PREFIX,
    EMERGENCY_MEMORY_PREFIX,
    EMERGENCY_PROFILE_PREFIX,
    ONBOARDING_NOTICE_PREFIX,
)
from campfire.surfaces.consult.runbus import RUN_NOT_RUNNING, cancel_pumps, drain_pumps, events_key, mutex_key

# 本文件的用例全是 async（仓库未开 pytest-asyncio 的 auto 模式，逐个加标记是既有做法）。
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: 本文件的两个账号：`_ACCOUNT` 是使用者，`_OTHER_ACCOUNT` 是越权用例里的「别人」。
_ACCOUNT = "it_consult_account"
_OTHER_ACCOUNT = "it_consult_other"

#: 本文件的 Redis 键前缀复核清单（出场 SCAN 用；键名由裁决 1/2/3 钉死，不加测试前缀）。
_KEY_PATTERNS = ("run:*", "session:*", "idem:*")


# ---------------------------------------------------------------------------
# 测试替身：脚本化运行器与会话桩
# ---------------------------------------------------------------------------


class ScriptedRunner:
    """按固定脚本产出事件的运行器替身。

    它同时承担真实运行的两件事：把使用者消息写进 SDK 会话真源（少了它，
    「幂等不重复追加」「并发被拒时不追加」两条断言就没有可观测对象），
    以及把本次请求原样记下来（`requests`）——T07b 的新增断言要看的正是
    「服务端到底给这次运行注入了什么」，而那只有面构造的 `RunRequest` 能回答。
    """

    def __init__(
        self,
        settings: Settings,
        *,
        deltas: Sequence[str] = ("这是测试回复。",),
        startup_delay: float = 0.0,
        fail_before_start: bool = False,
        append_user_message: bool = True,
        append_injections: bool = False,
    ) -> None:
        """绑定配置与脚本参数。

        `append_injections` 默认关闭：打开后每次运行会额外落若干条注入条目，
        而 T07a 的既有用例按条目计数断言「消息只落一条」——默认关闭让那些断言
        保持不动，需要观察注入落库的用例（首轮告知）自己打开它。
        """
        self._settings = settings
        self._deltas = tuple(deltas)
        self._startup_delay = startup_delay
        self._fail_before_start = fail_before_start
        self._append_user_message = append_user_message
        self._append_injections = append_injections
        #: 本次进程内真正启动过的运行（并发用例据此断言「只起了一次」）。
        self.started: list[str] = []
        #: 面交给运行器的每一次请求（按发生顺序），供注入断言检查。
        self.requests: list[RunRequest] = []
        #: 闸门：置为不空时运行会停在它上面，供「运行中再发」的用例保持运行。
        self.gate: asyncio.Event | None = None

    def run(self, request: RunRequest) -> AsyncIterator[RunEvent]:
        """返回一次运行的异步生成器（与 `AgentRunner.run` 同形）。"""
        return self._generate(request)

    async def _generate(self, request: RunRequest) -> AsyncIterator[RunEvent]:
        """脚本本体：起步延迟 → （可选）起步前失败 → 落消息 → 事件。"""
        if self._startup_delay:
            await asyncio.sleep(self._startup_delay)
        if self._fail_before_start:
            yield RunFailedEvent(
                code="session_write_failed",
                detail="对话真源不可用（测试替身）",
                citations=(),
                usage=RunUsage(),
                elapsed_seconds=0.0,
            )
            return

        run_id = uuid.uuid4().hex
        self.started.append(run_id)
        self.requests.append(request)
        sdk = build_sqlalchemy_session(request.session_id, engine=get_engine(self._settings))
        if self._append_injections:
            # 真实基座把注入项写在使用者消息之前（`runner.run` 的 `new_items` 顺序）。
            # 这里不写引用索引：本面的注入项都没有业务回指（`reference is None`），
            # 渲染结果就是逐条的消息正文。
            for item in request.injections.ordered():
                await sdk.add_items([{"role": item.role, "content": item.content}])  # type: ignore[arg-type]  # SDK 的 add_items 收 SDK 自有条目类型，测试传字面量 dict
        if self._append_user_message:
            await sdk.add_items([{"role": "user", "content": request.user_input or ""}])  # type: ignore[arg-type]  # SDK 的 add_items 收 SDK 自有条目类型，测试传字面量 dict

        yield RunStartedEvent(
            run_id=run_id,
            session_id=request.session_id,
            surface=request.surface,
            model="scripted",
            activated_skills=tuple(skill.name for skill in request.activated),
            injection_sources=tuple(item.source for item in request.injections.ordered()),
            appended_messages=1,
        )
        if self.gate is not None:
            await self.gate.wait()
        for delta in self._deltas:
            yield TextDeltaEvent(delta=delta)
        yield RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=0.01)


class StubSession:
    """`SessionContainer` 的桩：只需要回答「你是谁」。"""

    def __init__(self, account_id: str) -> None:
        """记录该请求的登录账号。"""
        self._account_id = account_id

    def get_user_id(self) -> str:
        """返回登录账号（真实 SDK 的同名方法）。"""
        return self._account_id


def _auth_as(account_id: str):  # noqa: ANN202 —— 返回 FastAPI 依赖函数
    """造一个「以某账号登录」的认证依赖。"""

    async def _dependency() -> StubSession:
        return StubSession(account_id)

    return _dependency


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _require_environment() -> AsyncIterator[None]:
    """缺库或 Redis 不可用时跳过——不假装通过（仓库既有集成测试的统一做法）。"""
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    cache = RedisCache(settings.redis_url)
    try:
        await cache.exists("it-consult-probe")
    except Exception as exc:  # noqa: BLE001 —— 探针只回答「能不能连上」
        await cache.aclose()
        pytest.skip(f"Redis 不可用（{type(exc).__name__}）——集成测试需要 docker compose up -d redis")
    await cache.aclose()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    """清掉本文件写入的行与 Redis 键：前后各一次。

    按账号过滤而不是无过滤全表删除：并发跑的其它集成测试文件各自做全表删除时
    会互相删掉对方刚写入的行（2026-09-30 实测的真实缺陷）。
    """
    await _purge_db()
    await _purge_redis()
    yield
    cancel_pumps()
    await drain_pumps()
    await _purge_db()
    await _purge_redis()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """一个穿过完整 FastAPI 应用的 ASGI 客户端（认证被替换成桩）。

    ASGITransport 不会跑 lifespan，因此这里显式做装配——与
    `test_auth_registration_integration.py` 同一种做法。认证 SDK 仍要初始化：
    SuperTokens 中间件在每个请求上取实例，未初始化时会直接抛 GeneralError，
    而「未登录 401」那条用例正是要穿过它。
    """
    settings = get_settings()
    init_supertokens(settings, api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)
    set_authorizer(OwnerAuthorizer(settings))
    cache = RedisCache(settings.redis_url)
    set_cache(cache)
    consult_assembly.clear_skill_registries()
    consult_assembly.set_runner_factory(None)
    main_module.app.dependency_overrides[consult_routes._session_dependency] = _auth_as(_ACCOUNT)
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://consult.test") as http_client:
        yield http_client
    main_module.app.dependency_overrides.clear()
    consult_assembly.set_runner_factory(None)
    await drain_pumps()
    await cache.aclose()
    set_cache(None)


async def _purge_db() -> None:
    """删除本文件两个账号的行，以及它们名下的 SDK 会话行。"""
    accounts = [_ACCOUNT, _OTHER_ACCOUNT]
    async with session_scope(get_settings()) as session:
        session_ids = list(
            (
                await session.execute(
                    select(CampfireSession.session_id).where(CampfireSession.account_id.in_(accounts))
                )
            ).scalars()
        )
        if session_ids:
            await session.execute(delete(AgentMessage).where(AgentMessage.session_id.in_(session_ids)))
            await session.execute(delete(AgentSession).where(AgentSession.session_id.in_(session_ids)))
        await session.execute(delete(CampfireSession).where(CampfireSession.account_id.in_(accounts)))
        await session.execute(delete(SessionObjectBinding).where(SessionObjectBinding.account_id.in_(accounts)))
        await session.execute(delete(SupportObject).where(SupportObject.account_id.in_(accounts)))
        await session.execute(delete(CampfireOnboarding).where(CampfireOnboarding.account_id.in_(accounts)))


async def _purge_redis() -> None:
    """删除本文件可能留下的三类键（键名形状由裁决 1/2/3 钉死，故按模式清）。"""
    settings = get_settings()
    cache = RedisCache(settings.redis_url)
    try:
        for pattern in _KEY_PATTERNS:
            leftover = await cache.scan_keys(pattern, limit=1000)
            if leftover:
                await cache.delete(*leftover)
    finally:
        await cache.aclose()


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _install_runner(runner: ScriptedRunner) -> None:
    """把脚本化运行器装进面装配（替换模型与工具，不替换被测的写入路径）。"""
    consult_assembly.set_runner_factory(lambda _settings: runner)  # type: ignore[arg-type,return-value]  # 替身只实现 run()，与 AgentRunner 的完整形状不同


async def _make_object(account_id: str, name: str = "小宝") -> str:
    """经用例层建一个支持对象，返回它的标识。"""
    async with session_scope(get_settings()) as session:
        record = await create_object(session, account_id=account_id, display_name=name)
    return str(record.id)


async def _create_session(client: httpx.AsyncClient, support_object_id: str | None = None) -> str:
    """经端点建一个会话，返回会话标识。"""
    body = {} if support_object_id is None else {"support_object_id": support_object_id}
    response = await client.post("/consult/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


async def _send(client: httpx.AsyncClient, session_id: str, **body: object) -> httpx.Response:
    """发一条消息。"""
    payload: dict[str, object] = {"client_message_id": uuid.uuid4().hex}
    payload.update(body)
    return await client.post(f"/consult/sessions/{session_id}/messages", json=payload)


async def _read_stream(client: httpx.AsyncClient, run_id: str, last_event_id: str | None = None) -> httpx.Response:
    """把整条流读完（运行已终结时它会自行关流）。"""
    headers = {} if last_event_id is None else {"Last-Event-ID": last_event_id}
    async with client.stream("GET", f"/consult/runs/{run_id}/stream", headers=headers) as response:
        body = b"".join([chunk async for chunk in response.aiter_bytes()])
    return httpx.Response(response.status_code, headers=response.headers, content=body)


async def _item_count(session_id: str) -> int:
    """某会话在 SDK 真源里的条目条数。"""
    async with session_scope(get_settings()) as session:
        return await accounts_repo.count_session_items(session, session_id=session_id)


async def _onboarding_state(account_id: str) -> str | None:
    """账号在引导状态表里的状态（无行返回 `None`）。"""
    async with session_scope(get_settings()) as session:
        return await read_onboarding_state(session, account_id=account_id)


async def _first_run_injected(session_id: str) -> bool:
    """会话的首轮注入结算标记。"""
    async with session_scope(get_settings()) as session:
        return await read_first_run_injected(session, session_id=session_id)


# ---------------------------------------------------------------------------
# 3.1 创建会话
# ---------------------------------------------------------------------------


async def test_create_session_without_objects_reports_null_and_pending(client: httpx.AsyncClient) -> None:
    """账号一个在用对象都没有时返回 `null` 且引导待注入——不是错误（`AC-02`）。"""
    response = await client.post("/consult/sessions", json={})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["support_object_id"] is None
    assert body["onboarding_pending"] is True

    async with session_scope(get_settings()) as session:
        owned = await accounts_repo.is_session_owned_by(session, session_id=body["session_id"], account_id=_ACCOUNT)
    assert owned is True, "归属行必须随创建落库，否则这个会话谁也读不了"


async def test_create_session_binds_the_explicit_object(client: httpx.AsyncClient) -> None:
    """传入对象标识时按其绑定，并在响应里原样回显。"""
    object_id = await _make_object(_ACCOUNT)
    session_id = await _create_session(client, object_id)

    async with session_scope(get_settings()) as session:
        owner = await get_session_owner(session, session_id=session_id)
    assert owner is not None and owner.account_id == _ACCOUNT

    listed = (await client.get("/consult/sessions")).json()
    assert listed["items"][0]["support_object_name"] == "小宝"


async def test_create_session_with_another_accounts_object_is_404(client: httpx.AsyncClient) -> None:
    """别人的对象不可绑定：404，且与「对象不存在」同一条文案。"""
    foreign = await _make_object(_OTHER_ACCOUNT, "别人的孩子")
    response = await client.post("/consult/sessions", json={"support_object_id": foreign})
    assert response.status_code == 404
    assert response.json()["detail"] == OBJECT_NOT_ACCESSIBLE_MESSAGE

    missing = await client.post("/consult/sessions", json={"support_object_id": str(uuid.uuid4())})
    assert missing.status_code == 404
    assert missing.json()["detail"] == response.json()["detail"]


async def test_create_session_with_archived_object_is_404_with_same_message(client: httpx.AsyncClient) -> None:
    """归档对象不得绑定新会话（契约 3.1），文案与不存在逐字相同。"""
    object_id = await _make_object(_ACCOUNT, "已归档")
    async with session_scope(get_settings()) as session:
        await archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    archived = await client.post("/consult/sessions", json={"support_object_id": object_id})
    missing = await client.post("/consult/sessions", json={"support_object_id": str(uuid.uuid4())})
    assert archived.status_code == missing.status_code == 404
    assert archived.json()["detail"] == missing.json()["detail"] == OBJECT_NOT_ACCESSIBLE_MESSAGE


async def test_create_session_rejects_unknown_fields(client: httpx.AsyncClient) -> None:
    """多给字段是 422（静默忽略会让前端以为自己传对了）。"""
    response = await client.post("/consult/sessions", json={"supportObjectId": "x"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 3.2 会话列表
# ---------------------------------------------------------------------------


async def test_list_sessions_shows_title_preview_and_only_own_sessions(client: httpx.AsyncClient) -> None:
    """列表字段与「只列自己的」：标题取首条使用者消息，预览取末条。"""
    mine = await _create_session(client)
    await _create_session(client)  # 第二条：验证列表有多行
    async with session_scope(get_settings()) as session:
        foreign, _created = await accounts_repo.insert_session_owner(
            session, session_id=f"it-consult-foreign-{uuid.uuid4().hex[:8]}", account_id=_OTHER_ACCOUNT
        )

    sdk = build_sqlalchemy_session(mine, engine=get_engine(get_settings()))
    await sdk.add_items(  # type: ignore[arg-type]  # SDK 的 add_items 收 SDK 自有条目类型，测试传字面量 dict
        [
            {"role": "user", "content": "孩子最近睡不好，怎么办"},
            {"role": "assistant", "content": [{"type": "output_text", "text": "可以先记录一周的作息。"}]},
        ]
    )

    body = (await client.get("/consult/sessions", params={"limit": 20})).json()
    ids = [item["session_id"] for item in body["items"]]
    assert mine in ids
    assert foreign.session_id not in ids, "别人的会话不得出现在列表里"
    row = next(item for item in body["items"] if item["session_id"] == mine)
    assert row["title"].startswith("孩子最近睡不好")
    assert row["last_message_preview"].startswith("可以先记录")
    assert row["support_object_name"] is None, "无绑定会话的该字段是 null，且前端不渲染"


async def test_list_sessions_rejects_bad_limit_and_cursor(client: httpx.AsyncClient) -> None:
    """分页参数越界或不可解析一律 422（对抗用例：超上限、伪造游标）。"""
    for params in ({"limit": 0}, {"limit": 51}, {"cursor": "!!!not-base64!!!"}):
        response = await client.get("/consult/sessions", params=params)
        assert response.status_code == 422, params


async def test_list_sessions_paginates_without_overlap(client: httpx.AsyncClient) -> None:
    """游标翻页：翻到底不重复、不漏，末页的 `next_cursor` 为 null（契约 3.2）。"""
    created = [await _create_session(client) for _ in range(3)]

    first = (await client.get("/consult/sessions", params={"limit": 2})).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"], "取满一页时必须给出下一页游标"

    second = (await client.get("/consult/sessions", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    first_ids = {item["session_id"] for item in first["items"]}
    second_ids = {item["session_id"] for item in second["items"]}
    assert not (first_ids & second_ids), "翻页不得重复"
    assert first_ids | second_ids == set(created), "翻页不得漏掉任何一条"
    assert second["next_cursor"] is None


# ---------------------------------------------------------------------------
# 3.3 历史水合
# ---------------------------------------------------------------------------


async def test_hydrate_empty_session_is_an_empty_list_not_an_error(client: httpx.AsyncClient) -> None:
    """刚建的会话返回空列表——与失败是两件事（契约 3.3）。"""
    session_id = await _create_session(client)
    response = await client.get(f"/consult/sessions/{session_id}/messages")
    assert response.status_code == 200
    assert response.json() == {"session_id": session_id, "messages": []}


async def test_hydrate_missing_and_foreign_session_share_the_same_404(client: httpx.AsyncClient) -> None:
    """不存在与越权必须不可分辨（越权探测的入口之一）。"""
    async with session_scope(get_settings()) as session:
        foreign, _created = await accounts_repo.insert_session_owner(
            session, session_id=f"it-consult-foreign-{uuid.uuid4().hex[:8]}", account_id=_OTHER_ACCOUNT
        )

    missing = await client.get(f"/consult/sessions/{uuid.uuid4().hex}/messages")
    foreign_response = await client.get(f"/consult/sessions/{foreign.session_id}/messages")
    assert missing.status_code == foreign_response.status_code == 404
    assert missing.json() == foreign_response.json()


# ---------------------------------------------------------------------------
# 4.1 发消息
# ---------------------------------------------------------------------------


async def test_send_message_returns_202_and_the_run_is_subscribable(client: httpx.AsyncClient) -> None:
    """202 只表示受理；返回的 `run_id` 可以订阅到事件。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)

    response = await _send(client, session_id, content="你好")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["session_id"] == session_id
    assert body["run_id"] in runner.started

    await drain_pumps()
    streamed = await _read_stream(client, body["run_id"])
    assert streamed.status_code == 200
    assert b"event: run_started" in streamed.content


async def test_send_message_is_idempotent(client: httpx.AsyncClient) -> None:
    """同 `client_message_id` 重发返回原 `run_id`，且消息只落一条。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)
    key = uuid.uuid4().hex

    first = await _send(client, session_id, content="重复提交", client_message_id=key)
    await drain_pumps()
    second = await _send(client, session_id, content="重复提交", client_message_id=key)
    await drain_pumps()

    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert len(runner.started) == 1, "重发不得再起一次运行"
    assert await _item_count(session_id) == 1, "重发不得重复追加使用者消息"


async def test_send_message_while_running_is_409_without_appending(client: httpx.AsyncClient) -> None:
    """会话已有在跑的运行 → 409 `session_busy`，且不追加消息（质量地板 ③）。"""
    runner = ScriptedRunner(get_settings())
    runner.gate = asyncio.Event()
    _install_runner(runner)
    session_id = await _create_session(client)

    accepted = await _send(client, session_id, content="第一条")
    assert accepted.status_code == 202

    busy = await _send(client, session_id, content="第二条")
    assert busy.status_code == 409
    assert busy.json()["detail"] == "session_busy"
    assert await _item_count(session_id) == 1, "被拒的请求不得留下消息"

    runner.gate.set()


async def test_two_concurrent_posts_yield_one_202_and_one_409(client: httpx.AsyncClient) -> None:
    """真并发（`asyncio.gather`）两 POST：恰好一个受理、一个会话忙。"""
    runner = ScriptedRunner(get_settings(), startup_delay=0.05)
    runner.gate = asyncio.Event()
    _install_runner(runner)
    session_id = await _create_session(client)

    first, second = await asyncio.gather(
        _send(client, session_id, content="并发一"),
        _send(client, session_id, content="并发二"),
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [202, 409], (first.text, second.text)
    assert len(runner.started) == 1, "同一会话并发只允许一个运行真正启动"
    assert await _item_count(session_id) == 1

    # 释放闸门并等收尾：前台用例结束后互斥键必须被放掉（TTL 只是兜底）。
    runner.gate.set()
    await drain_pumps()
    cache = RedisCache(get_settings().redis_url)
    try:
        assert not await cache.exists(mutex_key(session_id)), "终结时必须删掉会话互斥键"
    finally:
        await cache.aclose()


async def test_send_message_to_foreign_or_missing_session_is_404(client: httpx.AsyncClient) -> None:
    """发消息到别人的会话与不存在的会话：同一个 404。"""
    _install_runner(ScriptedRunner(get_settings()))
    async with session_scope(get_settings()) as session:
        foreign, _created = await accounts_repo.insert_session_owner(
            session, session_id=f"it-consult-foreign-{uuid.uuid4().hex[:8]}", account_id=_OTHER_ACCOUNT
        )

    missing = await _send(client, uuid.uuid4().hex, content="x")
    foreign_response = await _send(client, foreign.session_id, content="x")
    assert missing.status_code == foreign_response.status_code == 404
    assert missing.json() == foreign_response.json()


async def test_send_message_rejects_unknown_skill_and_accepts_registered_one(
    client: httpx.AsyncClient,
) -> None:
    """`skill` 必须是已注册技能（裁决 11）；已注册时该次运行程序注入它。

    先把账号的引导状态收束掉再发消息：否则这是会话的第一次运行，服务端会按契约 3.1
    程序注入 onboarding 并忽略 `skill`（T07b 落地的后果，用例见
    `test_consult_emergency_integration.py`）。本用例只回答「`skill` 参数怎么被校验与消费」，
    因此它必须跑在引导已终结的账号上。
    """
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)
    async with session_scope(get_settings()) as db:
        await complete_onboarding(db, account_id=_ACCOUNT)

    unknown = await _send(client, session_id, content="x", skill="no-such-skill")
    assert unknown.status_code == 422

    accepted = await _send(client, session_id, content="x", skill="daily-consulting")
    assert accepted.status_code == 202, accepted.text
    await drain_pumps()
    streamed = await _read_stream(client, accepted.json()["run_id"])
    assert b"daily-consulting" in streamed.content, "程序注入的激活集合必须出现在 run_started 里"


async def test_send_message_rejects_empty_content_and_empty_answers(client: httpx.AsyncClient) -> None:
    """两种形态各自的载荷不合法（对抗用例：空正文、空回答数组）。"""
    _install_runner(ScriptedRunner(get_settings()))
    session_id = await _create_session(client)

    assert (await _send(client, session_id, content="   ")).status_code == 422
    assert (await _send(client, session_id, answers=[])).status_code == 422


async def test_answers_are_rendered_into_one_user_message(client: httpx.AsyncClient) -> None:
    """一组回答渲染成一条使用者消息，且「跳过」可判定（契约 4.1）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)

    response = await _send(
        client,
        session_id,
        answers=[
            {"id": "q1", "value": "会有"},
            {"id": "q2", "skipped": True},
        ],
    )
    assert response.status_code == 202, response.text
    await drain_pumps()

    hydrated = (await client.get(f"/consult/sessions/{session_id}/messages")).json()
    user_messages = [message for message in hydrated["messages"] if message["role"] == "user"]
    assert len(user_messages) == 1, "一组回答是一次提交，落一条消息"
    text = user_messages[0]["parts"][0]["text"]
    assert text.splitlines()[0] == "以下是对提问的作答"
    assert text.splitlines()[2].endswith("（跳过）")


async def test_startup_failure_returns_503_and_releases_the_slot(client: httpx.AsyncClient) -> None:
    """首个事件不是 `run_started` 时没有可订阅的 `run_id` → 503，且占位被释放。"""
    _install_runner(ScriptedRunner(get_settings(), fail_before_start=True))
    session_id = await _create_session(client)

    response = await _send(client, session_id, content="x")
    assert response.status_code == 503
    assert "session_write_failed" in response.json()["detail"]

    cache = RedisCache(get_settings().redis_url)
    try:
        assert not await cache.exists(mutex_key(session_id)), "启动失败必须释放会话位"
    finally:
        await cache.aclose()


# ---------------------------------------------------------------------------
# 4.2 订阅事件流
# ---------------------------------------------------------------------------


async def test_stream_raw_bytes_are_three_line_frames(client: httpx.AsyncClient) -> None:
    """SSE 原始字节实测：`id` / `event` / `data` 三行 + 空行，终态后关流。"""
    runner = ScriptedRunner(get_settings(), deltas=("第一段", "第二段"))
    _install_runner(runner)
    session_id = await _create_session(client)
    accepted = await _send(client, session_id, content="你好")
    await drain_pumps()

    async with client.stream("GET", f"/consult/runs/{accepted.json()['run_id']}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream"
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        raw = b"".join([chunk async for chunk in response.aiter_bytes()])

    text = raw.decode("utf-8")
    frames = [frame for frame in text.split("\n\n") if frame]
    assert frames, "流里必须至少有一帧"
    for index, frame in enumerate(frames, start=1):
        lines = frame.split("\n")
        assert lines[0] == f"id: {index}", f"id 必须是运行内单调递增的序号：{frame!r}"
        assert lines[1].startswith("event: ")
        assert lines[2].startswith("data: ")
        assert len(lines) == 3
    assert frames[0].split("\n")[1] == "event: run_started"
    assert frames[-1].split("\n")[1] == "event: run_finished", "终态事件后必须关流"
    assert text.endswith("\n\n")


async def test_stream_resumes_from_last_event_id(client: httpx.AsyncClient) -> None:
    """带 `Last-Event-ID` 时从下一条续发（契约 4.2 的续传判据）。"""
    runner = ScriptedRunner(get_settings(), deltas=("一", "二"))
    _install_runner(runner)
    session_id = await _create_session(client)
    accepted = await _send(client, session_id, content="你好")
    await drain_pumps()
    run_id = accepted.json()["run_id"]

    whole = (await _read_stream(client, run_id)).content.decode("utf-8")
    resumed = (await _read_stream(client, run_id, last_event_id="1")).content.decode("utf-8")

    assert whole.count("event: run_started") == 1
    assert "event: run_started" not in resumed, "序号 1 已经发过，续传不得重发"
    assert resumed.startswith("id: 2\n"), resumed[:40]
    assert resumed.count("\n\n") == whole.count("\n\n") - 1


async def test_stream_with_out_of_range_last_event_id_closes_quietly(client: httpx.AsyncClient) -> None:
    """续传序号超界且运行已终结：没有可续内容，安静关流（不是 409——缓冲还在）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)
    accepted = await _send(client, session_id, content="你好")
    await drain_pumps()

    response = await _read_stream(client, accepted.json()["run_id"], last_event_id="999")
    assert response.status_code == 200
    assert response.content == b""


async def test_stream_rejects_unknown_and_foreign_run_with_same_404(client: httpx.AsyncClient) -> None:
    """运行不存在与不属于当前账号：同一个 404（越权与不存在不可分辨）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    main_module.app.dependency_overrides[consult_routes._session_dependency] = _auth_as(_OTHER_ACCOUNT)
    foreign_session = await _create_session(client)
    foreign_run = (await _send(client, foreign_session, content="别人的")).json()["run_id"]
    await drain_pumps()
    main_module.app.dependency_overrides[consult_routes._session_dependency] = _auth_as(_ACCOUNT)

    missing = await client.get(f"/consult/runs/{uuid.uuid4().hex}/stream")
    foreign = await client.get(f"/consult/runs/{foreign_run}/stream")
    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json()


async def test_stream_returns_409_when_the_buffer_is_gone(client: httpx.AsyncClient) -> None:
    """缓冲已失效且无可续内容 → 409 `run_not_resumable`（契约 4.2 与裁决 1）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)
    accepted = await _send(client, session_id, content="你好")
    await drain_pumps()
    run_id = accepted.json()["run_id"]

    cache = RedisCache(get_settings().redis_url)
    try:
        await cache.delete(events_key(run_id))
    finally:
        await cache.aclose()

    response = await client.get(f"/consult/runs/{run_id}/stream")
    assert response.status_code == 409
    assert response.json()["detail"] == "run_not_resumable"


async def test_stream_frames_emit_heartbeat_while_idle(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """心跳字节实测：空闲时按间隔产出 `: ping` 空注释行，且它出现在终态之前。

    心跳的真实间隔是 15 秒（`sse.HEARTBEAT_INTERVAL_SECONDS`，由单元用例钉住），
    这里改小到 50 毫秒——否则这条用例要跑 15 秒才拿到一个字节。

    为什么直接驱动帧生成器而不是发一个真请求：`httpx.ASGITransport` 不支持
    增量到达——它在 `handle_async_request` 里等应用把响应体全部产出后才返回
    （实测 `_transports/asgi.py:185-187`：`ASGIResponseStream` 只 `yield b"".join(body_parts)`）。
    因此「字节何时到达」在本进程内不可观测，能观测的是「产出了哪些字节、顺序如何」。
    代理（Nginx）之后的真实到达行为仍属契约第 10 节列出的未实测项。
    """
    monkeypatch.setattr(consult_routes, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(consult_routes, "STREAM_POLL_SECONDS", 0.02)
    runner = ScriptedRunner(get_settings())
    runner.gate = asyncio.Event()
    _install_runner(runner)
    session_id = await _create_session(client)
    accepted = await _send(client, session_id, content="你好")
    run_id = accepted.json()["run_id"]

    cache = RedisCache(get_settings().redis_url)
    chunks: list[str] = []
    try:
        # 上界（CORE-11）：心跳不出现时用例应当失败，而不是挂住。
        async with asyncio.timeout(30.0):
            async for chunk in consult_routes._stream_frames(cache, run_id=run_id, after_seq=0):
                chunks.append(chunk)
                if ": ping" in "".join(chunks) and not runner.gate.is_set():
                    runner.gate.set()
    finally:
        await cache.aclose()

    joined = "".join(chunks)
    assert ": ping\n\n" in joined, joined
    assert "event: run_finished" in joined, "放行后运行应走到终态"
    assert joined.index(": ping") < joined.index("event: run_finished"), "心跳是空闲期的事件"
    runner.gate.set()
    await drain_pumps()


async def test_unauthenticated_requests_are_401(client: httpx.AsyncClient) -> None:
    """未登录一律 401（除 `/health` 外全端点，`RQ-ACC-01`）。

    这条用例刻意摘掉认证桩，走真实的 SuperTokens 依赖：无凭据的请求必须在
    进到业务代码之前被拒。
    """
    main_module.app.dependency_overrides.clear()
    for method, path in (
        ("POST", "/consult/sessions"),
        ("GET", "/consult/sessions"),
        ("GET", f"/consult/sessions/{uuid.uuid4().hex}/messages"),
        ("POST", f"/consult/sessions/{uuid.uuid4().hex}/messages"),
        ("GET", f"/consult/runs/{uuid.uuid4().hex}/stream"),
        ("POST", f"/consult/runs/{uuid.uuid4().hex}/cancel"),
        ("POST", "/consult/emergency"),
        ("POST", f"/consult/sessions/{uuid.uuid4().hex}/onboarding/skip"),
    ):
        response = await client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 401, (method, path, response.status_code, response.text)
    assert (await client.get("/health")).status_code in (200, 503)


# ---------------------------------------------------------------------------
# 3.1 的后果：首次日常会话的第一次运行注入引导（T07b）
# ---------------------------------------------------------------------------


async def test_first_daily_run_injects_onboarding_and_ignores_skill(client: httpx.AsyncClient) -> None:
    """首次日常会话的第一次运行程序注入 onboarding 与静态告知，并忽略 `skill`。

    契约 3.1 的两句话在这里一次验完：`onboarding_pending` 为真时会话的第一次运行由
    服务端注入引导；而这一次运行不是使用者选的那件事（他选了 daily-consulting，
    因此「忽略 skill 参数」必须可观测）。
    """
    runner = ScriptedRunner(get_settings(), append_injections=True)
    _install_runner(runner)
    session_id = await _create_session(client)

    response = await _send(client, session_id, content="你好", skill="daily-consulting")
    assert response.status_code == 202, response.text
    await drain_pumps()

    request = runner.requests[-1]
    assert [skill.name for skill in request.activated] == ["onboarding"], "首次运行必须注入引导并忽略 skill 选择"
    notices = [item for item in request.injections.ordered() if item.source == "onboarding-notice"]
    assert len(notices) == 1
    assert notices[0].role == "assistant", "告知必须落到助手角色，否则水合会把它当机器上下文跳过"
    assert notices[0].content.startswith(ONBOARDING_NOTICE_PREFIX)
    assert "本次输入的内容用于生成回答，并按你的确认累积到档案与记忆。" in notices[0].content

    # 记账两处：会话标记（本会话不再注入）+ 账号引导状态（引导已开始）。
    assert await _first_run_injected(session_id) is True
    assert await _onboarding_state(_ACCOUNT) == ONBOARDING_IN_PROGRESS

    # 告知真的能被使用者读到：它是水合出来的第一条消息，且不是使用者消息。
    hydrated = (await client.get(f"/consult/sessions/{session_id}/messages")).json()
    first = hydrated["messages"][0]
    assert first["role"] == "assistant"
    assert ONBOARDING_NOTICE_PREFIX in first["parts"][0]["text"]


async def test_second_run_of_the_same_session_does_not_inject_onboarding(client: httpx.AsyncClient) -> None:
    """同一个会话的第二次运行不再注入引导，`skill` 参数恢复生效。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)

    assert (await _send(client, session_id, content="第一次")).status_code == 202
    await drain_pumps()
    second = await _send(client, session_id, content="第二次", skill="daily-consulting")
    assert second.status_code == 202, second.text
    await drain_pumps()

    request = runner.requests[-1]
    assert [skill.name for skill in request.activated] == ["daily-consulting"]
    assert request.injections.ordered() == (), "第二次运行不该再带引导注入"


async def test_first_run_injection_is_not_consumed_when_the_run_fails_to_start(
    client: httpx.AsyncClient,
) -> None:
    """运行起步失败（503）时首轮注入不结算：这个会话下次仍会注入引导。

    漏注入不可恢复（使用者此后没有任何入口回到引导），重复注入只是多一段可跳过的引导
    ——两者代价不对称，因此记账只能落在运行真的起步之后。
    """
    _install_runner(ScriptedRunner(get_settings(), fail_before_start=True))
    session_id = await _create_session(client)

    failed = await _send(client, session_id, content="你好")
    assert failed.status_code == 503, failed.text
    await drain_pumps()
    assert await _first_run_injected(session_id) is False, "起步失败不得消耗首轮注入"
    assert await _onboarding_state(_ACCOUNT) is None, "起步失败不得落引导开始状态"

    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    retried = await _send(client, session_id, content="你好")
    assert retried.status_code == 202, retried.text
    await drain_pumps()
    assert [skill.name for skill in runner.requests[-1].activated] == ["onboarding"]


async def test_completed_onboarding_is_not_injected_on_the_first_run(client: httpx.AsyncClient) -> None:
    """引导已终结时 `onboarding_pending` 为假，第一次运行也不注入（契约 3.1）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    async with session_scope(get_settings()) as db:
        await complete_onboarding(db, account_id=_ACCOUNT)

    created = await client.post("/consult/sessions", json={})
    assert created.status_code == 201
    assert created.json()["onboarding_pending"] is False
    session_id = created.json()["session_id"]

    assert (await _send(client, session_id, content="你好", skill="daily-consulting")).status_code == 202
    await drain_pumps()
    assert [skill.name for skill in runner.requests[-1].activated] == ["daily-consulting"]


# ---------------------------------------------------------------------------
# 4.3 取消
# ---------------------------------------------------------------------------


async def _start_gated_run(client: httpx.AsyncClient, runner: ScriptedRunner) -> str:
    """起一次挂在闸门上的运行，返回 `run_id`（用例自己负责放行或取消）。"""
    runner.gate = asyncio.Event()
    session_id = await _create_session(client)
    response = await _send(client, session_id, content="跑起来")
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


async def test_cancel_returns_202_and_the_stream_ends_without_a_terminal_event(
    client: httpx.AsyncClient,
) -> None:
    """取消是 202；被取消的运行不发终态事件，流的结束只由状态落定触发（契约 4.3）。

    取消与订阅真并发（`asyncio.gather`）：流在取消发出时正挂在轮询上，
    因此「终态事件不会到达」这条断言测的是取消路径本身，而不是「运行先跑完了」。
    """
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    run_id = await _start_gated_run(client, runner)

    cancel_response, streamed = await asyncio.gather(
        client.post(f"/consult/runs/{run_id}/cancel"),
        _read_stream(client, run_id),
    )

    assert cancel_response.status_code == 202, cancel_response.text
    assert cancel_response.json()["cancelled"] is True
    assert streamed.status_code == 200
    assert b"event: run_started" in streamed.content, "取消前已产出的事件照常送达"
    assert b"event: run_finished" not in streamed.content
    assert b"event: run_failed" not in streamed.content

    runner.gate.set()
    await drain_pumps()


async def test_cancel_releases_the_session_and_metadata_says_finished(client: httpx.AsyncClient) -> None:
    """取消之后：运行元数据落终结状态、会话位释放（同一会话可以立刻再发消息）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)
    runner.gate = asyncio.Event()
    started = await _send(client, session_id, content="跑起来")
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]

    assert (await client.post(f"/consult/runs/{run_id}/cancel")).status_code == 202
    runner.gate.set()
    await drain_pumps()

    cache = RedisCache(get_settings().redis_url)
    try:
        assert await cache.get(mutex_key(session_id)) is None, "取消后必须释放会话位"
        meta_raw = await cache.get(f"run:{run_id}:meta")
        assert meta_raw is not None and '"status":"finished"' in meta_raw, meta_raw
    finally:
        await cache.aclose()

    again = await _send(client, session_id, content="再发一条")
    assert again.status_code == 202, "会话位没释放时这里会拿到 409"
    await drain_pumps()


async def test_cancel_finished_run_is_409(client: httpx.AsyncClient) -> None:
    """已终结的运行返回 409（契约 4.3），错误码是本面补的 `run_not_running`。"""
    _install_runner(ScriptedRunner(get_settings()))
    session_id = await _create_session(client)
    response = await _send(client, session_id, content="跑完")
    assert response.status_code == 202, response.text
    await drain_pumps()

    cancelled = await client.post(f"/consult/runs/{response.json()['run_id']}/cancel")
    assert cancelled.status_code == 409, cancelled.text
    assert cancelled.json()["detail"] == RUN_NOT_RUNNING


async def test_concurrent_cancels_never_both_succeed_and_never_error(client: httpx.AsyncClient) -> None:
    """两条取消真并发：都不报错，且至少一条 202（另一条可能已看到终结状态而 409）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    run_id = await _start_gated_run(client, runner)

    first, second = await asyncio.gather(
        client.post(f"/consult/runs/{run_id}/cancel"),
        client.post(f"/consult/runs/{run_id}/cancel"),
    )
    statuses = sorted([first.status_code, second.status_code])
    assert set(statuses) <= {202, 409}, (first.text, second.text)
    assert statuses[0] == 202, "第一次取消必须成功"

    runner.gate.set()
    await drain_pumps()


async def test_cancel_other_accounts_run_is_404_with_the_same_body(client: httpx.AsyncClient) -> None:
    """越权与不存在逐字同文案同状态码（项目不变量）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    run_id = await _start_gated_run(client, runner)

    main_module.app.dependency_overrides[consult_routes._session_dependency] = _auth_as(_OTHER_ACCOUNT)
    try:
        foreign = await client.post(f"/consult/runs/{run_id}/cancel")
        missing = await client.post(f"/consult/runs/{uuid.uuid4().hex}/cancel")
    finally:
        main_module.app.dependency_overrides[consult_routes._session_dependency] = _auth_as(_ACCOUNT)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    runner.gate.set()
    await drain_pumps()


# ---------------------------------------------------------------------------
# 5 应急入口
# ---------------------------------------------------------------------------


def _intake_items() -> list[dict[str, object]]:
    """八项现场采集的一份完整载荷（契约第 5 节的示例形状）。"""
    return [
        {"key": "medical_red_flags", "values": ["意识改变"], "skipped": False},
        {"key": "baseline_deviation", "value": "marked", "skipped": False},
        {"key": "communication", "value": "reduced", "skipped": False},
        {"key": "distress", "value": "高", "skipped": False},
        {"key": "sensory_environment", "values": ["噪音", "强光"], "skipped": False},
        {"key": "what_happened", "skipped": True},
        {"key": "primary_risk", "value": "medical", "skipped": False},
        {"key": "possible_pain", "value": "uncertain", "skipped": False},
    ]


async def test_emergency_builds_session_message_and_run_in_one_call(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一次调用完成建会话、落第一条消息、启动运行（契约第 5 节）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    object_id = await _make_object(_ACCOUNT, "小宝")
    # 记忆取数替身：本用例测的是装配（档案 + 记忆 + 八项 + 技能），不是图库查询。
    # 不替身时它会去连 FalkorDB——那会让「面装配得对不对」依赖另一个容器是否在跑。
    monkeypatch.setattr(
        consult_routes,
        "read_emergency_facts",
        _fake_memory_reader(EmergencyMemory(facts=[])),
    )

    response = await client.post(
        "/consult/emergency",
        json={"support_object_id": object_id, "items": _intake_items()},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["session_id"] and body["run_id"]
    await drain_pumps()

    request = runner.requests[-1]
    assert [skill.name for skill in request.activated] == ["emergency-consulting"], "应急是程序注入激活"
    sources = [item.source for item in request.injections.items]
    assert sources == ["emergency-profile", "emergency-memory"]
    assert request.injections.items[0].content.startswith(EMERGENCY_PROFILE_PREFIX)
    assert request.injections.items[1].content.startswith(EMERGENCY_MEMORY_PREFIX)
    assert request.user_input is not None
    assert request.user_input.startswith(EMERGENCY_INTAKE_PREFIX)
    assert "what_happened：已跳过（未排除）" in request.user_input

    # 会话真源里的第一条使用者消息就是渲染好的八项（八项是使用者填的表单）。
    async with session_scope(get_settings()) as db:
        items = await accounts_repo.read_all_items(db, session_id=body["session_id"])
    user_texts = [message_text(item.data) or "" for item in items if item.data.get("role") == "user"]
    assert user_texts and user_texts[0].startswith(EMERGENCY_INTAKE_PREFIX)

    # 归属、绑定与首轮注入结算都落了库。
    async with session_scope(get_settings()) as db:
        owner = await get_session_owner(db, session_id=body["session_id"])
        binding = (
            await db.execute(
                select(SessionObjectBinding).where(SessionObjectBinding.session_id == body["session_id"])
            )
        ).scalar_one_or_none()
    assert owner is not None and owner.account_id == _ACCOUNT
    assert binding is not None and str(binding.support_object_id) == object_id
    assert await _first_run_injected(body["session_id"]) is True


def _fake_memory_reader(memory: EmergencyMemory):  # noqa: ANN202 —— 返回替身协程函数
    """造一个「按给定结果返回」的记忆取数替身（签名与 `read_emergency_facts` 的后两参一致）。"""

    async def _reader(_session: object, _graph: object, _account_id: str) -> EmergencyMemory:
        return memory

    return _reader


async def test_emergency_marks_unavailable_memory_instead_of_empty_memory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """记忆取数失败时标注来源不可用，**不**注入一条「该账号还没有可用记忆」。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)

    def _raise(_settings: object = None) -> object:
        raise MemoryUnavailableError("图库不可用（测试）", operation="read_emergency_facts", cause="FalkorDB")

    monkeypatch.setattr(consult_routes, "get_shared_memory_graph", _raise)

    response = await client.post("/consult/emergency", json={"items": _intake_items()})
    assert response.status_code == 202, response.text
    await drain_pumps()

    request = runner.requests[-1]
    contents = [item.content for item in request.injections.ordered()]
    assert not [text for text in contents if text.startswith(EMERGENCY_MEMORY_PREFIX)]
    status = [text for text in contents if text.startswith("<unavailable_sources>")]
    assert len(status) == 1 and 'name="emergency-memory"' in status[0]


async def test_emergency_session_never_triggers_onboarding(client: httpx.AsyncClient) -> None:
    """应急会话永不触发引导（`RQ-EMG-03`）：它后续的消息走日常路径也不注入引导。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    emergency = await client.post("/consult/emergency", json={"items": _intake_items()})
    assert emergency.status_code == 202, emergency.text
    await drain_pumps()
    session_id = emergency.json()["session_id"]

    # 账号的引导仍未终结（应急不落引导状态），但本会话的首轮注入已结算。
    assert await _onboarding_state(_ACCOUNT) is None
    assert await _first_run_injected(session_id) is True

    follow_up = await _send(client, session_id, content="继续说", skill="daily-consulting")
    assert follow_up.status_code == 202, follow_up.text
    await drain_pumps()
    assert [skill.name for skill in runner.requests[-1].activated] == ["daily-consulting"]
    assert runner.requests[-1].injections.ordered() == ()


async def test_emergency_uses_the_default_object_when_omitted(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """省略对象时按支持对象第 6 节推导默认对象，档案注入用它取数。"""
    _install_runner(ScriptedRunner(get_settings()))
    object_id = await _make_object(_ACCOUNT, "默认对象")
    seen: dict[str, object] = {}

    async def _capture(_db: object, *, account_id: str, support_object_id: str | None):  # noqa: ANN202 —— 替身
        seen["account_id"] = account_id
        seen["support_object_id"] = support_object_id
        return None

    monkeypatch.setattr(consult_routes, "emergency_context", _capture)
    monkeypatch.setattr(consult_routes, "read_emergency_facts", _fake_memory_reader(EmergencyMemory(facts=[])))

    response = await client.post("/consult/emergency", json={"items": _intake_items()})
    assert response.status_code == 202, response.text
    await drain_pumps()
    assert seen["account_id"] == _ACCOUNT
    assert seen["support_object_id"] == object_id

    async with session_scope(get_settings()) as db:
        binding = (
            await db.execute(
                select(SessionObjectBinding).where(SessionObjectBinding.session_id == response.json()["session_id"])
            )
        ).scalar_one_or_none()
    assert binding is not None and str(binding.support_object_id) == object_id


async def test_emergency_with_foreign_or_archived_object_is_404_with_the_same_message(
    client: httpx.AsyncClient,
) -> None:
    """越权对象与已归档对象都是 404，且与「对象不存在」逐字同文案。"""
    foreign = await _make_object(_OTHER_ACCOUNT, "别人的孩子")
    archived = await _make_object(_ACCOUNT, "已归档")
    async with session_scope(get_settings()) as db:
        await archive_object(db, account_id=_ACCOUNT, support_object_id=archived)

    for object_id in (foreign, archived, str(uuid.uuid4())):
        response = await client.post(
            "/consult/emergency",
            json={"support_object_id": object_id, "items": _intake_items()},
        )
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == OBJECT_NOT_ACCESSIBLE_MESSAGE


async def test_emergency_rejects_unknown_keys_and_bad_shapes(client: httpx.AsyncClient) -> None:
    """载荷不合法一律 422（契约第 2 节的 422 行）。"""
    _install_runner(ScriptedRunner(get_settings()))
    cases = (
        {"items": []},
        {"items": [{"key": "no_such_item", "value": "x", "skipped": False}]},
        {"items": [{"key": "medical_red_flags", "value": "意识改变", "skipped": False}]},
        {"items": [{"key": "distress", "value": "高", "skipped": True}]},
        {"items": [{"key": "distress", "value": "高", "skipped": False}, {"key": "distress", "value": "低"}]},
        {"unknown_field": 1, "items": _intake_items()},
    )
    for payload in cases:
        response = await client.post("/consult/emergency", json=payload)
        assert response.status_code == 422, (payload, response.status_code, response.text)


# ---------------------------------------------------------------------------
# 6 引导跳过入口
# ---------------------------------------------------------------------------


async def test_skip_sets_skipped_and_is_idempotent(client: httpx.AsyncClient) -> None:
    """跳过写入 `skipped`；重复调用仍 200 且状态不变（契约第 6 节的幂等）。"""
    _install_runner(ScriptedRunner(get_settings()))
    session_id = await _create_session(client)

    first = await client.post(f"/consult/sessions/{session_id}/onboarding/skip")
    assert first.status_code == 200, first.text
    assert first.json() == {"state": ONBOARDING_SKIPPED}
    assert await _onboarding_state(_ACCOUNT) == ONBOARDING_SKIPPED

    second = await client.post(f"/consult/sessions/{session_id}/onboarding/skip")
    assert second.status_code == 200, second.text
    assert second.json() == {"state": ONBOARDING_SKIPPED}

    # 跳过之后新会话的 `onboarding_pending` 为假，第一次运行也不注入引导。
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    created = await client.post("/consult/sessions", json={})
    assert created.json()["onboarding_pending"] is False
    assert (await _send(client, created.json()["session_id"], content="你好")).status_code == 202
    await drain_pumps()
    assert runner.requests[-1].injections.ordered() == ()


async def test_skip_does_not_overwrite_completed(client: httpx.AsyncClient) -> None:
    """已 `completed` 时跳过不代写：仍 200，但返回并保持 `completed`（两条通道互不代写）。"""
    _install_runner(ScriptedRunner(get_settings()))
    async with session_scope(get_settings()) as db:
        await complete_onboarding(db, account_id=_ACCOUNT)
    session_id = await _create_session(client)

    response = await client.post(f"/consult/sessions/{session_id}/onboarding/skip")
    assert response.status_code == 200, response.text
    assert response.json() == {"state": ONBOARDING_COMPLETED}
    assert await _onboarding_state(_ACCOUNT) == ONBOARDING_COMPLETED


async def test_skip_other_accounts_session_is_404_with_the_same_body(client: httpx.AsyncClient) -> None:
    """会话归属是跳过的前置凭据：别人的会话与不存在的会话同文案同码。"""
    _install_runner(ScriptedRunner(get_settings()))
    session_id = await _create_session(client)

    main_module.app.dependency_overrides[consult_routes._session_dependency] = _auth_as(_OTHER_ACCOUNT)
    try:
        foreign = await client.post(f"/consult/sessions/{session_id}/onboarding/skip")
        missing = await client.post(f"/consult/sessions/{uuid.uuid4().hex}/onboarding/skip")
    finally:
        main_module.app.dependency_overrides[consult_routes._session_dependency] = _auth_as(_ACCOUNT)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert await _onboarding_state(_ACCOUNT) is None, "越权请求不得改动别人的引导状态"


async def test_skip_does_not_cancel_a_running_run(client: httpx.AsyncClient) -> None:
    """跳过只写状态，不取消正在跑的运行（契约第 6 节末行）。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)
    runner.gate = asyncio.Event()
    started = await _send(client, session_id, content="跑起来")
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]

    skipped = await client.post(f"/consult/sessions/{session_id}/onboarding/skip")
    assert skipped.status_code == 200, skipped.text

    cache = RedisCache(get_settings().redis_url)
    try:
        assert await cache.get(mutex_key(session_id)) is not None, "跳过不得释放会话位（运行还在跑）"
    finally:
        await cache.aclose()
    busy = await _send(client, session_id, content="再发一条")
    assert busy.status_code == 409, busy.text

    runner.gate.set()
    await drain_pumps()
    assert (await client.post(f"/consult/runs/{run_id}/cancel")).status_code == 409
