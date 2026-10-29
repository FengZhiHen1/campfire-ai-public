"""模型调用「静默挂住」的守卫：`_drain` 的拉取上界与它的失败归因。

## 为什么需要这条判据（实测，不是假想）

2026-10-28 同一台机器、同一晚，三轮运行全部以 `reason=timeout` 结束、耗时 300 秒，
但**各自只有 1 次模型调用**，输出 81 / 245 / 734 个 token——0.3～2.5 token/秒，
而直接压测同一端点是 75 token/秒。连接没断，只是几乎不吐字。

原来的 `_drain` 每次拉取等的是「剩余整轮预算」，于是这种调用会把整轮预算一口吃光：
使用者等满五分钟，拿不到任何可读内容，页面上却只写「运行超时」——把「提供方挂住」
说成了「我们的预算不够」。

现在每次拉取等 `min(剩余预算, 静默上界)`：静默超过上界就抛 `_ModelStalled`，
由 `_failed_from_exception` 归成 `model_unavailable`（可重试），detail 写明静默了多久。

边界：这三条用例只碰 `_drain` 与 `_failed_from_exception` 两个纯函数/协程入口，
不连数据库、不连 Redis、不调模型。
"""

from __future__ import annotations

import time
from typing import cast

import pytest
from agents.result import RunResultStreaming

from campfire.agent.context import CitationIndex, CitationRecorder
from campfire.agent.runtime import RunUsage
from campfire.agent.runtime import runner as runner_module
from campfire.agent.runtime.runner import (
    _Budget,
    _drain,
    _failed_from_exception,
    _ModelStalled,
    _SdkEvent,
    _TimedOut,
)


class _NullIndex:
    """引用索引的哑实现：本用例只关心失败事件里写什么，不碰索引。"""

    async def write(self, record: object) -> None:  # pragma: no cover —— 不会走到
        raise AssertionError(f"静默挂住时不该写引用索引：{record!r}")


class _StalledStream:
    """先给一个事件，然后**永不**再给（模拟连接挂住：不结束、也不报错）。"""

    def __init__(self, *, first_event: object | None = object()) -> None:
        self._first = first_event
        self._yielded = False

    def __aiter__(self) -> _StalledStream:
        return self

    async def __anext__(self) -> object:
        if not self._yielded and self._first is not None:
            self._yielded = True
            return self._first
        # 真正的「挂住」：不返回、不抛错，一直等下去。
        while True:
            await _sleep_forever()


async def _sleep_forever() -> None:  # pragma: no cover —— 只用于挂住，正常路径不会返回
    import asyncio

    await asyncio.sleep(3600)


def _drain_host(stream: _StalledStream) -> object:
    """`_drain` 只用到 `stream_events()`。

    不构造真的 `RunResultStreaming`（它要一整棵 SDK 运行状态），而是给一个只有这一个方法的
    宿主对象，并在调用处 `cast` 成协议要求的类型——类型检查因此仍然有效，
    而用例不必假装自己是一条真运行。
    """

    class _Host:
        def stream_events(self) -> _StalledStream:
            return stream

    return _Host()


@pytest.mark.anyio
async def test_stalled_call_raises_before_the_run_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """预算还很充裕、但对端不吐字 ⇒ 抛 `_ModelStalled`，而不是等到整轮上限。

    判据刻意用「静默上界 0.05 秒 / 预算 30 秒」这种量级，避免用例真的等 90 秒：
    被测的是**判定关系**（谁先触发），不是那个具体秒数。
    """
    monkeypatch.setattr(runner_module, "AGENT_MODEL_STALL_SECONDS", 0.05)
    budget = _Budget(deadline=time.monotonic() + 2.0)

    started = time.monotonic()
    drained: list[object] = []
    with pytest.raises(_ModelStalled):
        async for item in _drain(cast(RunResultStreaming, _drain_host(_StalledStream())), budget):
            drained.append(item)
    elapsed = time.monotonic() - started

    # 先给出来的那个事件必须已经被交出去（不能因为后面挂了就把已产出的丢掉）。
    assert len(drained) == 1
    assert isinstance(drained[0], _SdkEvent)
    # **关键判据是耗时**，不是「抛了哪个异常」：只要等待时长仍等于剩余预算，
    # 「抛出 _ModelStalled」在任何预算下都能成立（预算耗尽后同样走到这条分支），
    # 那样这条用例对「有没有静默上界」毫无分辨力（消融实测：去掉上界仍全绿）。
    assert elapsed < 1.0, (
        f"静默上界 0.05 秒、预算 2 秒，却等了 {elapsed:.2f} 秒才判挂住："
        "说明拉取仍在等「剩余整轮预算」，静默上界没有生效"
    )


@pytest.mark.anyio
async def test_exhausted_budget_still_reports_run_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """剩余预算不足静默上界 ⇒ 仍是「整轮到期」（`_TimedOut`），不能抢着报「挂住」。

    这条是上一条的对照臂：只证明「会抛 `_ModelStalled`」而不区分场景，就会把
    「运行到点结束」误报成「提供方挂住」——那是把责任推给对端。
    """
    monkeypatch.setattr(runner_module, "AGENT_MODEL_STALL_SECONDS", 30.0)
    budget = _Budget(deadline=time.monotonic() + 0.05)

    items = [
        item async for item in _drain(cast(RunResultStreaming, _drain_host(_StalledStream(first_event=None))), budget)
    ]

    assert len(items) == 1
    assert isinstance(items[0], _TimedOut)


def test_stall_failure_is_retryable_model_unavailable_with_a_clear_detail() -> None:
    """静默挂住要归成 `model_unavailable`（可重试），detail 说清「挂了多久、什么形态」。"""
    recorder = CitationRecorder(cast(CitationIndex, _NullIndex()), run_id="run-stall")
    usage = RunUsage()

    event = _failed_from_exception(_ModelStalled("stalled"), recorder, usage, time.monotonic())

    assert event.code == "model_unavailable"
    # detail 必须能让人判断处置：写「静默 N 秒 / 连接还在但没有数据」，
    # 而不是把 `_ModelStalled` 这个类名甩给使用者。
    assert "静默超过" in event.detail
    assert "连接还在" in event.detail
