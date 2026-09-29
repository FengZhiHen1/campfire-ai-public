"""集成测试：删除账本的存储约束、幂等与删除写入端。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 7 节。这些事实**只能在真实
PostgreSQL 上验证**（约束与 `ON CONFLICT` 是数据库行为，不是 Python 行为），因此带
``integration`` marker。显式跑法：

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_memory_ledger_integration.py

**注意**：``addopts`` 里没有 marker 过滤，因此默认 ``uv run pytest`` 也会收集本文件。

锁住的是 CORE-05 要求的最强通道——**不变量落在数据库约束上，而不是注释承诺**：

1. ``episode_key`` 唯一：同一条记忆重复删除不得产生第二行（删除本身也须幂等）。
2. ``account_id`` 非空 + 可按账号批量筛（账号级清理的查询路径）。
3. ``derived_uuids`` 默认空数组且可存列表（JSONB 往返）。
4. 表存在且列名与模型一致——迁移与模型漂移会在写入时报错而不是静默。
5. 删除**写入端**（``record_deletion``）：幂等命中如实区分、跨账号共用 key 显式失败、
   非法原因/空 key 显式失败、与读取端对得上。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from campfire.core.config import get_settings
from campfire.core.db import dispose_engine, session_scope
from campfire.modules.memory.errors import MemoryDataError
from campfire.modules.memory.ledger import (
    DeletionOutcome,
    deleted_episode_keys,
    record_deletion,
)
from campfire.modules.memory.models import (
    DELETION_REASON_CORRECTION,
    DELETION_REASON_USER_REQUEST,
    MemoryDeletionLedger,
)

pytestmark = pytest.mark.integration

#: 本文件专用的账号标识。**故意用非 UUID 形态**：账本列此前是 `uuid`，而
#: `identity.to_account_id` 接受 `[a-zA-Z0-9_-]`（不只 UUID）——两者冲突会让
#: 「合法账号键无法落库」。用下划线形态正是为了把这个缺陷钉住（2026-09-29 评审发现）。
_ACCOUNT = "cd_it_account_001"

#: 本文件用到的另外两个账号（跨账号场景）。**集中定义**：用例里不再就地写字面量，
#: 这样 `_ALL_ACCOUNTS` 不可能漏掉某个账号（2026-09-29 评审发现的清理漂移）。
_OTHER_ACCOUNT_A = "cd_it_account_002"
_OTHER_ACCOUNT_B = "cd_it_account_003"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**。

    仓库既有集成测试的统一做法（见 `test_library_schema_integration.py`）：CI 不带
    Postgres service。若不跳过，本文件会以「连接失败」整片变红，把「没配环境」误报成
    「代码坏了」（2026-09-29 评审指出本文件此前是唯一没有该守卫的集成测试）。
    """
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_engine() -> AsyncIterator[None]:
    """每个用例前后释放 ``core/db`` 的全局共享引擎。

    原因（实测）：pytest-asyncio 为每个用例新建事件循环，而共享引擎的连接池绑定在
    **首次使用时的事件循环**上——跨循环复用会抛 ``RuntimeError: Event loop is closed``，
    并在 teardown 留下一串 ``AsyncAdaptedQueuePool: Exception terminating connection``，
    把真正的失败原因埋掉。生产只有一个长驻循环，不存在该问题。
    同一处理见 ``test_library_ingestion_integration.py``。
    """
    await dispose_engine()
    yield
    await dispose_engine()


def _episode_key(suffix: str) -> str:
    """构造一个确定性的 episode key（形状与真实派生一致：规范 UUID 文本）。

    用 uuid5 而非拼接：拼接出来的（如 ``cd000000-...-00000000idem``）**不是合法
    UUID**，会被 `identity.to_episode_key` 正确拒绝——那正是校验该拦的输入，
    不该出现在夹具里。uuid5 既确定性又保证形状合法。
    """
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"campfire-test-ledger-{suffix}"))


#: 本文件写入的所有账号。清理必须覆盖**全部**，不能只清 `_ACCOUNT`。
#:
#: 为什么（2026-09-29 评审发现，已复现）：`episode_key` 有**全局**唯一约束，而本文件
#: 的用例会为不同账号写入同一个 key。若清理只按 `_ACCOUNT`，上一次运行/中止留下的
#: 他账号行会让下一次运行在插入同 key 时报 `UniqueViolationError`——不是理论风险，
#: 是可复现的「环境不干净即红」。
_ALL_ACCOUNTS = (_ACCOUNT, _OTHER_ACCOUNT_A, _OTHER_ACCOUNT_B)


