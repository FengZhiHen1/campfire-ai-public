"""注销墓碑的存储层行为（真实 PostgreSQL）。

对应 ``docs/技术设计/decisions/账号注销与墓碑.md`` 与
``docs/技术设计/technical-details/认证与账号.md`` 第 8 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_auth_tombstone_integration.py

## 逐条对应设计

1. **墓碑是 Worker 判定「已注销」的唯一依据**：``is_account_deleted`` 是那条判定的入口。
2. **一个账号只能注销一次**：重复写入必须不产生第二行——否则「查墓碑」会变成需要去重
   的问题。用**存储层主键**承载，不是应用层先查后写。
3. **幂等且能区分「新建」与「已存在」**：注销编排可能重跑（第 1 步失败后整体重试），
   而「本次是新建」与「上次已写过」的正确后续动作不同。
4. **墓碑不含任何用户内容**：只有账号标识、时间、原因——这是对外表述
   「已删除全部内容，并保留一条不含内容的注销记录」能成立的依据。
5. **原因词表落 CHECK**：闭集，静默写入未知原因会让「为什么注销」无从查起。
6. **`core/auth` 不得依赖业务模块**：本层只校验长度与空值，不校验字符集
   （字符集判据属 `modules/memory/identity`）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from campfire.core.auth import (
    DELETION_REASON_USER_REQUEST,
    MAX_ACCOUNT_ID_LENGTH,
    AccountDeletionTombstone,
    TombstonePayloadError,
    deleted_account_ids,
    get_tombstone,
    is_account_deleted,
    record_deletion,
)
from campfire.core.config import get_settings
from campfire.core.db import session_scope

pytestmark = pytest.mark.integration

#: 本文件的账号前缀（避免与其它测试文件的行互相干扰）。
_ACCOUNT = "it_tombstone_account"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


async def _clear() -> None:
    """清掉本文件写入的行。"""
    async with session_scope(get_settings()) as session:
        await session.execute(
            delete(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id.like(f"{_ACCOUNT}%"))
        )


# ---------------------------------------------------------------------------
# 写入与幂等
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_a_deletion_marks_the_account_deleted() -> None:
    """写墓碑后 ``is_account_deleted`` 为真——这是 Worker 那条判定的入口。"""
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            result = await record_deletion(session, account_id=_ACCOUNT)

        assert result.created is True, "首次写入必须是「新建」"
        assert result.account_id == _ACCOUNT
        assert result.reason == DELETION_REASON_USER_REQUEST

        async with session_scope(get_settings()) as session:
            assert await is_account_deleted(session, account_id=_ACCOUNT) is True
            # 未注销的账号必须是 False（否则「已注销」判定失去意义）。
            assert await is_account_deleted(session, account_id=f"{_ACCOUNT}_never") is False
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_recording_twice_is_idempotent_and_reports_not_created() -> None:
    """重复写墓碑**不产生第二行**，且如实报告「本次不是新建」。

    **判别性**：注销编排可能重跑。若第二次报错，重试路径会把「其实已经写好了」
    当作失败，操作者会去排查一个不存在的问题；若第二次静默产生第二行，
    「查墓碑」就变成需要去重的问题。两种都必须避免，故这里同时断言
    「`created is False`」与「表里恰好一行」。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            first = await record_deletion(session, account_id=_ACCOUNT)
        async with session_scope(get_settings()) as session:
            second = await record_deletion(session, account_id=_ACCOUNT)

        assert first.created is True
        assert second.created is False, "重复写入必须报告「已存在」而不是「新建」"
        # 时间戳与原因保持**首次**的值：注销时间是不可变事实，重跑不得改写它。
        assert second.deleted_at == first.deleted_at, "重跑不得改写注销时间"
        assert second.reason == first.reason

        async with session_scope(get_settings()) as session:
            rows = list(
                (
                    await session.execute(
                        select(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id == _ACCOUNT)
                    )
                ).scalars()
            )
        assert len(rows) == 1, f"同一账号不得有第二行墓碑（实际 {len(rows)} 行）"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_database_enforces_one_tombstone_per_account() -> None:
    """**一个账号只能注销一次**由**存储层主键**承载（不是应用层先查后写）。

    判别性：去掉主键（或改成普通列），本用例失败——而那样并发两次注销会产生两行。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            session.add(AccountDeletionTombstone(account_id=_ACCOUNT, reason=DELETION_REASON_USER_REQUEST))

        with pytest.raises(IntegrityError, match="pk_campfire_account_deletion_tombstone"):
            async with session_scope(get_settings()) as session:
                session.add(AccountDeletionTombstone(account_id=_ACCOUNT, reason=DELETION_REASON_USER_REQUEST))
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_concurrent_recording_yields_exactly_one_row() -> None:
    """并发写同一账号的墓碑 → **恰好一行**，且两方都不报错（幂等）。

    **判别性**：若实现是「先查后写」，两个并发请求会都查到「没有墓碑」、都去插入，
    其中一个撞主键抛错。本用例断言两个调用都正常返回。
    """
    import asyncio

    await _clear()
    try:

        async def record() -> object:
            async with session_scope(get_settings()) as session:
                return await record_deletion(session, account_id=_ACCOUNT)

        results = await asyncio.gather(record(), record())
        # 两方都必须成功返回（幂等），且至少一方报告 created=True。
        assert all(hasattr(r, "created") for r in results)
        assert any(r.created for r in results), "至少一方必须是新建"

        async with session_scope(get_settings()) as session:
            rows = list(
                (
                    await session.execute(
                        select(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id == _ACCOUNT)
                    )
                ).scalars()
            )
        assert len(rows) == 1, f"并发注销必须只留下 1 行（实际 {len(rows)}）"
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 内容边界（对外表述的依据）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tombstone_has_no_user_content_columns() -> None:
    """**墓碑只有账号标识、时间、原因**——不得出现承载用户内容的列。

    这条是「已删除全部内容，并保留一条不含内容的注销记录」这句对外表述的**机器化依据**。
    判别性：任何人给墓碑加一列内容字段（备注、原因说明、原账号名…），本用例失败，
    从而迫使「对外表述」与「存储事实」重新对齐。
    """
    columns = set(AccountDeletionTombstone.__table__.columns.keys())

    assert columns == {"account_id", "deleted_at", "reason"}, (
        f"墓碑的列发生了变化：{sorted(columns)}。若新增了承载用户内容的列，"
        "则「不含任何用户内容」这句对外表述**不再成立**，必须同步改口径（见决策记录）。"
    )


@pytest.mark.asyncio
async def test_tombstone_records_the_reason_and_time() -> None:
    """墓碑保留注销时间与原因（审计用途），且写入的时间即传入的参照时间。"""
    await _clear()
    try:
        base = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        async with session_scope(get_settings()) as session:
            await record_deletion(session, account_id=_ACCOUNT, now=base)

        async with session_scope(get_settings()) as session:
            row = await get_tombstone(session, account_id=_ACCOUNT)
        assert row is not None
        assert row.deleted_at == base
        assert row.reason == DELETION_REASON_USER_REQUEST
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 存储层约束与形状校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_rejects_an_unknown_reason() -> None:
    """原因词表是闭集，落在 **CHECK 约束**上。"""
    await _clear()
    try:
        with pytest.raises(IntegrityError, match="ck_campfire_account_deletion_tombstone_reason"):
            async with session_scope(get_settings()) as session:
                session.add(AccountDeletionTombstone(account_id=_ACCOUNT, reason="not_a_reason"))
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_application_layer_rejects_reason_outside_the_vocabulary() -> None:
    """词表在**应用层也校验一次**：存储层会抛裸 `IntegrityError`，看不出是哪个字段。"""
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(TombstonePayloadError, match="reason 不在词表内"):
                await record_deletion(session, account_id=_ACCOUNT, reason="not_a_reason")
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_application_layer_rejects_bad_account_ids() -> None:
    """账号标识的形状校验：空、超宽、非字符串都是**领域异常**，不是裸 DBAPIError。

    只为保证「落库不会因超宽而抛裸 DBAPIError」；**字符集不在此层**
    （`core/*` 不得依赖业务模块，见模块说明）。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            for bad in ("", 123, None, b"bytes"):
                with pytest.raises(TombstonePayloadError):
                    await record_deletion(session, account_id=bad)
            # 超宽：恰好 128 可接受，129 拒绝（边界闭区间）。
            with pytest.raises(TombstonePayloadError, match="字符上界"):
                await record_deletion(session, account_id="a" * (MAX_ACCOUNT_ID_LENGTH + 1))
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_account_id_and_reason_are_not_nullable() -> None:
    """两个必填列不得接受 NULL（存储层 NOT NULL）。"""
    await _clear()
    try:
        with pytest.raises(IntegrityError):
            async with session_scope(get_settings()) as session:
                session.add(AccountDeletionTombstone(account_id=_ACCOUNT, reason=None))
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 批量查询（Worker 与排查用）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_query_returns_only_the_deleted_ones() -> None:
    """批量查询：只返回已注销的账号，且**空输入不发查询**。"""
    await _clear()
    try:
        deleted = f"{_ACCOUNT}_one"
        alive = f"{_ACCOUNT}_two"
        async with session_scope(get_settings()) as session:
            await record_deletion(session, account_id=deleted)

        async with session_scope(get_settings()) as session:
            found = await deleted_account_ids(session, account_ids=[deleted, alive, f"{_ACCOUNT}_three"])
        assert found == {deleted}

        async with session_scope(get_settings()) as session:
            assert await deleted_account_ids(session, account_ids=[]) == set()
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_batch_query_rejects_a_bare_string() -> None:
    """传 ``str`` 必须**显式拒绝**——否则逐字符校验并**静默返回空集**。

    ## 为什么这是安全问题而不是参数风格问题

    传 ``str`` 时 ``for value in account_ids`` 会逐字符迭代，
    ``IN ('i','t','_')`` 匹配不到任何墓碑，于是返回**空集**——
    即**静默回答「这些账号都没注销」**。那正是墓碑要防的「删后复活」的入口：
    调用方少写一层 ``[ ... ]`` 就会拿到与事实相反的答案，而且**不报错**。

    实测（评审）：修复前传 ``str`` 返回空集、传 ``None`` 或生成器抛裸 ``TypeError``。

    判别性：去掉类型守卫，本用例失败（不抛异常，返回空集或裸 TypeError）。
    """
    await _clear()
    try:
        # 先造一个**真的已注销**的账号：这样「空集」与「正确结果」才可区分。
        deleted = f"{_ACCOUNT}_strguard"
        async with session_scope(get_settings()) as session:
            await record_deletion(session, account_id=deleted)

        async with session_scope(get_settings()) as session:
            # 它不是合法输入：必须报错，不能静默给空集。
            with pytest.raises(TombstonePayloadError, match="序列"):
                await deleted_account_ids(session, account_ids=deleted)

            # 同样的内容放进 list 才对——证明上面拒的是**类型**，不是内容。
            found = await deleted_account_ids(session, account_ids=[deleted])
        assert found == {deleted}, "传 list 时必须正确返回已注销的账号"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_batch_query_is_bounded() -> None:
    """批量查询**有界**（CORE-11）：超长列表显式拒绝，不放进 SQL。"""
    from campfire.core.auth.tombstone_repository import BATCH_MAX_ACCOUNTS

    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(TombstonePayloadError, match="上界"):
                await deleted_account_ids(session, account_ids=[f"a{i}" for i in range(BATCH_MAX_ACCOUNTS + 1)])
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_cleanup_leaves_no_rows() -> None:
    """自检：清理后无残留（避免给其它测试留下脏数据）。"""
    await _clear()
    async with session_scope(get_settings()) as session:
        remaining = (
            await session.execute(
                select(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id.like(f"{_ACCOUNT}%"))
            )
        ).scalars()
        assert list(remaining) == []


@pytest.mark.asyncio
async def test_deleted_at_defaults_to_now_when_not_given() -> None:
    """不给参照时间时用当前 UTC，且落在合理区间内（防止默认值写死成常量）。"""
    await _clear()
    try:
        before = datetime.now(timezone.utc) - timedelta(seconds=5)
        async with session_scope(get_settings()) as session:
            await record_deletion(session, account_id=_ACCOUNT)

        async with session_scope(get_settings()) as session:
            row = await get_tombstone(session, account_id=_ACCOUNT)
        assert row is not None
        assert row.deleted_at > before, "默认时间应是当前时间，不是常量或过去某点"
    finally:
        await _clear()
