"""集成测试：账号注销时记忆图库那一半（`GRAPH.DELETE` 整图丢弃）。

该动作此前没有任何自动化覆盖（`test_auth_deletion_integration.py` 只覆盖账本那一半）。
本文件只碰图库与账本、不碰认证 core。

锁住：① 有图时图键消失且账本行清除；② 没图是正常结果（注销可重试）；③ 旁观账号不受
影响；④ 畸形账号键入口被拒；⑤ 结构性回归——删图路径**不得**为被删账号 clone 驱动
（那会调度建索引任务，与 `GRAPH.DELETE` 竞态）。

    docker compose up -d postgres falkordb
    uv run pytest -m integration apps/api/tests/test_memory_purge_integration.py

不调模型：`purge` 一次模型请求都不发。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select

from campfire.core.config import Settings, get_settings
from campfire.core.db import session_scope
from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError
from campfire.modules.memory.graph import MemoryGraph
from campfire.modules.memory.identity import AccountIdError
from campfire.modules.memory.models import MemoryDeletionLedger
from campfire.modules.memory.purge import MemoryAccountPurger

from .conftest import connect_falkordb_or_skip, settings_with_placeholder_model_key

pytestmark = pytest.mark.integration

#: 本文件的图名命名空间（清理只按它收窄；共享 FalkorDB 下不做无过滤删除）。
_PREFIX = "it_mem_purge_"


async def _settings_or_skip() -> Settings:
    """配置与图库可用性探针；容器不可用则跳过（只把「连不上」当环境问题）。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——本文件会写删除账本行，需要 docker compose up -d postgres")
    driver, client = connect_falkordb_or_skip()
    del driver  # 只作可用性探针；purger 自己建连接
    await client.aclose()
    return settings_with_placeholder_model_key(get_settings())


async def _graph_names(settings: Settings) -> list[str]:
    """共享 FalkorDB 现有图名（经 `connect_falkordb_or_skip` 的同一连接方式读）。"""
    from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed

    client = FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        password=(settings.falkordb_password.get_secret_value() if settings.falkordb_password else None),
    )
    try:
        return list(await client.list_graphs())
    finally:
        await client.aclose()


async def _create_graph(settings: Settings, name: str) -> None:
    """建一张带一条节点的最小图（模拟该账号已有记忆）。"""
    from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed

    client = FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        password=(settings.falkordb_password.get_secret_value() if settings.falkordb_password else None),
    )
    try:
        await client.select_graph(name).query("CREATE (:Episodic {uuid: $uuid})", {"uuid": f"probe-{name}"})
    finally:
        await client.aclose()


async def _seed_ledger_row(account_id: str) -> None:
    async with session_scope(get_settings()) as session:
        session.add(
            MemoryDeletionLedger(
                episode_key="6f2a1c3e-9b74-4d51-8a0e-2c5f7b9d4e11",
                account_id=account_id,
                reason="user_request",
            )
        )


async def _ledger_rows(account_id: str) -> int:
    async with session_scope(get_settings()) as session:
        rows = list(
            (
                await session.execute(
                    select(MemoryDeletionLedger.episode_key).where(MemoryDeletionLedger.account_id == account_id)
                )
            ).scalars()
        )
    return len(rows)


@pytest_asyncio.fixture
async def settings_ready() -> AsyncIterator[Settings]:
    """配置 + 清理本命名空间残留（上一次运行中断留下的图）。"""
    settings = await _settings_or_skip()
    from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed

    client = FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        password=(settings.falkordb_password.get_secret_value() if settings.falkordb_password else None),
    )
    try:
        for name in await client.list_graphs():
            if name.startswith(_PREFIX):
                await client.execute_command("GRAPH.DELETE", name)
    finally:
        await client.aclose()
    try:
        yield settings
    finally:
        async with session_scope(get_settings()) as session:
            from sqlalchemy import delete

            await session.execute(
                delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id.like(f"{_PREFIX}%"))
            )


@pytest.mark.asyncio
async def test_purge_drops_the_account_graph_and_its_ledger_rows(settings_ready: Settings) -> None:
    """有图有账本时：图键消失、账本行清除，并在 detail 里如实说明。"""
    account = f"{_PREFIX}target"
    await _create_graph(settings_ready, account)
    await _seed_ledger_row(account)
    assert account in await _graph_names(settings_ready), "前置条件：图必须已建立"

    outcome = await MemoryAccountPurger(settings_ready).purge_account(account)

    assert "已丢弃图" in outcome.detail, outcome.detail
    assert account not in await _graph_names(settings_ready), "整图丢弃后图键必须消失"
    assert await _ledger_rows(account) == 0, "账本行必须一并清除（内容真删的一部分）"


