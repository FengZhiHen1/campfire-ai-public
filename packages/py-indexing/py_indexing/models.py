"""CASE-04 Pydantic 数据模型定义。

对外模型：
    - IndexTaskEnvelope: Redis List 异步任务载荷
    - ChunkMetadata: case_chunks.metadata JSONB 结构
    - EnqueueResult: enqueue_index_task() 返回字典结构

内部模型（不对外暴露）：
    - InternalIndexContext: Worker 内部处理上下文
    - EmbeddingResponse: 阿里 text-embedding-v4 API 返回的嵌入向量

字段名、类型、必填性与 docs/contracts/CASE-04/ 下的契约 JSON 一致。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ============================================================================
# 对外模型 — 与契约文件对齐
# ============================================================================


class IndexTaskEnvelope(BaseModel):
    """Redis List 异步任务载荷。

    契约引用: docs/contracts/CASE-04/IndexTaskEnvelope.json
    消费方: CASE-03（案例审核工作流）
    """

    case_id: str = Field(
        description="案例唯一标识，格式为标准 UUID v4",
    )
    trace_id: str = Field(
        pattern=r"^[a-f0-9]{32}$",
        description="贯穿索引入库全生命周期的追踪标识，32 位十六进制小写",
    )
    enqueued_at: str = Field(
        description="任务投递的 ISO 8601 时间戳",
    )


class ChunkMetadata(BaseModel):
    """case_chunks.metadata JSONB 字段的结构化定义。

    契约引用: docs/contracts/CASE-04/ChunkMetadata.json
    消费方: CSLT-02（RAG 语义检索）
    """

    behavior_type: str = Field(
        description="行为类型，对应 cases.behavior_type 枚举值",
    )
    age_range: str = Field(
        description="年龄区间，格式为 'min-max' 字符串",
    )
    severity: str = Field(
        description="严重程度枚举值",
    )
    evidence_level: str = Field(
        description="循证等级枚举值",
    )


# ============================================================================
# 内部模型（不对外暴露）
# ============================================================================


class InternalIndexContext(BaseModel):
    """Worker 内部处理上下文，不对外暴露。"""

    case_id: uuid.UUID = Field(description="正在处理的案例标识")
    trace_id: str = Field(
        pattern=r"^[a-f0-9]{32}$",
        description="全链路追踪标识",
    )
    retry_count: int = Field(
        default=0,
        ge=0,
        le=2,
        description="当前重试次数 (0=首次尝试, 1=重试1, 2=重试2)",
    )
    phase: str = Field(
        description="当前处理阶段: build_chunk_text | generate_embedding | write_index",
    )


class EmbeddingResponse(BaseModel):
    """阿里 text-embedding-v4 API 返回的嵌入向量（内部模型）。"""

    embedding: list[float] = Field(
        min_length=1024,
        max_length=1024,
        description="1024 维 float32 向量",
    )
    model: str = Field(
        default="text-embedding-v4",
        description="嵌入模型名称",
    )


# ============================================================================
# 类型别名
# ============================================================================

EnqueueResult = dict[Literal["status"], Literal["enqueued", "already_queued", "already_indexed"]]
"""enqueue_index_task() 返回字典结构。"""
