"""py-agent-kernel Session——消息序列化与 steering/follow-up 队列。

- 消息落盘：pydantic-ai ModelMessagesTypeAdapter（字节不兼容 pi，结构同构，§十）
- steering/follow-up：asap（当前 turn 工具执行完后注入）/ when_idle（agent 将终止时注入）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

# ===========================================================================
# 消息序列化（ModelMessagesTypeAdapter 落盘）
# ===========================================================================


def serialize_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """pydantic-ai 消息列表 → JSON 可序列化 dict 列表。"""
    return json.loads(ModelMessagesTypeAdapter.dump_json(messages))


def deserialize_messages(payload: list[dict[str, Any]]) -> list[ModelMessage]:
    """dict 列表 → pydantic-ai 消息列表（round-trip）。"""
    return list(ModelMessagesTypeAdapter.validate_python(payload))


# ===========================================================================
# steering / follow-up 队列（pi 语义 → PendingMessage 映射）
# ===========================================================================


class InjectionMode(StrEnum):
    """注入时机（pi steering/follow-up 语义）。"""

    ASAP = "asap"  # steering：当前 turn 工具执行完后注入
    WHEN_IDLE = "when_idle"  # follow-up：agent 将终止时注入


@dataclass
class PendingMessage:
    """待注入消息。"""

    content: str
    mode: InjectionMode


class PendingMessageQueue:
    """steering/follow-up 队列。

    - asap：下一轮 LLM 调用前注入（当前 turn 的工具执行完成后）
    - when_idle：agent 无更多动作、即将终止时注入（使其继续工作）
    """

    def __init__(self) -> None:
        self._queue: list[PendingMessage] = []

    def enqueue(self, content: str, mode: InjectionMode | str = InjectionMode.ASAP) -> None:
        self._queue.append(PendingMessage(content=content, mode=InjectionMode(mode)))

    def drain_asap(self) -> list[str]:
        """取走全部 asap 消息（turn 边界注入）。"""
        asap = [m.content for m in self._queue if m.mode == InjectionMode.ASAP]
        self._queue = [m for m in self._queue if m.mode != InjectionMode.ASAP]
        return asap

    def drain_when_idle(self) -> list[str]:
        """取走全部 when_idle 消息（agent 终止前注入）。"""
        idle = [m.content for m in self._queue if m.mode == InjectionMode.WHEN_IDLE]
        self._queue = [m for m in self._queue if m.mode != InjectionMode.WHEN_IDLE]
        return idle

    def __len__(self) -> int:
        return len(self._queue)


__all__ = [
    "serialize_messages",
    "deserialize_messages",
    "InjectionMode",
    "PendingMessage",
    "PendingMessageQueue",
]
