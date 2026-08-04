# @contract
"""SSE 流式协议 — Pydantic 数据模型定义（ADR-009/015 目标态）。

统一 SSE 协议（AI 服务接口契约 §三）+ 应急面消息事件扩展：
- 统一族：chunk / result / done / error / heartbeat（+ sequence 续传锚点）
- 应急面消息事件（时刻分层产出，以 message 插入聊天容器）：
  safety_card / stage_question / redline_guide / fallback_notice

事件外壳：event: {type} + id: {sequence} + data: {json}，
sequence 为会话内单调递增整数（Last-Event-Id 续传锚点）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from py_schemas.base import CampfireBaseModel
from py_schemas.emergency import (
    FallbackNoticeDto,
    RedlineGuideDto,
    SafetyCardDto,
    StageQuestionDto,
)


class StreamErrorCode(StrEnum):
    """SSE 流式推送错误码（{模块}_{场景} 命名，AI 服务接口契约 §4.2）。"""

    SESSION_NOT_FOUND = "CONSULT_SESSION_EXPIRED"
    GENERATION_FAILED = "LLM_UNAVAILABLE"
    STREAM_TIMEOUT = "STREAM_TIMEOUT"
    CONCURRENCY_LIMIT_EXCEEDED = "CONCURRENCY_LIMIT_EXCEEDED"
    OUTPUT_SCHEMA_VIOLATION = "OUTPUT_SCHEMA_VIOLATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class SseEventType(StrEnum):
    """SSE 事件类型族（统一族 + 应急面消息事件扩展）。"""

    # 统一族（AI 服务接口契约 §3.3）
    CHUNK = "chunk"
    RESULT = "result"
    HEARTBEAT = "heartbeat"
    DONE = "done"
    ERROR = "error"
    # 应急面消息事件（时刻分层产出）
    SAFETY_CARD = "safety_card"
    STAGE_QUESTION = "stage_question"
    REDLINE_GUIDE = "redline_guide"
    FALLBACK_NOTICE = "fallback_notice"


# ===========================================================================
# 统一族事件载荷
# ===========================================================================


class ChunkEvent(CampfireBaseModel):
    """chunk 事件载荷——文本增量（生成型，客户端增量渲染）。"""

    text: str = Field(..., max_length=4096, description="文本增量")


class ResultEvent(CampfireBaseModel):
    """result 事件载荷——结构化产出（经 Pydantic 契约校验后发出）。"""

    contract: str = Field(..., description="py-schemas 契约名（如 EmergencyPlan）")
    payload: dict[str, Any] = Field(..., description="契约校验通过的结构化产出")


class DoneEvent(CampfireBaseModel):
    """done 事件载荷——正常终态（其后关闭连接）。"""

    finish_reason: str = Field(default="COMPLETE", description="终止原因（COMPLETE/PARTIAL/ERROR）")


class HeartbeatEvent(CampfireBaseModel):
    """heartbeat 事件载荷——连接保活（15s 间隔，空载荷）。"""


class ErrorEvent(CampfireBaseModel):
    """error 事件载荷——错误终态（其后关闭连接）。"""

    error_code: str = Field(..., description="错误码（{模块}_{场景}）")
    detail: str = Field(..., max_length=500, description="中文友好提示（无技术堆栈）")
    trace_id: str | None = Field(default=None, description="追踪 ID（观测约定）")


# ===========================================================================
# 应急面消息事件载荷
# ===========================================================================


class SafetyCardEvent(CampfireBaseModel):
    """safety_card 事件载荷——安全卡消息（大字号强视觉样式）。"""

    card: SafetyCardDto


class StageQuestionEvent(CampfireBaseModel):
    """stage_question 事件载荷——阶段单点问题（内嵌 quick-reply 按钮）。"""

    question: StageQuestionDto


class RedlineGuideEvent(CampfireBaseModel):
    """redline_guide 事件载荷——红线指引（标红置顶，锁定视觉重心）。"""

    guide: RedlineGuideDto


class FallbackNoticeEvent(CampfireBaseModel):
    """fallback_notice 事件载荷——兜底强提示 + 求助指引。"""

    notice: FallbackNoticeDto


# ===========================================================================
# 推送会话上下文（纯内存）
# ===========================================================================


class StreamSession(CampfireBaseModel):
    """推送会话上下文（内存态，不持久化）。

    sequence 为会话内单调递增整数——SSE id 字段与 Last-Event-Id 续传锚点。
    """

    stream_id: str = Field(..., description="流标识（= 咨询会话 ID）")
    sequence: int = Field(default=0, ge=0, description="已推送最后事件的 sequence")
    created_at: float = Field(..., description="创建时间戳（time.monotonic）")
    first_chunk_sent_at: float | None = Field(default=None, description="首 chunk 推送时间（TTFT 观测）")


__all__ = [
    "StreamErrorCode",
    "SseEventType",
    "ChunkEvent",
    "ResultEvent",
    "DoneEvent",
    "HeartbeatEvent",
    "ErrorEvent",
    "SafetyCardEvent",
    "StageQuestionEvent",
    "RedlineGuideEvent",
    "FallbackNoticeEvent",
    "StreamSession",
]
