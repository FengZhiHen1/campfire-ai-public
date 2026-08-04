"""py-agent-kernel 事件总线（pi 语义移植）。

语义规则（Agent内核框架 §四/§八）：
- handler 按扩展加载顺序依次执行；
- 可干预事件的修改在 handler 间链式传递（后者看到前者的结果）；
- tool_call 任一 handler 返回 block 即阻断（reason 回传模型）；
- handler 抛异常：通知类事件记录后继续；可阻断类事件一律视为 block（fail-closed）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from py_agent_kernel.events.types import (
    BLOCKABLE_EVENTS,
    TRANSFORMABLE_EVENTS,
    EventContext,
    EventResult,
    KernelEvent,
)

logger = logging.getLogger("py_agent_kernel.events")

# handler 签名：同步或异步，接收 EventContext，返回 EventResult 或 None
EventHandler = Callable[[EventContext], "EventResult | None | Awaitable[EventResult | None]"]


class EventBus:
    """事件总线——订阅注册与分发执行。

    订阅顺序 = 扩展加载顺序（注册即优先级，pi 语义）。
    """

    def __init__(self) -> None:
        self._handlers: dict[KernelEvent, list[EventHandler]] = {}

    # ------------------------------------------------------------------
    # 订阅
    # ------------------------------------------------------------------

    def subscribe(self, event: KernelEvent | str, handler: EventHandler) -> None:
        """注册事件 handler（按注册顺序执行）。"""
        evt = KernelEvent(event)
        self._handlers.setdefault(evt, []).append(handler)

    def handlers_for(self, event: KernelEvent) -> list[EventHandler]:
        """返回事件的全部 handler（只读视图）。"""
        return list(self._handlers.get(event, []))

    def has_handlers(self, event: KernelEvent) -> bool:
        return bool(self._handlers.get(event))

    # ------------------------------------------------------------------
    # 分发
    # ------------------------------------------------------------------

    async def emit(self, ctx: EventContext) -> EventResult:
        """分发事件并按干预性语义聚合 handler 结果。

        Returns:
            EventResult：聚合后的最终结果（链式修改后的 payload、阻断标记等）。
        """
        handlers = self._handlers.get(ctx.event, [])
        if not handlers:
            return EventResult(payload=ctx.payload)

        if ctx.event in BLOCKABLE_EVENTS:
            return await self._emit_blockable(ctx, handlers)
        if ctx.event in TRANSFORMABLE_EVENTS:
            return await self._emit_transformable(ctx, handlers)
        return await self._emit_notification(ctx, handlers)

    # ------------------------------------------------------------------
    # 干预性分发实现
    # ------------------------------------------------------------------

    async def _emit_notification(self, ctx: EventContext, handlers: list[EventHandler]) -> EventResult:
        """通知事件：全部执行；handler 抛异常记录后继续（pi 原生默认）。"""
        for handler in handlers:
            try:
                await self._invoke(handler, ctx)
            except Exception:
                logger.exception(
                    "事件 handler 异常（通知类，继续执行）",
                    extra={"event": ctx.event.value, "session_id": ctx.session_id},
                )
        return EventResult(payload=ctx.payload)

    async def _emit_transformable(self, ctx: EventContext, handlers: list[EventHandler]) -> EventResult:
        """可干预事件：链式传递 payload（后者看到前者的修改）。

        handler 异常：记录并跳过该 handler 的修改（链式继续）。
        input 事件的 handled=True 会短路剩余 handler。
        """
        current_payload: dict[str, Any] = ctx.payload
        handled = False
        for handler in handlers:
            try:
                result = await self._invoke(handler, EventContext(ctx.event, ctx.session_id, current_payload))
            except Exception:
                logger.exception(
                    "事件 handler 异常（可干预类，跳过该修改）",
                    extra={"event": ctx.event.value, "session_id": ctx.session_id},
                )
                continue
            if result is None:
                continue
            if result.payload is not None:
                current_payload = result.payload
            if result.handled:
                handled = True
                break
        return EventResult(payload=current_payload, handled=handled)

    async def _emit_blockable(self, ctx: EventContext, handlers: list[EventHandler]) -> EventResult:
        """可阻断事件：任一 handler block 即阻断（fail-closed：异常视为 block）。"""
        for handler in handlers:
            try:
                result = await self._invoke(handler, ctx)
            except Exception as exc:
                logger.exception(
                    "可阻断事件 handler 异常，fail-closed 视为阻断",
                    extra={"event": ctx.event.value, "session_id": ctx.session_id},
                )
                return EventResult(block=True, reason=f"handler_error: {exc}", payload=ctx.payload)
            if result is not None and result.block:
                return EventResult(block=True, reason=result.reason, payload=ctx.payload)
        return EventResult(payload=ctx.payload)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    async def _invoke(handler: EventHandler, ctx: EventContext) -> EventResult | None:
        """统一调用 handler（兼容同步/异步）。"""
        import inspect

        result = handler(ctx)
        if inspect.isawaitable(result):
            result = await result
        return result


__all__ = ["EventBus", "EventHandler"]
