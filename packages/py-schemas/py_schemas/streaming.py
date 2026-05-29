"""CSLT-04 流式应答推送 — Pydantic 数据模型定义。

提供 SSE 事件载荷的 Pydantic 模型和流式推送相关枚举。
字段名、类型、必填性与 docs/contracts/CSLT-04/ 下 JSON Schema 契约完全一致。

模型清单：
    ChunkEvent       SSE chunk 事件 data 载荷
    DoneEvent        SSE done 事件 data 载荷
    HeartbeatEvent   SSE 心跳保活事件（空载荷）
    ErrorEvent       SSE error 事件 data 载荷
    StreamErrorCode  SSE 流推送错误码枚举
    StreamSession    推送会话上下文（纯内存，不持久化到数据库）
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from py_schemas.base import CampfireBaseModel


class StreamErrorCode(StrEnum):
    """SSE 流式推送场景专用的错误码枚举。

    Contract: docs/contracts/CSLT-04/StreamErrorCode.json

    Values:
        SESSION_NOT_FOUND: 重连时流会话不存在或已过期（超过 5 分钟 TTL）或从未创建
        GENERATION_FAILED: 上游 CSLT-03 生成异常，Generator 提前退出
        STREAM_TIMEOUT: 推送响应超时（首 chunk 5s 软超时已触发进度提示）
        CONCURRENCY_LIMIT_EXCEEDED: 并发连接数达到 SSE_MAX_CONCURRENT_CONNECTIONS 上限
        INTERNAL_ERROR: 服务端未预期的内部异常
    """

    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    GENERATION_FAILED = "GENERATION_FAILED"
    STREAM_TIMEOUT = "STREAM_TIMEOUT"
    CONCURRENCY_LIMIT_EXCEEDED = "CONCURRENCY_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ChunkEvent(CampfireBaseModel):
    """SSE chunk 事件的 data 字段载荷。

    Contract: docs/contracts/CSLT-04/ChunkEvent.json

    承载上游 CSLT-03 产出的每段文本增量（delta）及递增序列号。
    每个 chunk 事件对应 SSE 协议中一个 ``event: chunk`` 帧。
    text 字段原样透传 CSLT-03/GenerationChunk.text，不做任何修改、截断或格式转换。
    """

    text: str = Field(
        ...,
        max_length=4096,
        description="当前 chunk 的文本增量，仅包含段落内容文本（JSON 语法字符已剥离）。",
        examples=["请保持冷静，先将孩子带离当前环境"],
    )
    sequence: int = Field(
        ...,
        ge=1,
        description="单调递增的序列号，从 1 开始计数。用于：(1) 前端检测丢帧（比对相邻 sequence"
        "是否连续）；(2) 断点续传定位（重连时 Last-Event-Id 携带最后成功接收的 sequence，"
        "CSLT-04 从中断位置续传）；(3) SSE id: 字段值与 sequence 保持一致。",
        examples=[1, 2, 3],
    )
    section: str | None = Field(
        default=None,
        description="当前 chunk 所属的段落标题，前端据此增量追加到对应 planSections 卡片。"
        "None 表示非内容文本。",
    )


class DoneEvent(CampfireBaseModel):
    """SSE done 事件的 data 字段载荷。

    Contract: docs/contracts/CSLT-04/DoneEvent.json

    标记流式推送的终止，并在 finish_reason 字段中说明终止原因。
    无论流正常结束、上游异常中止还是超时截断，try/finally 块必须保证
    发送此事件后再关闭 SSE 连接（满足 AC-04 流结束信号可靠）。
    finish_reason 值直接映射自 CSLT-03/GenerationStatus 的五种状态值。
    """

    finish_reason: str = Field(
        ...,
        description="流式推送的终止原因，值直接映射自 CSLT-03/GenerationStatus 枚举："
        "COMPLETE=正常完成、PARTIAL=部分生成（超时截断但已产出至少一个完整段落）、"
        "BLOCKED=安全阻断（输出预设安全文本，未调用 LLM）、TIMEOUT=完全超时"
        "（无任何文本产出）、ERROR=不可恢复错误（API 不可用、网络断开等）",
        examples=["COMPLETE"],
    )
    sequence: int | None = Field(
        default=None,
        ge=1,
        description="最后的 sequence 号（可选）。当 finish_reason 为非 COMPLETE"
        "状态时，告知前端已成功推送的最后一个 chunk 的序列号，便于前端确认"
        "已接收内容的范围。",
    )
    referenced_slice_ids: list[str] = Field(
        default_factory=list,
        description="LLM 输出中实际引用的案例切片 ID 列表（从 [N] 标记反向查找得到）",
    )
    crisis_level: str | None = Field(
        default=None,
        description="危机分级结果（mild/moderate/severe）",
    )
    referenced_cases: list[dict[str, str]] = Field(
        default_factory=list,
        description="被引用案例的简要信息列表，每条含 slice_id、case_id、case_title、slice_text(前200字)",
    )
    confidence_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="置信度评分（0~1），来自后校验管线",
    )
    verdict: str | None = Field(
        default=None,
        description="置信度校验判定结论（PASS/APPEND_WARNING/FORCE_BLOCK）",
    )
    ticket_triggered: bool = Field(
        default=False,
        description="是否已触发人工工单创建",
    )
    sections: dict[str, list[str]] = Field(
        default_factory=dict,
        description="从 LLM JSON 输出解析出的四段式结构化数据。"
        "key 为段落标题（即时安全干预动作/情绪安抚话术/后续观察指标/就医判断标准），"
        "value 为该段落的建议文本列表。JSON 解析失败时各段落为空列表。",
    )


class HeartbeatEvent(CampfireBaseModel):
    """SSE 心跳保活事件的 data 载荷。

    Contract: docs/contracts/CSLT-04/HeartbeatEvent.json

    空对象 {}，不携带 data 负载。仅通过 ``event: heartbeat`` 帧告知前端
    SSE 连接处于活跃状态，用于防止移动端网络或中间代理因长时间无数据而断开连接。
    """


class ErrorEvent(CampfireBaseModel):
    """SSE error 事件的 data 字段载荷。

    Contract: docs/contracts/CSLT-04/ErrorEvent.json

    携带机器可读的 error_code 和人类可读的 detail 说明，
    用于在推送过程中发生异常时告知前端故障原因。
    error_code 使用 StreamErrorCode 枚举值，detail 用于前端 ErrorBoundary 或 toast 提示。
    """

    error_code: StreamErrorCode = Field(
        ...,
        description="机器可读的错误码，必须为 StreamErrorCode 枚举中的值："
        "SESSION_NOT_FOUND=重连时流会话不存在或已过期、"
        "GENERATION_FAILED=上游 CSLT-03 生成异常、"
        "STREAM_TIMEOUT=推送响应超时、"
        "CONCURRENCY_LIMIT_EXCEEDED=并发连接数超过上限、"
        "INTERNAL_ERROR=服务端未预期的内部异常",
        examples=["SESSION_NOT_FOUND"],
    )
    detail: str = Field(
        ...,
        max_length=500,
        description="人类可读的错误详情文本，用于前端直接展示（toast/提示条/"
        "ErrorBoundary）。内容为中文友好提示，不包含技术堆栈信息。",
        examples=["当前推送会话不存在或已过期，请重新发起咨询"],
    )


class StreamSession(CampfireBaseModel):
    """推送会话的完整上下文，纯内存存储，不持久化到数据库。

    每个会话使用 stream-{uuid4} 格式的 stream_id 标识。
    创建时自动生成 stream_id 并记录当前单调时钟时间戳。
    """

    stream_id: str = Field(
        ...,
        description="流标识符，格式 stream-{uuid4}，通过首次 SSE 连接响应头 "
        "X-Stream-Id 返回前端。",
        examples=["stream-a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
    chunk_buffer: dict[int, str] = Field(
        default_factory=dict,
        description="已推送的 chunk 文本缓冲区，key 为 sequence 号（从 1 开始），"
        "用于断点续传时跳过已推送内容。",
    )
    sequence: int = Field(
        default=0,
        ge=0,
        description="当前已推送的最后一个 chunk 的 sequence 号。0 表示尚未推送任何 chunk。",
    )
    created_at: float = Field(
        ...,
        description="会话创建时间戳（time.monotonic()），用于 TTL 过期判定。",
        examples=[1716800000.0],
    )
    first_chunk_sent_at: float | None = Field(
        default=None,
        description="首个 chunk 成功推送的时间戳（time.monotonic()）。"
        "为 None 表示尚未推送任何 chunk。",
    )
    status: str = Field(
        default="CREATED",
        description="推送会话内部状态：CREATED|STREAMING|COMPLETED|ABORTED|EXPIRED。",
    )
    finish_reason: str | None = Field(
        default=None,
        description="推送终止原因，仅在 status 为 COMPLETED 或 ABORTED 时填充。",
    )
    ttft_ms: float | None = Field(
        default=None,
        description="首字延迟（TTFT），毫秒，从 created_at 到 first_chunk_sent_at 的差值。",
    )
    total_chunks: int = Field(
        default=0,
        ge=0,
        description="累计推送的 chunk 数量。",
    )


__all__ = [
    "ChunkEvent",
    "DoneEvent",
    "HeartbeatEvent",
    "ErrorEvent",
    "StreamErrorCode",
    "StreamSession",
]