async def _cleanup() -> None:
    """清理本文件写入的行。

    按 `_ALL_ACCOUNTS` 清理**全部**账号，而不是只清 `_ACCOUNT`（2026-09-29 评审发现，
    已复现）：`episode_key` 有**全局**唯一约束，而本文件的用例会为不同账号写入同一个
    key。清理漏掉某个账号时，上一次运行（或中止的运行）留下的那一行会让下一次运行在
    插入同 key 时报 `UniqueViolationError`——「环境不干净即红」。

    维护要求：**任何新账号都必须登记进 `_ALL_ACCOUNTS`**，否则该用例的行不会被清理。
    为避免漂移，各用例一律引用 `_OTHER_ACCOUNT_A` / `_OTHER_ACCOUNT_B` 这两个常量，
    而不是就地写字面量。
    """
    async with session_scope(get_settings()) as session:
        await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id.in_(_ALL_ACCOUNTS)))


@pytest.mark.asyncio
async def test_ledger_table_exists_and_round_trips() -> None:
    """表可写可读，`derived_uuids` 的 JSONB 往返保真。

    迁移漏建表或列名不符时，这里会在写入阶段直接报错（而不是静默）。
    """
    await _cleanup()
    try:
        async with session_scope(get_settings()) as session:
            session.add(
                MemoryDeletionLedger(
                    episode_key=_episode_key("1"),
                    account_id=_ACCOUNT,
                    reason=DELETION_REASON_USER_REQUEST,
                    derived_uuids=["edge-1", "node-2"],
                )
            )

        async with session_scope(get_settings()) as session:
            row = (
                await session.execute(
                    select(MemoryDeletionLedger).where(MemoryDeletionLedger.episode_key == _episode_key("1"))
                )
            ).scalar_one()
            assert row.derived_uuids == ["edge-1", "node-2"]
            assert row.reason == DELETION_REASON_USER_REQUEST
            # server_default now()：写的时候没给时间，读回来必须有值。
            assert row.deleted_at is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_duplicate_episode_key_is_rejected_by_the_database() -> None:
    """同一条记忆重复删除被**数据库唯一约束**拒绝——不靠应用层先查后写。

    这条是 CORE-05 的落点：删除幂等由存储约束承载，而不是靠调用方自觉。
    若约束缺失（例如有人把 unique 去掉），本用例会失败——那正是我们要拦的漂移。
    """
    await _cleanup()
    try:
        async with session_scope(get_settings()) as session:
            session.add(
                MemoryDeletionLedger(
                    episode_key=_episode_key("2"),
                    account_id=_ACCOUNT,
                    reason=DELETION_REASON_CORRECTION,
                )
            )

        with pytest.raises(IntegrityError):
            async with session_scope(get_settings()) as session:
                session.add(
                    MemoryDeletionLedger(
                        episode_key=_episode_key("2"),
                        account_id=_ACCOUNT,
                        reason=DELETION_REASON_USER_REQUEST,
                    )
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_derived_uuids_defaults_to_empty_list() -> None:
    """不给 `derived_uuids` 时落库为空数组，而不是 NULL。

    读路径会直接迭代该列；NULL 会让迭代在运行期炸，且「删除时没查到派生物」
    与「数据缺失」在语义上必须区分（前者正常，后者是缺陷）。
    """
    await _cleanup()
    try:
        async with session_scope(get_settings()) as session:
            session.add(
                MemoryDeletionLedger(
                    episode_key=_episode_key("3"),
                    account_id=_ACCOUNT,
                    reason=DELETION_REASON_USER_REQUEST,
                )
            )

        async with session_scope(get_settings()) as session:
            row = (
                await session.execute(
                    select(MemoryDeletionLedger).where(MemoryDeletionLedger.episode_key == _episode_key("3"))
                )
            ).scalar_one()
            assert row.derived_uuids == []
            assert row.derived_uuids is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_account_filter_is_the_query_path_for_account_wide_cleanup() -> None:
    """按 `account_id` 能一次筛出该账号的全部删除记录（账号级清理的查询路径）。

    同时验证**跨账号不可见**：另一个账号的删除记录不出现在结果里——
    这是「记忆按账号归属」在账本上的体现（决策记录 `通用记忆归属为账号.md`）。
    """
    other_account = _OTHER_ACCOUNT_A
    await _cleanup()
    try:
        async with session_scope(get_settings()) as session:
            session.add_all(
                [
                    MemoryDeletionLedger(
                        episode_key=_episode_key("4"), account_id=_ACCOUNT, reason=DELETION_REASON_USER_REQUEST
                    ),
                    MemoryDeletionLedger(
                        episode_key=_episode_key("5"), account_id=_ACCOUNT, reason=DELETION_REASON_CORRECTION
                    ),
                    MemoryDeletionLedger(
                        episode_key=_episode_key("6"), account_id=other_account, reason=DELETION_REASON_USER_REQUEST
                    ),
                ]
            )

        async with session_scope(get_settings()) as session:
            mine = (
                await session.execute(
                    select(func.count())
                    .select_from(MemoryDeletionLedger)
                    .where(MemoryDeletionLedger.account_id == _ACCOUNT)
                )
            ).scalar_one()
            assert mine == 2, "按账号筛应只看到本账号的 2 条，看不到另一账号的第 3 条"
    finally:
        await _cleanup()
        async with session_scope(get_settings()) as session:
            await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == other_account))


