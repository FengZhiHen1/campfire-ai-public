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
from campfire.modules.accounts.models import CampfireOnboarding, CampfireSession
from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields
from campfire.modules.accounts.session_repository import get_session_owner
from campfire.modules.profile import archive_object, create_object
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.models import SessionObjectBinding, SupportObject
from campfire.surfaces.consult import assembly as consult_assembly
from campfire.surfaces.consult import routes as consult_routes
from campfire.surfaces.consult.runbus import cancel_pumps, drain_pumps, events_key, mutex_key

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

    它同时承担真实运行的一件事：把使用者消息写进 SDK 会话真源。少了它，
    「幂等不重复追加」「并发被拒时不追加」两条断言就没有可观测对象。
    """

    def __init__(
        self,
        settings: Settings,
        *,
        deltas: Sequence[str] = ("这是测试回复。",),
        startup_delay: float = 0.0,
        fail_before_start: bool = False,
        append_user_message: bool = True,
    ) -> None:
        """绑定配置与脚本参数。"""
        self._settings = settings
        self._deltas = tuple(deltas)
        self._startup_delay = startup_delay
        self._fail_before_start = fail_before_start
        self._append_user_message = append_user_message
        #: 本次进程内真正启动过的运行（并发用例据此断言「只起了一次」）。
        self.started: list[str] = []
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
        if self._append_user_message:
            sdk = build_sqlalchemy_session(request.session_id, engine=get_engine(self._settings))
            await sdk.add_items([{"role": "user", "content": request.user_input or ""}])  # type: ignore[arg-type]  # SDK 的 add_items 收 SDK 自有条目类型，测试传字面量 dict

        yield RunStartedEvent(
            run_id=run_id,
            session_id=request.session_id,
            surface=request.surface,
            model="scripted",
            activated_skills=tuple(skill.name for skill in request.activated),
            injection_sources=(),
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
    """`skill` 必须是已注册技能（裁决 11）；已注册时该次运行程序注入它。"""
    runner = ScriptedRunner(get_settings())
    _install_runner(runner)
    session_id = await _create_session(client)

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
    ):
        response = await client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 401, (method, path, response.status_code, response.text)
    assert (await client.get("/health")).status_code in (200, 503)
