"""按 `kind` 分派的机械检查与分派表行为。

对应 `docs/技术设计/technical-details/写入路径.md` 第 4 节第 3 条「消费：按 kind 分派」。
本文件不连数据库、不连 Redis：它钉的是分派表本身——哪些 kind 有消费者、没有消费者的
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


def test_every_kind_has_a_consumer() -> None:
    """`KINDS` 的每个取值都必须有消费者（T12 已给 `profile_item` 接上，缺口清零）。

    这条防的是「将来加第三种 kind 时忘了分派」：分派表是 `worker._CONSUMER_DISPATCHERS`，
    没有键的 kind 不会被投给任何消费者（`dispatch_pending_write_to_queue` 显式跳过），
    因此「缺少消费者」必须是被检查的事实，而不是运行期才发现。

    它不是「永远不会失败的检查」：新增第三种 kind 却没注册消费者时 `missing`
    非空 → 失败，并给出改法。

    为什么不用 `xfail(strict=True)` 表达缺口：xfail 期间「新增第三种 kind」
    仍然只会是 XFAIL（静默通过），本检查防第二种情形的能力会被一起锁掉。
    T12 之前这里钉的是已知唯一缺口 `{KIND_PROFILE_ITEM}`；接上消费者后按当时的
    注释改成 `assert not missing`，缺口到期即收口。
    """
    missing = KINDS - worker_module.CONSUMED_KINDS

    assert not missing, (
        f"缺消费者的 kind = {sorted(missing)}。"
        "新增了 kind：请在 worker._CONSUMER_DISPATCHERS 里注册它的消费者；"
        "否则这些记录会一直停在 pending，且每轮兜底扫描都为它们白占条数预算。"
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
    """无消费者的 kind：不投给任何消费者、记一条指名道姓的 warning。

    「显式跳过」不是「静默丢弃」：日志必须带 kind 与 pending_id，运维才看得出
    「有一批写入在等消费者」。记录本身的处置是不终结（仍是 `pending`，由兜底扫描
    在消费者接上后带回）——这一点由
    `apps/api/tests/test_pending_write_sweep_integration.py` 的两条集成用例钉住。

    为什么用一个不在 `KINDS` 里的 kind 而不是 `profile_item`：T12 已给 `profile_item`
    接上消费者，它不再是「无消费者的 kind」；拿它有消费者的事实去测跳过分支，
    测的会是分派表命中那条路。而跳过分支的输入本就是「一个没有键的 kind」，
    造一个这样的 kind 才与分支的判据同构（`KINDS` 是闭集，
    `enqueue` 不会写进非法 kind，因此这一分支在真实数据下由「尚未注册的新 kind」触发）。
    """
    pending_id = "00000000-0000-4000-8000-00000000000b"
    kind_without_consumer = "kind_not_yet_registered"

    async def _must_not_be_called(called_with: str) -> None:
        raise AssertionError(f"无消费者的 kind 不得投给别的消费者：{called_with}")

    assert kind_without_consumer not in worker_module._CONSUMER_DISPATCHERS, (
        "构造的前提失效：这个 kind 已经有消费者了，本用例就测不到跳过分支"
    )
    for kind in list(worker_module._CONSUMER_DISPATCHERS):
        monkeypatch.setitem(worker_module._CONSUMER_DISPATCHERS, kind, _must_not_be_called)

    with caplog.at_level(logging.WARNING):
        await worker_module.dispatch_pending_write_to_queue(pending_id, kind_without_consumer)

    assert pending_id in caplog.text and kind_without_consumer in caplog.text, (
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