# ---------------------------------------------------------------------------
# 删除的写入端（第 7 节：语义删除的唯一生效点）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_deletion_is_idempotent_on_repeat() -> None:
    """同一条记忆重复删除只留一行，且**如实区分**「新记」与「已记过」。

    幂等落在 `episode_key` 的唯一约束 + `ON CONFLICT DO NOTHING`（存储约束通道），
    不是「先查后写」——后者在并发下会双写。
    区分结果的意义：调用方需要知道是刚删除还是早已删除（用户可见文案与审计不同）；
    静默返回同一种结果会让「删除根本没生效」与「删除早已生效」看起来一样。
    """
    await _cleanup()
    key = _episode_key("idem")
    try:
        async with session_scope(get_settings()) as session:
            first = await record_deletion(session, account_id=_ACCOUNT, episode_key=key)

        async with session_scope(get_settings()) as session:
            second = await record_deletion(session, account_id=_ACCOUNT, episode_key=key)

        assert first.outcome is DeletionOutcome.RECORDED
        assert second.outcome is DeletionOutcome.ALREADY_RECORDED
        assert second.owner_account_id == _ACCOUNT

        async with session_scope(get_settings()) as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(MemoryDeletionLedger)
                    .where(MemoryDeletionLedger.episode_key == key)
                )
            ).scalar_one()
            assert count == 1, "重复删除不得产生第二行"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_record_deletion_rejects_a_key_owned_by_another_account() -> None:
    """跨账号共用同一 `episode_key` 时**显式失败**，不静默幂等。

    为什么：`episode_key` 由 uuid4 派生，跨账号共用正常不可能发生。若此时静默按
    「已存在」返回，本账号的删除会**看起来成功、实际不生效**（读路径按本账号查账本，
    查不到那条记录）——删除静默失效正是 `RQ-MEM-03` 要避免的。故必须报错。
    """
    other = _OTHER_ACCOUNT_B
    key = _episode_key("crossacct")
    try:
        async with session_scope(get_settings()) as session:
            await record_deletion(session, account_id=other, episode_key=key)

        async with session_scope(get_settings()) as session:
            with pytest.raises(MemoryDataError, match="其它账号"):
                await record_deletion(session, account_id=_ACCOUNT, episode_key=key)
    finally:
        await _cleanup()
        async with session_scope(get_settings()) as session:
            await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == other))


