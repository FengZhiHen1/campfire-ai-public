"""集成测试：删除账本表的存储约束与幂等。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 7 节。这些事实**只能在真实
PostgreSQL 上验证**（约束是数据库行为，不是 Python 行为），因此带 ``integration``
marker，默认不在 ``uv run pytest`` 中运行；显式跑法：

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_memory_ledger_integration.py

锁住的是 CORE-05 要求的最强通道——**不变量落在数据库约束上，而不是注释承诺**：

1. ``episode_key`` 唯一：同一条记忆重复删除不得产生第二行（删除本身也须幂等）。
2. ``account_id`` 非空 + 可按账号批量筛（账号级清理的查询路径）。
3. ``derived_uuids`` 默认空数组且可存列表（JSONB 往返）。
4. 表存在且列名与模型一致——迁移与模型漂移会在写入时报错而不是静默。
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
from campfire.modules.memory.models import (
    DELETION_REASON_CORRECTION,
    DELETION_REASON_USER_REQUEST,
    MemoryDeletionLedger,
)

pytestmark = pytest.mark.integration

#: 本文件专用的账号前缀，测试结束按它清理。
_ACCOUNT = uuid.UUID("cd000000-0000-4000-8000-000000000001")


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
    """构造一个确定性的 episode key（形状与真实派生一致：uuid 字符串）。"""
    return f"cd000000-0000-4000-8000-{suffix.zfill(12)}"


async def _cleanup() -> None:
    """按账号清理本文件写入的行。"""
    async with session_scope(get_settings()) as session:
        await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == _ACCOUNT))


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
    other_account = uuid.UUID("cd000000-0000-4000-8000-0000000000ff")
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
