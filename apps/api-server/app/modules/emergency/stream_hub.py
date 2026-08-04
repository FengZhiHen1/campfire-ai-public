"""应急面 SSE 事件枢纽（AI 服务接口契约 §三）。

职责：
- 会话事件持久缓冲（sequence 单调递增——Last-Event-Id 续传锚点）
- 订阅分发（多客户端跟随同一会话）
- 心跳保活（15s）
- 终态语义：done / error 后关闭连接

设计：进程内内存枢纽（MVP 单实例部署；多实例时经 Redis Pub/Sub 扩展——
本期不建，需求未达）。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from py_schemas.streaming import SseEventType

_HEARTBEAT_INTERVAL_S = 15.0


@dataclass
class StreamEvent:
    """缓冲事件（sequence 为会话内单调递增锚点）。"""

    sequence: int
    event_type: str
    data: dict[str, Any]

    def to_sse_frame(self) -> str:
        return f"event: {self.event_type}\nid: {self.sequence}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


@dataclass
class _SessionStream:
    events: list[StreamEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    terminal: bool = False  # done/error 已发
    created_at: float = field(default_factory=time.monotonic)


class ConsultStreamHub:
    """应急会话事件枢纽（内存态单例）。"""

    def __init__(self) -> None:
        self._streams: dict[str, _SessionStream] = {}

    def get_or_create(self, session_id: str) -> _SessionStream:
        stream = self._streams.get(session_id)
        if stream is None:
            stream = _SessionStream()
            self._streams[session_id] = stream
        return stream

    async def publish(self, session_id: str, event_type: SseEventType | str, data: dict[str, Any]) -> None:
        """发布事件（缓冲 + 唤醒全部订阅者）。"""
        stream = self.get_or_create(session_id)
        evt_type = event_type.value if isinstance(event_type, SseEventType) else event_type
        async with stream.condition:
            sequence = stream.events[-1].sequence + 1 if stream.events else 1
            stream.events.append(StreamEvent(sequence=sequence, event_type=evt_type, data=data))
            if evt_type in (SseEventType.DONE.value, SseEventType.ERROR.value):
                stream.terminal = True
            stream.condition.notify_all()

    async def stream(self, session_id: str, last_event_id: int = 0) -> AsyncIterator[str]:
        """订阅事件流（Last-Event-Id 续传：从 sequence+1 重放）。

        终态（done/error）后结束；空闲 15s 发心跳。
        """
        stream = self.get_or_create(session_id)
        cursor = last_event_id

        while True:
            async with stream.condition:
                # 先回放缓冲区中 sequence > cursor 的事件
                pending = [e for e in stream.events if e.sequence > cursor]
                if not pending and not stream.terminal:
                    try:
                        await asyncio.wait_for(stream.condition.wait(), timeout=_HEARTBEAT_INTERVAL_S)
                    except asyncio.TimeoutError:
                        yield "event: heartbeat\ndata: {}\n\n"
                        continue
                    pending = [e for e in stream.events if e.sequence > cursor]

            for event in pending:
                cursor = event.sequence
                yield event.to_sse_frame()
                if event.event_type in (SseEventType.DONE.value, SseEventType.ERROR.value):
                    return

            # 缓冲区空且已终态（重连迟到场景）：直接结束
            if stream.terminal and not pending:
                return

    def drop(self, session_id: str) -> None:
        """会话流清理（终态后延迟清理由调用方决定）。"""
        self._streams.pop(session_id, None)


_hub: ConsultStreamHub | None = None


def get_stream_hub() -> ConsultStreamHub:
    """获取全局事件枢纽单例。"""
    global _hub
    if _hub is None:
        _hub = ConsultStreamHub()
    return _hub


__all__ = ["ConsultStreamHub", "StreamEvent", "get_stream_hub"]
