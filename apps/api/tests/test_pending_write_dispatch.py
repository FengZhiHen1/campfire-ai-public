"""按 `kind` 分派的机械检查与分派表行为。

对应 `docs/技术设计/technical-details/写入路径.md` 第 4 节第 3 条「消费：按 kind 分派」。
本文件不连数据库、不连 Redis：它钉的是**分派表本身**——哪些 kind 有消费者、没有消费者的
kind 如何被处置，以及两个入口有没有把投递钩子装上。

为什么要有这组检查（2026-09-30 修复）：投递钩子此前硬编码只投记忆任务，而
`campfire_pending_write` 有两种 kind。`profile_item` 被投进记忆消费者，记忆侧按
「kind 不符」抛 `MemoryDataError`，Worker 捕获后 `mark_dead` —— 永久 dead，
且 `last_error` 写成「记忆写入的载荷不合法」，污染 `dead` 的告警指标（第 8 节）。
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from campfire import main as main_module
from campfire import worker as worker_module
from campfire.core import jobs as jobs_module
from campfire.core.jobs import dispatch_pending_write, set_dispatch_hook
from campfire.core.pending_write import KIND_MEMORY_EPISODE, KIND_PROFILE_ITEM, KINDS


def test_every_kind_has_a_consumer_except_the_known_t12_gap() -> None:
    """`KINDS` 的每个取值都必须有消费者；当前唯一允许缺的是 `profile_item`（归 T12）。

    这条防的是「将来加第三种 kind 时忘了分派」：分派表是 `worker._CONSUMER_DISPATCHERS`，
    没有键的 kind 不会被投给任何消费者（`dispatch_pending_write_to_queue` 显式跳过），
    因此「缺少消费者」必须是被检查的事实，而不是运行期才发现。

    **它不是「永远不会失败的检查」**，两个方向都会失败并给出改法：

    - 新增第三种 kind 却没注册消费者：`missing` 变成两个值 → 失败；
    - T12 给 `profile_item` 接上消费者：`missing` 变成空集 → 失败，此时把断言改成
      `assert not missing` 即可（这句就是本检查的目标形态）。

    为什么不用 `xfail(strict=True)` 表达这个缺口：xfail 期间「新增第三种 kind」
    仍然只会是 XFAIL（静默通过），本检查防第二种情形的能力会被一起锁掉。
    现在这个写法把缺口写成可执行断言：集合不等于「已知的唯一缺口」就失败。
    """
    missing = KINDS - worker_module.CONSUMED_KINDS

    assert missing == {KIND_PROFILE_ITEM}, (
        f"缺消费者的 kind = {sorted(missing)}；当前唯一允许缺的是 {KIND_PROFILE_ITEM!r}（T12）。"
        "新增了 kind：请在 worker._CONSUMER_DISPATCHERS 里注册它的消费者。"
        "刚给 profile_item 接上消费者：把本断言改成 `assert not missing`。"
    )


@pytest.mark.asyncio
async def test_memory_episode_is_dispatched_to_its_own_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    """`memory_episode` 投给记忆消费者——分派表命中的那条路径。"""
    recorded: list[str] = []

    async def _record(pending_id: str) -> None:
        recorded.append(pending_id)

    monkeypatch.setitem(worker_module._CONSUMER_DISPATCHERS, KIND_MEMORY_EPISODE, _record)

    await worker_module.dispatch_pending_write_to_queue("00000000-0000-4000-8000-00000000000a", KIND_MEMORY_EPISODE)

    assert recorded == ["00000000-0000-4000-8000-00000000000a"]


@pytest.mark.asyncio
async def test_a_kind_without_a_consumer_is_skipped_and_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """无消费者的 kind：**不投给任何消费者**、记一条指名道姓的 warning。

    「显式跳过」不是「静默丢弃」：日志必须带 kind 与 pending_id，运维才看得出
    「有一批写入在等消费者」。记录本身的处置是不终结（仍是 `pending`，由兜底扫描
    在消费者接上后带回）——这一点由
    `apps/api/tests/test_pending_write_sweep_integration.py` 的两条集成用例钉住。
    """
    pending_id = "00000000-0000-4000-8000-00000000000b"

    async def _must_not_be_called(called_with: str) -> None:
        raise AssertionError(f"无消费者的 kind 不得投给别的消费者：{called_with}")

    for kind in list(worker_module._CONSUMER_DISPATCHERS):
        monkeypatch.setitem(worker_module._CONSUMER_DISPATCHERS, kind, _must_not_be_called)

    with caplog.at_level(logging.WARNING):
        await worker_module.dispatch_pending_write_to_queue(pending_id, KIND_PROFILE_ITEM)

    assert pending_id in caplog.text and KIND_PROFILE_ITEM in caplog.text, (
        f"跳过必须是显式的（日志带 kind 与 pending_id），实际日志={caplog.text!r}"
    )


@pytest.mark.asyncio
async def test_the_delivery_contract_carries_the_kind() -> None:
    """投递契约带 kind（第 4 节第 3 条）——钩子拿到的是 `(pending_id, kind)`。

    判别性：把 `dispatch_pending_write` 改成只传 `pending_id`，本用例失败。
    """
    seen: list[tuple[str, str]] = []

    async def _hook(pending_id: str, kind: str) -> None:
        seen.append((pending_id, kind))

    set_dispatch_hook(_hook)
    try:
        await dispatch_pending_write("00000000-0000-4000-8000-00000000000c", KIND_PROFILE_ITEM)
    finally:
        set_dispatch_hook(None)

    assert seen == [("00000000-0000-4000-8000-00000000000c", KIND_PROFILE_ITEM)]


@pytest.mark.asyncio
async def test_a_failed_delivery_logs_the_exception_type_without_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """投递失败留下的 warning 必须可归因：带 pending_id、kind 与**异常类型**。

    判别性：把格式串里的 `type(exc).__name__` 去掉，本用例失败——那正是修复前的
    形态（注释声称记了异常类型，实际两者都没有）。没有类型名就分不出
    「broker 未启动」「Redis 连接被拒」「队列名写错」，而这三种归因的处置完全不同。

    同时钉住安全侧：异常**消息**不得进日志（AGENTS.md：日志不复述连接串），
    因此实现只记类型名、也不带 `exc_info`。
    """

    class _BrokerDown(Exception):
        pass

    async def _explode(_pending_id: str, _kind: str) -> None:
        raise _BrokerDown("redis://user:secret@host:6379/0 连接被拒")

    pending_id = "00000000-0000-4000-8000-00000000000e"
    set_dispatch_hook(_explode)
    try:
        with caplog.at_level(logging.WARNING):
            await dispatch_pending_write(pending_id, KIND_MEMORY_EPISODE)
    finally:
        set_dispatch_hook(None)

    assert pending_id in caplog.text and KIND_MEMORY_EPISODE in caplog.text, (
        f"投递失败必须指名道姓（pending_id 与 kind），实际日志={caplog.text!r}"
    )
    assert "_BrokerDown" in caplog.text, f"warning 必须带异常类型，实际日志={caplog.text!r}"
    assert "secret" not in caplog.text, f"异常消息可能带连接串，不得进日志，实际日志={caplog.text!r}"


def test_api_entry_installs_the_dispatch_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    """API 入口必须注入投递钩子（写入路径第 4 节第 1 条：请求事务提交后再投递）。

    只由 Worker 入口注入时，API 进程的钩子是空的：每次投递都落进
    `core/jobs.dispatch_pending_write` 的 warning，所有写入要等 Worker 每 5 分钟的
    兜底扫描——与第 4 节第 1 条相反（2026-09-30 修复前的实际行为）。

    做法：进入 `main.app` 的 lifespan（与 `test_health.py` 同一方式），断言钩子已装上，
    且装上的钩子确实按 kind 分派到分派表里的消费者（把记忆消费者换成测试替身，
    因此真的不碰 Redis）。
    """
    recorded: list[tuple[str, str]] = []

    async def _record(pending_id: str) -> None:
        recorded.append((pending_id, KIND_MEMORY_EPISODE))

    monkeypatch.setitem(worker_module._CONSUMER_DISPATCHERS, KIND_MEMORY_EPISODE, _record)
    set_dispatch_hook(None)
    try:
        with TestClient(main_module.app):
            # lifespan 已跑完：`_dispatch_hook` 是私有装配位，这里是唯一可观测点。
            assert jobs_module._dispatch_hook is not None, "API 入口没有注入投递钩子——投递只能等兜底扫描"
            asyncio.run(dispatch_pending_write("00000000-0000-4000-8000-00000000000d", KIND_MEMORY_EPISODE))
    finally:
        set_dispatch_hook(None)

    assert recorded == [("00000000-0000-4000-8000-00000000000d", KIND_MEMORY_EPISODE)]
