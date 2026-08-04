"""py-agent-kernel 事件系统 — 事件表与上下文数据结构（pi 语义移植）。

事件名与语义仿 pi（Agent内核框架 §四事件表），内核负责将 pydantic-ai
运行时接缝翻译成统一事件面。

干预性分级：
- 通知事件：handler 抛异常记录后继续
- 可干预事件（input/context/message_end/tool_result/before_agent_start）：
  handler 链式传递修改结果
- 可阻断事件（tool_call）：任一 handler 返回 block 即阻断；
  handler 抛异常一律视为 block（fail-closed，§八）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class KernelEvent(StrEnum):
    """内核事件表（Agent内核框架 §四，与 pi 事件名对齐）。"""

    # 会话生命周期
    SESSION_START = "session_start"
    SESSION_SHUTDOWN = "session_shutdown"

    # 输入与 Agent 运行
    INPUT = "input"
    BEFORE_AGENT_START = "before_agent_start"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"

    # turn（LLM 调用 + 工具执行为一 turn）
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # 消息生命周期（流式增量经 message_update）
    MESSAGE_START = "message_start"
    MESSAGE_UPDATE = "message_update"
    MESSAGE_END = "message_end"

    # 上下文构建（每次 LLM 调用前）
    CONTEXT = "context"

    # 工具生命周期
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"
    TOOL_EXECUTION_END = "tool_execution_end"

    # 资源与压缩
    RESOURCES_DISCOVER = "resources_discover"
    SESSION_BEFORE_COMPACT = "session_before_compact"


# 可干预事件（链式修改：handler 返回修改后的 payload，后者看到前者的结果）
TRANSFORMABLE_EVENTS: frozenset[KernelEvent] = frozenset(
    {
        KernelEvent.INPUT,
        KernelEvent.BEFORE_AGENT_START,
        KernelEvent.CONTEXT,
        KernelEvent.MESSAGE_END,
        KernelEvent.TOOL_RESULT,
        KernelEvent.SESSION_BEFORE_COMPACT,
    }
)

# 可阻断事件（任一 handler 返回 block 即阻断；异常一律视为 block——fail-closed）
BLOCKABLE_EVENTS: frozenset[KernelEvent] = frozenset({KernelEvent.TOOL_CALL})


@dataclass
class EventResult:
    """事件 handler 返回结果。

    - payload: 可干预事件的修改结果（链式传递给下一个 handler）
    - block: 可阻断事件的阻断标记（tool_call）
    - reason: 阻断原因（回传给模型作为工具错误）
    - handled: input 事件已处理标记（短路 Agent 循环）
    """

    payload: dict[str, Any] | None = None
    block: bool = False
    reason: str | None = None
    handled: bool = False


@dataclass
class EventContext:
    """事件上下文——handler 的输入。

    payload 为事件数据，事件语义：
    - input: {"text": str}（用户输入）
    - before_agent_start: {"system_prompt": str, "inject_messages": list}（可改系统提示/注入消息）
    - context: {"messages": list}（LLM 调用前的消息列表，非破坏修改）
    - message_start/update/end: {"message": Any, "delta": str|None}
    - tool_call: {"tool_name": str, "tool_call_id": str, "params": dict}
    - tool_result: {"tool_name": str, "tool_call_id": str, "result": dict, "is_error": bool}
    - turn_start/end: {"turn_index": int}
    """

    event: KernelEvent
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "KernelEvent",
    "EventContext",
    "EventResult",
    "TRANSFORMABLE_EVENTS",
    "BLOCKABLE_EVENTS",
]
