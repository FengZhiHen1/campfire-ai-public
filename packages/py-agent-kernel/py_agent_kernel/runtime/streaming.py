"""py-agent-kernel runtime——流式装配（AgentStreamEvent → 内核流事件）。

映射规则（Agent内核框架 §十 偏差清单·接缝层聚合，探针验证 2026-08-04）：
- PartStartEvent(TextPart)      → message_start
- PartDeltaEvent(TextPartDelta) → message_update（delta 文本）
- PartEndEvent(TextPart)        → message_end
- FunctionToolCallEvent         → tool_execution_start（tool_name/params）
- FunctionToolResultEvent       → tool_execution_end（result）

宿主（api-server SSE）消费 KernelStreamEvent 序列。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)


@dataclass
class KernelStreamEvent:
    """内核流事件（宿主 SSE 消费面）。

    type: message_start / message_update / message_end /
          tool_execution_start / tool_execution_update / tool_execution_end /
          turn_start / turn_end / agent_start / agent_end
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)


def translate_stream_event(event: AgentStreamEvent) -> KernelStreamEvent | None:
    """pydantic-ai AgentStreamEvent → 内核流事件。

    返回 None 表示该事件不映射（如 FinalResultEvent——由 run 结果承载）。
    """
    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, TextPart):
            return KernelStreamEvent(
                type="message_start",
                data={"index": event.index, "content": part.content},
            )
        if isinstance(part, ThinkingPart):
            return KernelStreamEvent(
                type="message_start",
                data={"index": event.index, "kind": "thinking", "content": part.content},
            )
        return None

    if isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta):
            return KernelStreamEvent(
                type="message_update",
                data={"index": event.index, "delta": delta.content_delta},
            )
        if isinstance(delta, ThinkingPartDelta):
            return KernelStreamEvent(
                type="message_update",
                data={"index": event.index, "kind": "thinking", "delta": delta.content_delta},
            )
        return None

    if isinstance(event, PartEndEvent):
        part = event.part
        if isinstance(part, TextPart):
            return KernelStreamEvent(
                type="message_end",
                data={"index": event.index, "content": part.content},
            )
        if isinstance(part, ThinkingPart):
            return KernelStreamEvent(
                type="message_end",
                data={"index": event.index, "kind": "thinking", "content": part.content},
            )
        return None

    if isinstance(event, FunctionToolCallEvent):
        part = event.part
        return KernelStreamEvent(
            type="tool_execution_start",
            data={
                "tool_name": part.tool_name,
                "tool_call_id": part.tool_call_id,
                "params": part.args if isinstance(part.args, dict) else {"raw": part.args},
            },
        )

    if isinstance(event, FunctionToolResultEvent):
        result_part = event.result
        return KernelStreamEvent(
            type="tool_execution_end",
            data={
                "tool_name": getattr(result_part, "tool_name", ""),
                "tool_call_id": getattr(result_part, "tool_call_id", ""),
                "content": str(getattr(result_part, "content", ""))[:2000],
            },
        )

    return None


__all__ = ["KernelStreamEvent", "translate_stream_event"]