@pytest.mark.asyncio
async def test_record_deletion_rejects_unknown_reason_and_empty_key() -> None:
    """非法原因与空 key 都显式失败（边界显式，不留静默兜底）。"""
    await _cleanup()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(MemoryDataError, match="原因"):
                await record_deletion(session, account_id=_ACCOUNT, episode_key=_episode_key("r"), reason="乱写")
            with pytest.raises(MemoryDataError, match="为空"):
                await record_deletion(session, account_id=_ACCOUNT, episode_key="")
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_deleted_episode_keys_returns_what_was_recorded() -> None:
    """写入端与读取端对得上：记了删除，`deleted_episode_keys` 就取得到。"""
    await _cleanup()
    kept_out = _episode_key("k1")
    try:
        async with session_scope(get_settings()) as session:
            await record_deletion(session, account_id=_ACCOUNT, episode_key=kept_out)

        async with session_scope(get_settings()) as session:
            keys = await deleted_episode_keys(session, _ACCOUNT)

        assert kept_out in keys
        assert len(keys) == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_record_deletion_rejects_invalid_account_ids() -> None:
    """`account_id` 必须过入口校验——否则会产生**不可恢复的毒化行**。

    为什么必须有这条（2026-09-29 评审发现的阻断级，实测复现）：此前 `record_deletion`
    只校验 `episode_key`，`account_id` 是裸 `str`。写入一条 `account_id=''` 的行后，
    它**既不被任何真实账号读到**（读路径按 account_id 过滤），又因 `episode_key` 的
    **全局唯一约束**永久占用该 key——合法账号删除那条记忆会撞上跨账号守卫而**永久失败**，
    且没有 API 能清掉该行。超长值此前还会退化成裸 `StringDataRightTruncationError`。

    判别性：去掉 `account_id = to_account_id(account_id)` 这一行，本用例会失败
    （空串会被接受）。
    """
    from campfire.modules.memory.identity import AccountIdError

    await _cleanup()
    key = _episode_key("badacct")
    try:
        for bad in ("", "_", "acct.aaa", "a" * 200):
            async with session_scope(get_settings()) as session:
                with pytest.raises(AccountIdError):
                    await record_deletion(session, account_id=bad, episode_key=key)

        # 被拒的请求不得留下任何账本行（毒化行的定义就是「留下了」）。
        async with session_scope(get_settings()) as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(MemoryDeletionLedger)
                    .where(MemoryDeletionLedger.episode_key == key)
                )
            ).scalar_one()
            assert count == 0, "被拒的账号标识不得留下账本行"

        # 合法账号仍然可用（防止把校验做成「一律拒绝」）。
        async with session_scope(get_settings()) as session:
            ok = await record_deletion(session, account_id=_ACCOUNT, episode_key=key)
        assert ok.outcome is DeletionOutcome.RECORDED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_deleted_episode_keys_rejects_invalid_account_id() -> None:
    """读侧同样校验账号标识（脏键会让读路径按错误分区过滤）。"""
    from campfire.modules.memory.identity import AccountIdError

    async with session_scope(get_settings()) as session:
        with pytest.raises(AccountIdError):
            await deleted_episode_keys(session, "")


@pytest.mark.asyncio
async def test_deleted_episode_keys_is_empty_for_untouched_account() -> None:
    """没有删除记录的账号返回空列表——**正常状态，不是错误**。"""
    async with session_scope(get_settings()) as session:
        keys = await deleted_episode_keys(session, "cd_it_account_never_used")
    assert keys == []


@pytest.mark.asyncio
async def test_database_rejects_a_reason_outside_the_vocabulary() -> None:
    """`reason` 的词表判据落在 **CHECK 约束**上，不只是 Python 侧 frozenset。

    为什么必须有这条（2026-09-29 评审发现）：此前 `pg_constraint` 里只有 PK 与 UNIQUE，
    探针 `INSERT ... reason='not_a_valid_reason'` **成功**——注释写着「取值见
    DELETION_REASONS」，存储层却接受任意字符串。这条断言把词表钉在存储层：
    去掉 CHECK 约束它就会失败。
    """
    await _cleanup()
    try:
        with pytest.raises(IntegrityError, match="ck_campfire_memory_deletion_ledger_reason"):
            async with session_scope(get_settings()) as session:
                session.add(
                    MemoryDeletionLedger(
                        episode_key=_episode_key("badreason"),
                        account_id=_ACCOUNT,
                        reason="not_a_valid_reason",
                    )
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_derived_uuids_defaults_to_empty_list_at_insert() -> None:
    """`derived_uuids` 在 **INSERT 时**落成 `[]`（不是 NULL）。

    为什么必须有这条（2026-09-29 评审发现）：只有 `server_default` 时该列会被写成
    NULL；`default=list` 修的是插入值。

    **同时钉住 `default=` 的生效时机**：它**不在构造期**求值——构造后立刻读仍是
    ``None``（实测）。这是 SQLAlchemy 的语义，不是缺陷；但调用方若在持久化前就需要
    空列表，必须自己赋值（`ledger.record_deletion` 的做法）。这条断言把该事实写进
    测试，避免后来者误以为 ORM 默认值在构造期生效。
    """
    row = MemoryDeletionLedger(
        episode_key=_episode_key("prefflush"),
        account_id=_ACCOUNT,
        reason=DELETION_REASON_USER_REQUEST,
    )
    # 构造期：未 assign，ORM 默认值尚未求值（预期为 None，见 docstring）。
    assert row.derived_uuids is None, "default= 只在 flush 时生效；这条断言记录该语义"

    await _cleanup()
    try:
        async with session_scope(get_settings()) as session:
            session.add(row)

        async with session_scope(get_settings()) as session:
            persisted = (
                await session.execute(
                    select(MemoryDeletionLedger).where(MemoryDeletionLedger.episode_key == _episode_key("prefflush"))
                )
            ).scalar_one()
            assert persisted.derived_uuids == [], "INSERT 时必须落成空数组而不是 NULL"
    finally:
        await _cleanup()
