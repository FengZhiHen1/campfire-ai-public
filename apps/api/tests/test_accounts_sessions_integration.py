"""会话归属数据链（真实 PostgreSQL + 真实 SDK 会话存储）。

对应 `docs/技术设计/decisions/会话归属单立表归accounts.md`、
`docs/技术设计/面/consult/HTTP与SSE契约.md` 第 3.2／3.3 节、
`docs/项目结构设计.md` 第 6／10 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_accounts_sessions_integration.py

这里钉住的四类事（都不是「实现细节的回归」）：

1. 归属判定：不存在与属主不符必须逐字同文案。区分二者等于提供会话枚举通道
   （与 T02 的 `core/authz` 同一纪律，支持对象 5.3）。
2. 登记幂等且属主不可变：重复登记是正常路径（会话创建会被重试），换属主是错误
   ——允许改属主等于允许把别人的会话据为己有。
3. 列表与水合：游标分页边界、空列表、无消息行的会话（标题回退）、注入消息不算
   首条使用者消息、真实 SDK 落库的条目能被水合出来。
4. SDK 两表与迁移的一致性：本文件把 SDK 自己建的表反射出来，与
   `core/db/sdk_session.py` 的声明逐列比对——两侧不一致时 `--autogenerate`
   会提议改列迁移，而改 SDK 的表正是决策记录否决过的做法。

为什么用真实 SDK 落库，而不是手写 `INSERT`：

手写 JSON 只能验证「我按自己设想的形状解析」。真实 SDK 的条目形状是外部契约，
本任务实测过它与设想有出入（使用者消息没有 `type` 字段、助手消息的 content 是分片
数组、思考文本在 `summary` 里）。因此关键用例（`test_hydration_...sdk...`）走
`SQLAlchemySession.add_items` 真实落库，再经我们的读取路径读回。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, inspect, text

from campfire.core.config import get_settings
from campfire.core.db import session_scope, to_sync_url
from campfire.core.db.sdk_session import (
    SDK_MESSAGES_INDEX_NAME,
    SDK_MESSAGES_TABLE_NAME,
    SDK_SESSIONS_TABLE_NAME,
    AgentMessage,
    AgentSession,
)
from campfire.modules.accounts import session_repository as repo
from campfire.modules.accounts.errors import (
    SessionNotFoundError,
    SessionQueryError,
    SessionRegistrationError,
)
from campfire.modules.accounts.models import CampfireSession
from campfire.modules.accounts.session_items import TITLE_FALLBACK, TITLE_MAX_CHARS
from campfire.modules.accounts.sessions import (
    SessionAccountPurger,
    decode_cursor,
    encode_cursor,
    list_sessions,
    load_history,
    register_session,
    require_session_owner,
    validate_limit,
)

# 本文件必须能构造真实的 SDK 会话对象，而 `openai` 的客户端构造在宿主机 `no_proxy`
# 含带方括号的 IPv6 字面量时会抛 `InvalidURL`（见 `conftest.py` 的说明）。`conftest`
# 的 autouse 夹具会覆盖它，但那个夹具在测试函数执行前生效，而模块级导入不会——
# 因此模块级不构造任何客户端，构造都发生在用例体内。

pytestmark = pytest.mark.integration

#: 本文件写入的账号标识前缀。按它清理自己的行（不按 id 清，避免漏掉中途失败留下的记录）。
_ACCOUNT = "it_sessions_account"

#: 第二个账号：越权用例的「别人」。
_OTHER_ACCOUNT = "it_sessions_other"

#: 会话标识前缀。
_SESSION_PREFIX = "it-sessions-"


def _session_id(suffix: str) -> str:
    """造一个本文件专用的会话标识（加随机后缀避免跨轮次残留相互影响）。"""
    return f"{_SESSION_PREFIX}{suffix}-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过（仓库既有集成测试的统一做法）。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    """清掉本文件写入的行：前后各一次，避免跨轮次残留互相干扰。

    按账号前缀过滤，不做无过滤全表删除（2026-09-30 实测的真实缺陷）：
    并发跑的另外两个集成测试文件曾因各自做全表删除而互相删掉对方刚写入的行，
    症状是随机失败。这里把范围收窄到本文件的账号标识。

    SDK 的两张表按会话标识前缀清：归属行删掉后 SDK 表里的行仍在（两者无外键关系
    ——那是决策记录的要求：归位判定的权威是 `campfire_session`，不靠 SDK 表的存在性）。
    """
    await _purge()
    yield
    await _purge()


async def _purge() -> None:
    """删除本文件的账号与以本文件前缀命名的会话。"""
    async with session_scope(get_settings()) as session:
        await session.execute(delete(CampfireSession).where(CampfireSession.account_id.in_([_ACCOUNT, _OTHER_ACCOUNT])))
        await session.execute(delete(AgentMessage).where(AgentMessage.session_id.like(f"{_SESSION_PREFIX}%")))
        await session.execute(delete(AgentSession).where(AgentSession.session_id.like(f"{_SESSION_PREFIX}%")))


async def _register(session_id: str, account_id: str = _ACCOUNT) -> None:
    """登记一个会话（已提交）。"""
    async with session_scope(get_settings()) as session:
        await register_session(session, session_id=session_id, account_id=account_id)


async def _add_sdk_items(session_id: str, items: list[dict]) -> None:
    """用真实 SDK 的会话对象把条目落库。

    直接 `INSERT` 会绕过 SDK 的序列化（`json.dumps` 的确切写法），只能验证「我按自己
    设想的形状解析」。走 SDK 才证明我们的读取路径认得的就是它写下的东西。
    """
    from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession

    from campfire.core.db import get_engine

    sdk_session = SQLAlchemySession(session_id, engine=get_engine(get_settings()), create_tables=False)
    # 传的是测试构造的 JSON 条目（故意保留原始形状）；SDK 收的是它自有的条目类型联合
    await sdk_session.add_items(items)  # type: ignore[arg-type]  # SDK 的自有类型是 30 多个 TypedDict 的联合，测试这里就是要喂原始 JSON 形状


async def _list(
    *,
    account_id: str = _ACCOUNT,
    cursor: object = None,
    limit: object = None,
    reader=None,  # noqa: ANN001 —— 可选的对象名回调，签名见 sessions.ObjectNameReader
):
    """对账跑一次 `list_sessions`（打开一个只读会话）。"""
    async with session_scope(get_settings()) as session:
        return await list_sessions(
            session,
            account_id=account_id,
            cursor=cursor,
            limit=limit,
            object_name_reader=reader,
        )


# ---------------------------------------------------------------------------
# 一、归属判定：不存在与越权不可区分
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_foreign_session_and_missing_session_have_identical_message() -> None:
    """核心用例：会话不存在与会话属于别人，必须抛出逐字相同的消息。

    区分二者等于提供会话枚举通道——攻击者据此可以确认某个 `session_id` 是否真实存在
    （支持对象 5.3 同一条纪律）。判据是两条消息字符串相等，而不只是「都抛了错」。
    """
    foreign = _session_id("foreign")
    await _register(foreign, _OTHER_ACCOUNT)
    missing = _session_id("missing")

    async with session_scope(get_settings()) as session:
        with pytest.raises(SessionNotFoundError) as foreign_exc:
            await require_session_owner(session, session_id=foreign, account_id=_ACCOUNT)

    async with session_scope(get_settings()) as session:
        with pytest.raises(SessionNotFoundError) as missing_exc:
            await require_session_owner(session, session_id=missing, account_id=_ACCOUNT)

    assert str(foreign_exc.value) == str(missing_exc.value)
    assert SessionNotFoundError.MESSAGE in str(foreign_exc.value)


@pytest.mark.asyncio
async def test_owner_passes_ownership_check() -> None:
    """正向控制：属主自己必须通过——否则上面的「都失败」可能只是因为判定永远失败。"""
    session_id = _session_id("own")
    await _register(session_id)

    async with session_scope(get_settings()) as session:
        await require_session_owner(session, session_id=session_id, account_id=_ACCOUNT)


@pytest.mark.asyncio
async def test_ownership_check_rejects_empty_and_oversized_ids() -> None:
    """形状不合法的标识显式报错，不落进「查不到行」的伪装。

    空标识在等值查询里必然查不到行，而「查不到行」的语义是「不属于你」——于是
    调用方错误会被伪装成一个合法的越权判定。超宽值则会让驱动抛裸 `DBAPIError`。
    """
    async with session_scope(get_settings()) as session:
        with pytest.raises(SessionQueryError):
            await require_session_owner(session, session_id="   ", account_id=_ACCOUNT)
        with pytest.raises(SessionQueryError):
            await require_session_owner(session, session_id="x" * 200, account_id=_ACCOUNT)
        with pytest.raises(SessionQueryError):
            await require_session_owner(session, session_id=_session_id("ok"), account_id="")


# ---------------------------------------------------------------------------
# 二、登记：幂等与属主不可变
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_is_idempotent_for_same_owner() -> None:
    """核心用例：同一属主重复登记是无操作，不报错、不产生第二行。

    会话创建路径可能被重试，因此重复登记是正常路径（第一次插、第二次空转）。
    判据同时看返回值（`created` 标志）与库里的行数（只有一行）。
    """
    session_id = _session_id("idem")

    async with session_scope(get_settings()) as session:
        first = await register_session(session, session_id=session_id, account_id=_ACCOUNT)
    async with session_scope(get_settings()) as session:
        second = await register_session(session, session_id=session_id, account_id=_ACCOUNT)

    assert first.created is True, "第一次登记必须真的插入"
    assert second.created is False, "第二次登记必须是无操作"
    assert first.session_id == second.session_id == session_id

    async with session_scope(get_settings()) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM campfire_session WHERE session_id = :sid"), {"sid": session_id}
            )
        ).scalar_one()
    assert rows == 1, "重复登记不得产生第二行"


@pytest.mark.asyncio
async def test_register_rejects_different_owner_and_keeps_original() -> None:
    """核心用例：换属主必须报错，且既有行不被修改。

    允许改属主等于允许把别人的会话据为己有——一次会话标识猜测就能把对方的会话
    挂到自己名下，整张归属表的意义随之消失。因此这里既断言抛错，也断言原属主未变
    （只断言抛错的话，一个「先改再报错」的实现也会通过）。
    """
    session_id = _session_id("immutable")
    await _register(session_id, _ACCOUNT)

    async with session_scope(get_settings()) as session:
        with pytest.raises(SessionRegistrationError):
            await register_session(session, session_id=session_id, account_id=_OTHER_ACCOUNT)

    async with session_scope(get_settings()) as session:
        owner = await repo.get_session_owner(session, session_id=session_id)

    assert owner is not None
    assert owner.account_id == _ACCOUNT, "属主必须保持不变——不允许改属主"


@pytest.mark.asyncio
async def test_register_survives_concurrent_attempts() -> None:
    """并发登记同一会话：只有一个真的插入，另一个走无操作分支（不得抛完整性异常）。

    `ON CONFLICT DO NOTHING` 的判据在此：若实现写成「先查后插」，并发下会有一个请求
    撞主键冲突并抛裸 `IntegrityError`（而不是 `created=False`）。
    """
    import asyncio

    session_id = _session_id("race")

    async def attempt() -> bool:
        async with session_scope(get_settings()) as session:
            result = await register_session(session, session_id=session_id, account_id=_ACCOUNT)
            return result.created

    results = await asyncio.gather(*(attempt() for _ in range(4)))

    assert sum(1 for created in results if created) == 1, f"恰好一个请求应真的插入，实测 {results}"
    async with session_scope(get_settings()) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM campfire_session WHERE session_id = :sid"), {"sid": session_id}
            )
        ).scalar_one()
    assert rows == 1


# ---------------------------------------------------------------------------
# 三、会话列表
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_session_list_returns_no_items_and_no_cursor() -> None:
    """对抗用例：没有会话时返回空列表与 `None` 游标（不是错误）。"""
    page = await _list(account_id=f"{_ACCOUNT}-nobody")

    assert page.items == []
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_list_only_returns_own_sessions() -> None:
    """列表按账号过滤——别人的会话不得出现（越权在列表侧同样要挡住）。"""
    mine = _session_id("mine")
    theirs = _session_id("theirs")
    await _register(mine, _ACCOUNT)
    await _register(theirs, _OTHER_ACCOUNT)

    page = await _list()

    ids = [item.session_id for item in page.items]
    assert mine in ids
    assert theirs not in ids


@pytest.mark.asyncio
async def test_title_falls_back_for_session_without_messages() -> None:
    """对抗用例：SDK 表里没有消息行的会话（刚建、还没发过消息）→ 标题回退。

    这是会话归属行先于消息落库的直接结果（决策记录的创建时机）。此时标题、预览都
    没有可用数据，但该会话必须出现在列表里——否则「刚建的会话不见了」。
    """
    session_id = _session_id("nomessages")
    await _register(session_id)

    page = await _list()

    item = next(entry for entry in page.items if entry.session_id == session_id)
    assert item.title == TITLE_FALLBACK
    assert item.last_message_preview is None
    # 缺 SDK 行时活动时间退回登记时间，必须非空——否则排序键为 NULL。
    assert item.updated_at is not None


@pytest.mark.asyncio
async def test_injected_messages_do_not_become_the_title() -> None:
    """核心用例：标题取首条使用者消息，跳过先落库的应用注入消息。

    实测注入消息与使用者消息同角色（都是 `user`），只能靠内容前缀区分。取错的话
    会话列表会显示一段技能目录当标题。
    """
    session_id = _session_id("inject")
    await _register(session_id)
    await _add_sdk_items(
        session_id,
        [
            {"role": "user", "content": '<available_skills>\n  <skill name="daily-consulting" />\n</available_skills>'},
            {"role": "user", "content": "<tool_availability>\n</tool_availability>"},
            {"role": "user", "content": "孩子最近晚上不肯睡"},
            {"role": "assistant", "content": [{"type": "output_text", "text": "我们看看作息。"}]},
        ],
    )

    page = await _list()

    item = next(entry for entry in page.items if entry.session_id == session_id)
    assert item.title == "孩子最近晚上不肯睡"
    assert item.last_message_preview == "我们看看作息。"


@pytest.mark.asyncio
async def test_title_is_truncated_to_24_chars() -> None:
    """标题取前 24 字符 + 省略号（裁决 5），且是单行。"""
    session_id = _session_id("longtitle")
    await _register(session_id)
    await _add_sdk_items(session_id, [{"role": "user", "content": "一" * 40}])

    page = await _list()

    item = next(entry for entry in page.items if entry.session_id == session_id)
    assert item.title == "一" * TITLE_MAX_CHARS + "…"


@pytest.mark.asyncio
async def test_cursor_pagination_covers_every_session_exactly_once() -> None:
    """核心用例：游标翻页必须不重不漏地覆盖全部会话。

    造 5 个会话、每页 2 条，逐页翻完，断言「拿到的标识集合 == 全部标识集合」且
    没有重复。这一条同时覆盖两件事：排序键是全序（撞值时不会漏行）、游标比较
    的方向正确（写反会立刻死循环或漏掉一整页）。
    """
    created = [_session_id(f"page{i}") for i in range(5)]
    for session_id in created:
        await _register(session_id)

    collected: list[str] = []
    cursor: object = None
    pages = 0
    while True:
        page = await _list(cursor=cursor, limit=2)
        collected.extend(item.session_id for item in page.items)
        pages += 1
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
        assert pages < 10, "翻页没有终止——游标比较方向可能写反"

    # 只统计本文件的会话：库里可能有其它测试文件留下的行。
    mine = [session_id for session_id in collected if session_id.startswith(_SESSION_PREFIX)]
    assert sorted(mine) == sorted(created), "翻页必须覆盖全部会话"
    assert len(mine) == len(set(mine)), "翻页不得重复返回同一会话"


@pytest.mark.asyncio
async def test_cursor_boundary_when_total_is_exact_multiple_of_limit() -> None:
    """边界用例：总条数恰好是 `limit` 的整数倍时，最后一页不得丢最后一条。

    上一页取满 `limit` 条时会给出 `next_cursor`（实现不预判「还有没有」），因此这里
    翻到空页才算结束。若实现改用「取 limit+1 条判断是否还有」而写错了边界，
    最后一条会消失——这正是要钉住的。
    """
    exact = [_session_id(f"exact{i}") for i in range(4)]
    for session_id in exact:
        await _register(session_id)

    seen: list[str] = []
    cursor: object = None
    while True:
        page = await _list(cursor=cursor, limit=2)
        seen.extend(item.session_id for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    mine = [session_id for session_id in seen if session_id.startswith(f"{_SESSION_PREFIX}exact")]
    assert sorted(mine) == sorted(exact), "恰好整除时不得丢掉最后一条"


@pytest.mark.asyncio
async def test_list_orders_by_most_recent_activity() -> None:
    """列表按最近活动时间倒序（刚聊过的在最前）。

    判据用真实 SDK 落库（它会刷新 `agent_sessions.updated_at`），而不是直接改
    时间戳——直接改就绕过了「活动时间从 SDK 表来」这条设计。
    """
    older = _session_id("older")
    newer = _session_id("newer")
    await _register(older)
    await _register(newer)
    # 先给 older 写消息，再给 newer 写，让 newer 的活动时间更晚。
    await _add_sdk_items(older, [{"role": "user", "content": "早的"}])
    await _add_sdk_items(newer, [{"role": "user", "content": "晚的"}])

    page = await _list()

    mine = [item.session_id for item in page.items if item.session_id in {older, newer}]
    assert mine == [newer, older], f"应按最近活动时间倒序，实测 {mine}"


@pytest.mark.asyncio
async def test_object_name_reader_is_injected_not_imported() -> None:
    """对象名经注入回调取；未注入时为 `None`（不是错误）。

    accounts 不得 import profile（模块之间禁止互相 import，项目结构设计第 7 节），
    因此这条数据只能由装配处注入。未注入时字段为 `None`——列表页对缺失字段的处理是
    不渲染该行，不是报错。
    """
    session_id = _session_id("objname")
    await _register(session_id)

    page_without = await _list()
    item_without = next(entry for entry in page_without.items if entry.session_id == session_id)
    assert item_without.support_object_name is None

    async def reader(session_ids: list[str]) -> dict[str, str]:
        return {sid: "小宝" for sid in session_ids if sid == session_id}

    page_with = await _list(reader=reader)
    item_with = next(entry for entry in page_with.items if entry.session_id == session_id)
    assert item_with.support_object_name == "小宝"


def test_limit_validation_rejects_out_of_range() -> None:
    """条数上界显式拒绝而不是静默截断（契约第 3.2 节：默认 20、上限 50）。"""
    assert validate_limit(None) == repo.LIST_DEFAULT_LIMIT
    assert validate_limit(1) == 1
    assert validate_limit(repo.LIST_MAX_LIMIT) == repo.LIST_MAX_LIMIT

    for bad in (0, -1, repo.LIST_MAX_LIMIT + 1, "20", 2.5, True):
        with pytest.raises(SessionQueryError):
            validate_limit(bad)


def test_cursor_round_trip_and_rejections() -> None:
    """游标编码/解析：往返一致，非法输入显式报错（不静默回退到首页）。

    静默回退会让调用方在触底分页里反复拿到第一页并以为「刷新了」，于是无限循环。
    """
    marker = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

    assert decode_cursor(None) is None
    assert decode_cursor("") is None
    assert decode_cursor(encode_cursor(marker, "s-1")) == (marker, "s-1")

    for bad in ("不是 base64!!", "YWJj", 123, "e30", "eyJ2IjoxLCJ0Ijoibm90LWEtdGltZSIsInMiOiJ4In0"):
        with pytest.raises(SessionQueryError):
            decode_cursor(bad)


# ---------------------------------------------------------------------------
# 四、历史水合
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_history_rejects_foreign_and_missing_with_same_error() -> None:
    """水合的越权判定与归属判定同文案（契约第 3.3 节：不得暴露会话是否存在）。"""
    foreign = _session_id("hforeign")
    await _register(foreign, _OTHER_ACCOUNT)

    async with session_scope(get_settings()) as session:
        with pytest.raises(SessionNotFoundError) as foreign_exc:
            await load_history(session, session_id=foreign, account_id=_ACCOUNT)
    async with session_scope(get_settings()) as session:
        with pytest.raises(SessionNotFoundError) as missing_exc:
            await load_history(session, session_id=_session_id("hmissing"), account_id=_ACCOUNT)

    assert str(foreign_exc.value) == str(missing_exc.value)


@pytest.mark.asyncio
async def test_load_history_distinguishes_empty_from_failure() -> None:
    """核心用例：真的没有消息 → 空列表（200）；归属不成立 → 抛错（404）。

    契约第 3.3 节要求「水合失败显示错误与重试，不显示空对话冒充成功」。两个结果
    必须在数据层就分开——若失败也返回 `messages=[]`，面层无法分辨，只能猜。
    """
    empty = _session_id("hempty")
    await _register(empty)

    async with session_scope(get_settings()) as session:
        history = await load_history(session, session_id=empty, account_id=_ACCOUNT)

    assert history.session_id == empty
    assert history.messages == []


@pytest.mark.asyncio
async def test_load_history_hydrates_real_sdk_items() -> None:
    """核心用例：真实 SDK 落库的条目能被水合成契约第 3.3 节的形状。

    走真实 `SQLAlchemySession.add_items`（外部契约的形状），覆盖四件事：
    注入消息被排除、使用者消息的字符串 content、助手消息的分片数组 content、
    以及水合的顺序。
    """
    session_id = _session_id("hydrate")
    await _register(session_id)
    await _add_sdk_items(
        session_id,
        [
            {"role": "user", "content": '<available_skills>\n  <skill name="x" />\n</available_skills>'},
            {"role": "user", "content": "你好，第一次。"},
            {"role": "assistant", "content": [{"type": "output_text", "text": "第一轮回答。"}]},
        ],
    )

    async with session_scope(get_settings()) as session:
        history = await load_history(session, session_id=session_id, account_id=_ACCOUNT)

    assert [message["role"] for message in history.messages] == ["user", "assistant"]
    assert history.messages[0]["parts"] == [{"type": "text", "text": "你好，第一次。"}]
    # 分片数组形状必须被取到文本（只认字符串的实现会让这条助手消息消失）。
    assert history.messages[1]["parts"] == [{"type": "text", "text": "第一轮回答。"}]
    # 消息 id 取自行标识（真源里的稳定值）。
    assert all(message["id"].isdigit() for message in history.messages)


@pytest.mark.asyncio
async def test_load_history_is_read_only_for_sdk_tables() -> None:
    """水合不得改写 SDK 的表（约束：只读 + 迁移建表）。

    判据：水合前后 SDK 两张表的行数与内容逐行相同。若实现顺手「规范化」写入
    （例如补 `type` 字段），行数可能不变而内容变了——因此比对内容而不仅是行数。
    """
    session_id = _session_id("readonly")
    await _register(session_id)
    await _add_sdk_items(session_id, [{"role": "user", "content": "问"}])

    before = await _snapshot_sdk_tables(session_id)
    async with session_scope(get_settings()) as session:
        await load_history(session, session_id=session_id, account_id=_ACCOUNT)
    after = await _snapshot_sdk_tables(session_id)

    assert before == after, "水合不得修改 SDK 会话表的任何一行"


async def _snapshot_sdk_tables(session_id: str) -> list[tuple]:
    """取某会话在 SDK 两张表里的全部行（用于「只读」断言）。"""
    async with session_scope(get_settings()) as session:
        sessions = (
            await session.execute(
                text(
                    "SELECT session_id, created_at, updated_at FROM agent_sessions "
                    "WHERE session_id = :sid ORDER BY session_id"
                ),
                {"sid": session_id},
            )
        ).all()
        messages = (
            await session.execute(
                text(
                    "SELECT id, session_id, message_data, created_at FROM agent_messages "
                    "WHERE session_id = :sid ORDER BY id"
                ),
                {"sid": session_id},
            )
        ).all()
    return [tuple(row) for row in sessions] + [tuple(row) for row in messages]


# ---------------------------------------------------------------------------
# 五、注销清除
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purger_deletes_ownership_rows_and_is_idempotent() -> None:
    """注销清除者真删该账号的归属行，且重复调用不报错（幂等）。"""
    mine = _session_id("purge")
    theirs = _session_id("purgeother")
    await _register(mine, _ACCOUNT)
    await _register(theirs, _OTHER_ACCOUNT)

    purger = SessionAccountPurger(get_settings())
    first = await purger.purge_account(_ACCOUNT)
    second = await purger.purge_account(_ACCOUNT)

    assert purger.name == "session-owner"
    assert "1" in first.detail, f"应报告删了 1 条，实测 {first.detail!r}"
    assert "0" in second.detail, f"第二次应报告删了 0 条，实测 {second.detail!r}"

    async with session_scope(get_settings()) as session:
        gone = await repo.get_session_owner(session, session_id=mine)
        # 别人的行不受影响——清除按账号隔离。
        kept = await repo.get_session_owner(session, session_id=theirs)

    assert gone is None
    assert kept is not None


@pytest.mark.asyncio
async def test_purged_account_fails_ownership_check_closed() -> None:
    """清除后归属判定必须拒绝（fail-closed），而不是「查不到就放行」。

    认证与账号第 8 节第 4 步：删掉归属行是 fail-closed——在途的订阅与取消请求随后
    一律判定为 404。
    """
    session_id = _session_id("closed")
    await _register(session_id, _ACCOUNT)
    await SessionAccountPurger(get_settings()).purge_account(_ACCOUNT)

    async with session_scope(get_settings()) as session:
        with pytest.raises(SessionNotFoundError):
            await require_session_owner(session, session_id=session_id, account_id=_ACCOUNT)


# ---------------------------------------------------------------------------
# 六、SDK 两表与迁移的一致性（白名单登记的意义所在）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sdk_tables_exist_and_were_created_by_migration() -> None:
    """SDK 两表必须存在，且由迁移建出——判据是它们的列注释。

    为什么这条用例有判别性：`SQLAlchemySession(create_tables=True)` 也能建出同名表，
    但那是 SDK 自建、没有业务注释。迁移建的带中文注释（见 `core/db/sdk_session.py`
    的 `comment=` 与迁移文件）。因此「表存在」不足以证明迁移生效，注释才是判据。

    刻意不断言具体的 revision 号：那会让下一个迁移落地时本用例无条件失败
    （跨任务的脆弱耦合），而它要证明的事（迁移建了这两张表）已由注释证明。
    只断言库确实处于 Alembic 管理之下。
    """
    from sqlalchemy import create_engine

    url = get_settings().database_url
    assert url, "未配置 DATABASE_URL"
    engine = create_engine(to_sync_url(url))
    try:
        inspector = inspect(engine)
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        comments = {
            table: inspector.get_table_comment(table).get("text")
            for table in (SDK_SESSIONS_TABLE_NAME, SDK_MESSAGES_TABLE_NAME)
        }
        indexes = {index["name"] for index in inspector.get_indexes(SDK_MESSAGES_TABLE_NAME)}
    finally:
        engine.dispose()

    assert comments[SDK_SESSIONS_TABLE_NAME], "agent_sessions 缺少迁移写入的业务注释——可能是 SDK 自建的表"
    assert comments[SDK_MESSAGES_TABLE_NAME], "agent_messages 缺少迁移写入的业务注释"
    assert SDK_MESSAGES_INDEX_NAME in indexes, f"缺少 SDK 使用的索引名 {SDK_MESSAGES_INDEX_NAME}"
    assert version, "库不在 Alembic 管理之下——迁移没有跑过"


@pytest.mark.asyncio
async def test_declared_sdk_models_match_the_real_tables() -> None:
    """核心一致性用例：`core/db/sdk_session.py` 的声明必须与真实表逐列一致。

    两侧不一致时 `--autogenerate` 会提议改列迁移，而改 SDK 的表正是决策记录否决过的
    做法（会把业务字段塞进框架表、SDK 升级牵连）。因此这条用例是「登记进白名单」
    这个动作的安全网：它把声明的形状与真源（库里实存的表）比对。

    比对的判据：列名集合、主键、可空性、外键的 `ondelete`、索引列。
    """
    from typing import cast

    from sqlalchemy import Table, create_engine

    url = get_settings().database_url
    assert url, "未配置 DATABASE_URL"
    engine = create_engine(to_sync_url(url))
    try:
        inspector = inspect(engine)
        for model in (AgentSession, AgentMessage):
            table = model.__tablename__
            # `declarative_base().__table__` 的静态类型是 `FromClause`（SQLAlchemy 存根
            # 未按声明式模型收窄），而这里要用的 `primary_key` / `indexes` 只在 `Table` 上。
            # 真跑时它确实是 `Table`（声明式模型必然由 Table 承载），故此处收窄而非改判据。
            declared_table = cast(Table, model.__table__)
            actual_columns = {column["name"]: column for column in inspector.get_columns(table)}
            declared_columns = {column.name: column for column in declared_table.columns}

            assert set(actual_columns) == set(declared_columns), (
                f"{table} 的列集合与声明不符：库里 {sorted(actual_columns)}，声明 {sorted(declared_columns)}"
            )
            for name, declared in declared_columns.items():
                actual = actual_columns[name]
                assert actual["nullable"] == declared.nullable, f"{table}.{name} 的可空性与声明不符"

            assert set(inspector.get_pk_constraint(table)["constrained_columns"]) == {
                column.name for column in declared_table.primary_key.columns
            }, f"{table} 的主键与声明不符"

            actual_fks = {
                (fk["constrained_columns"][0], fk["referred_table"], fk["options"].get("ondelete"))
                for fk in inspector.get_foreign_keys(table)
            }
            declared_fks = {(fk.parent.name, fk.column.table.name, fk.ondelete) for fk in declared_table.foreign_keys}
            assert actual_fks == declared_fks, f"{table} 的外键与声明不符：{actual_fks} vs {declared_fks}"

            actual_indexes = {(index["name"], tuple(index["column_names"])) for index in inspector.get_indexes(table)}
            declared_indexes = {
                (index.name, tuple(column.name for column in index.columns)) for index in declared_table.indexes
            }
            assert actual_indexes == declared_indexes, f"{table} 的索引与声明不符"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_created_at_semantics_are_utc_consistent() -> None:
    """SDK 的裸时间戳按 UTC 解释后，与归属行的带时区时间可比。

    这条钉住的是跨表比较的正确性：SDK 的 `updated_at` 是 `timestamp without time
    zone`，而归属行的 `created_at` 带时区。若读取侧不做 `timezone('UTC', …)`，
    排序结果会依赖数据库会话时区——本机是 UTC 时看不出问题，换一台就漂移几小时。
    因此这里断言「同一会话的活动时间与登记时间相差在一个合理窗口内」，
    而不是断言某一个具体时刻。
    """
    session_id = _session_id("utc")
    await _register(session_id)
    await _add_sdk_items(session_id, [{"role": "user", "content": "问"}])

    async with session_scope(get_settings()) as session:
        rows = await repo.list_session_owners(session, account_id=_ACCOUNT, before=None, limit=repo.LIST_MAX_LIMIT)

    row = next(entry for entry in rows if entry.owner.session_id == session_id)
    assert row.updated_at.tzinfo is not None, "活动时间必须带时区——否则跨表比较依赖服务器配置"
    drift = abs(row.updated_at - row.owner.created_at)
    assert drift < timedelta(minutes=5), f"活动时间与登记时间相差过大（{drift}）——时区解释可能反了"


# ---------------------------------------------------------------------------
# 七、白名单的机械守卫：SDK 两表不得被判为「该删」
# ---------------------------------------------------------------------------


def test_sdk_tables_are_registered_in_metadata() -> None:
    """SDK 两表必须登记进 `core/db.metadata`——否则白名单会判它们「该删」。

    `migrations/env.py` 的判据是「在 `core/db.metadata` 里才管理」。未登记时
    autogenerate 会产出 `remove_table`（白名单模式下严格说是「看不到」，而一旦
    有人误把过滤器放宽就会立刻删表）。这条用例在不连库的前提下守住登记这件事，
    与 `test_migration_safety_integration.py` 的黑盒守卫互补。
    """
    from campfire.core.db import metadata

    assert SDK_SESSIONS_TABLE_NAME in metadata.tables
    assert SDK_MESSAGES_TABLE_NAME in metadata.tables


def test_sdk_table_names_match_the_sdk_defaults() -> None:
    """表名必须与 SDK 的构造默认值一致——改名的后果是迁移建的表不是 SDK 读写的那张。

    SDK 的 `SQLAlchemySession` 以 `sessions_table` / `messages_table` 为参数，默认值
    就是这两个名字。装配处不传这两个参数（见 `agent/runtime/session.py`），因此默认值
    是事实契约。
    """
    import inspect as py_inspect

    from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession

    signature = py_inspect.signature(SQLAlchemySession.__init__)
    assert signature.parameters["sessions_table"].default == SDK_SESSIONS_TABLE_NAME
    assert signature.parameters["messages_table"].default == SDK_MESSAGES_TABLE_NAME
