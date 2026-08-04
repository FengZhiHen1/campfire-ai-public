"""事件总线单元测试——pi 语义：链式干预、阻断、fail-closed、通知容错。"""

from __future__ import annotations

import pytest
from py_agent_kernel.events import (
    EventBus,
    EventContext,
    EventResult,
    KernelEvent,
)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class TestNotificationEvents:
    @pytest.mark.asyncio
    async def test_notification_all_handlers_run(self, bus):
        calls = []
        bus.subscribe(KernelEvent.AGENT_START, lambda ctx: calls.append("a"))
        bus.subscribe(KernelEvent.AGENT_START, lambda ctx: calls.append("b"))
        await bus.emit(EventContext(KernelEvent.AGENT_START, "s1", {}))
        assert calls == ["a", "b"]

    @pytest.mark.asyncio
    async def test_notification_handler_error_continues(self, bus):
        """通知类事件 handler 抛异常：记录后继续执行后续 handler。"""
        calls = []

        def bad(ctx):
            raise RuntimeError("boom")

        bus.subscribe(KernelEvent.AGENT_START, bad)
        bus.subscribe(KernelEvent.AGENT_START, lambda ctx: calls.append("ok"))
        await bus.emit(EventContext(KernelEvent.AGENT_START, "s1", {}))
        assert calls == ["ok"]


class TestTransformableEvents:
    @pytest.mark.asyncio
    async def test_chained_modification_order(self, bus):
        """链式传递：后者看到前者的修改结果（扩展加载顺序即优先级）。"""

        def first(ctx):
            return EventResult(payload={"text": ctx.payload["text"] + "-A"})

        def second(ctx):
            return EventResult(payload={"text": ctx.payload["text"] + "-B"})

        bus.subscribe(KernelEvent.INPUT, first)
        bus.subscribe(KernelEvent.INPUT, second)
        result = await bus.emit(EventContext(KernelEvent.INPUT, "s1", {"text": "origin"}))
        assert result.payload["text"] == "origin-A-B"

    @pytest.mark.asyncio
    async def test_handler_returning_none_keeps_payload(self, bus):
        def noop(ctx):
            return None

        def modifier(ctx):
            return EventResult(payload={"text": "changed"})

        bus.subscribe(KernelEvent.INPUT, noop)
        bus.subscribe(KernelEvent.INPUT, modifier)
        result = await bus.emit(EventContext(KernelEvent.INPUT, "s1", {"text": "origin"}))
        assert result.payload["text"] == "changed"

    @pytest.mark.asyncio
    async def test_transformable_handler_error_skipped(self, bus):
        """可干预事件 handler 异常：跳过该修改，链式继续。"""

        def bad(ctx):
            raise RuntimeError("boom")

        def good(ctx):
            return EventResult(payload={"text": "good"})

        bus.subscribe(KernelEvent.INPUT, bad)
        bus.subscribe(KernelEvent.INPUT, good)
        result = await bus.emit(EventContext(KernelEvent.INPUT, "s1", {"text": "origin"}))
        assert result.payload["text"] == "good"

    @pytest.mark.asyncio
    async def test_input_handled_short_circuits(self, bus):
        """input handled=True 短路剩余 handler。"""
        calls = []

        def handler1(ctx):
            return EventResult(handled=True, payload=ctx.payload)

        def handler2(ctx):
            calls.append("h2")

        bus.subscribe(KernelEvent.INPUT, handler1)
        bus.subscribe(KernelEvent.INPUT, handler2)
        result = await bus.emit(EventContext(KernelEvent.INPUT, "s1", {"text": "x"}))
        assert result.handled is True
        assert calls == []


class TestBlockableEvents:
    @pytest.mark.asyncio
    async def test_tool_call_block(self, bus):
        """任一 handler 返回 block 即阻断，reason 回传。"""
        bus.subscribe(KernelEvent.TOOL_CALL, lambda ctx: EventResult(block=True, reason="权限不足"))
        result = await bus.emit(EventContext(KernelEvent.TOOL_CALL, "s1", {"tool_name": "x"}))
        assert result.block is True
        assert result.reason == "权限不足"

    @pytest.mark.asyncio
    async def test_tool_call_fail_closed_on_exception(self, bus):
        """fail-closed：可阻断事件 handler 抛异常一律视为 block。"""

        def bad(ctx):
            raise RuntimeError("handler 崩溃")

        bus.subscribe(KernelEvent.TOOL_CALL, bad)
        result = await bus.emit(EventContext(KernelEvent.TOOL_CALL, "s1", {"tool_name": "x"}))
        assert result.block is True
        assert "handler_error" in (result.reason or "")

    @pytest.mark.asyncio
    async def test_tool_call_pass_when_no_block(self, bus):
        bus.subscribe(KernelEvent.TOOL_CALL, lambda ctx: None)
        result = await bus.emit(EventContext(KernelEvent.TOOL_CALL, "s1", {"tool_name": "x"}))
        assert result.block is False

    @pytest.mark.asyncio
    async def test_first_block_wins(self, bus):
        """首个 block 生效（不继续执行后续 handler）。"""
        calls = []

        def blocker(ctx):
            return EventResult(block=True, reason="first")

        def later(ctx):
            calls.append("later")

        bus.subscribe(KernelEvent.TOOL_CALL, blocker)
        bus.subscribe(KernelEvent.TOOL_CALL, later)
        result = await bus.emit(EventContext(KernelEvent.TOOL_CALL, "s1", {}))
        assert result.block is True
        assert result.reason == "first"
        assert calls == []


class TestSubscription:
    def test_handlers_for_returns_copy(self, bus):
        bus.subscribe(KernelEvent.AGENT_START, lambda ctx: None)
        handlers = bus.handlers_for(KernelEvent.AGENT_START)
        handlers.clear()
        assert bus.has_handlers(KernelEvent.AGENT_START)

    def test_string_event_name_accepted(self, bus):
        bus.subscribe("tool_call", lambda ctx: None)
        assert bus.has_handlers(KernelEvent.TOOL_CALL)