@pytest.mark.asyncio
async def test_purge_is_idempotent_when_the_graph_is_already_gone(settings_ready: Settings) -> None:
    """没有图时是正常结果（注销可重试），不是异常。

    判别性（实测）：此前的实现靠「`GRAPH.DELETE` 对不存在的图不报错」这一**错误前提**
    免去了存在性判断——实测 v4.20.7 对不存在的图抛
    `ResponseError: Invalid graph operation on empty key`，于是第二次注销会失败。
    """
    account = f"{_PREFIX}absent"

    first = await MemoryAccountPurger(settings_ready).purge_account(account)
    second = await MemoryAccountPurger(settings_ready).purge_account(account)

    assert "无图可丢弃" in first.detail, first.detail
    assert "无图可丢弃" in second.detail, second.detail


@pytest.mark.asyncio
async def test_purge_does_not_touch_a_bystander_account(settings_ready: Settings) -> None:
    """旁观账号的图必须原样保留（清理只按账号命名空间）。

    正控与目标同批：一条漏了账号参数的删图会连旁观者一起删，而只断言目标消失时
    那种写法照样「通过」。
    """
    target = f"{_PREFIX}target_iso"
    bystander = f"{_PREFIX}bystander"
    await _create_graph(settings_ready, target)
    await _create_graph(settings_ready, bystander)

    await MemoryAccountPurger(settings_ready).purge_account(target)

    names = await _graph_names(settings_ready)
    assert target not in names
    assert bystander in names, "旁观账号的图被一并删掉了"


@pytest.mark.asyncio
async def test_purge_rejects_a_malformed_account_id_before_deleting_anything(settings_ready: Settings) -> None:
    """畸形账号键在入口被拒，且不删任何图。

    为什么必须有这条（2026-10-29）：删图路径此前经 `driver_for(account_id)` 取驱动，
    校验是那一步**顺带**提供的。改成直接删图后若不显式校验，`'_'`（框架哨兵）或含
    换行的键就会直接成为被删的图名。
    """
    survivor = f"{_PREFIX}survivor"
    await _create_graph(settings_ready, survivor)

    for bad in ("_", "", "bad\nname", "x" * 200, "acct.aaa"):
        with pytest.raises(AccountIdError):
            await MemoryAccountPurger(settings_ready).purge_account(bad)

    assert survivor in await _graph_names(settings_ready), "被拒的账号键不得导致任何图被删"


@pytest.mark.asyncio
async def test_drop_graph_never_clones_a_driver_for_the_account_being_deleted(
    settings_ready: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """删图路径**不得**为被删账号 clone 驱动（后台建索引任务 + `GRAPH.DELETE` 竞态）。

    时序不可稳定复现（会在共享服务上制造真实竞态），因此钉「有没有走到那条路」而不是
    钉「有没有偶发报错」。判别性：把 `_drop_graph` 改回 `driver_for` 取驱动 ⇒ 本用例红。
    """
    account = f"{_PREFIX}no_clone"
    await _create_graph(settings_ready, account)

    calls: list[str] = []
    original = MemoryGraph.driver_for

    def spy(self: MemoryGraph, account_id: str) -> object:  # noqa: ANN401 —— 原样转交
        calls.append(str(account_id))
        return original(self, account_id)

    monkeypatch.setattr(MemoryGraph, "driver_for", spy)

    await MemoryAccountPurger(settings_ready).purge_account(account)

    assert account not in calls, (
        f"删图路径为被删账号 clone 了驱动（{account!r}）——那会调度建索引后台任务，与 GRAPH.DELETE 竞态（QA-10 的成因）"
    )


@pytest.mark.asyncio
async def test_purge_refuses_to_delete_the_configured_database(settings_ready: Settings) -> None:
    """账号标识命中配置库名时拒绝删图，而不是把默认库清空。

    账户标识在生产里是身份服务的 id，但这条判据不该依赖「上游不会传什么」：
    删错一张图不可恢复，失败方向必须是显式拒绝。
    """
    with pytest.raises(MemoryDataError):
        await MemoryAccountPurger(settings_ready).purge_account(settings_ready.falkordb_database)


@pytest.mark.asyncio
async def test_purge_fails_loudly_when_the_graph_client_is_missing(
    settings_ready: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """拿不到图库客户端时必须失败，不得把「没清」回执成成功。

    注销的承诺是「内容已清除」；静默跳过会让「已删除」成为谎话。
    """

    class _DriverWithoutClient:
        pass

    class _GraphWithoutClient:
        driver = _DriverWithoutClient()

        async def aclose(self) -> None:
            return None

    import campfire.modules.memory.purge as purge_module

    monkeypatch.setattr(purge_module, "build_memory_graph", lambda *_: _GraphWithoutClient())

    with pytest.raises(MemoryUnavailableError):
        await MemoryAccountPurger(settings_ready).purge_account(f"{_PREFIX}no_client")
